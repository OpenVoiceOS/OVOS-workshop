# Copyright 2019 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""The fallback skill implements a special type of skill handling
utterances not handled by the intent system.
"""
import operator

from ovos_utils.log import LOG
from ovos_utils.messagebus import get_handler_name, Message
from ovos_utils.metrics import Stopwatch
from ovos_utils.skills import get_non_properties
from ovos_config import Configuration
from ovos_workshop.permissions import FallbackMode
from ovos_workshop.skills.ovos import OVOSSkill, is_classic_core


class _MutableFallback(type(OVOSSkill)):
    """ To override isinstance checks we need to use a metaclass """

    def __instancecheck__(self, instance):
        if isinstance(instance, _MetaFB):
            return True
        return super().__instancecheck__(instance)


class _MetaFB(OVOSSkill):
    pass


class FallbackSkill(_MetaFB, metaclass=_MutableFallback):
    def __new__(cls, *args, **kwargs):
        if cls is FallbackSkill:
            # direct instantiation of class, dynamic wizardry or unittests going on...
            # return V2 as expected, V1 will eventually be dropped
            return FallbackSkillV2(*args, **kwargs)

        is_old = is_classic_core()
        if not is_old:
            try:
                from mycroft.version import OVOS_VERSION_MAJOR, OVOS_VERSION_MINOR, OVOS_VERSION_BUILD, OVOS_VERSION_ALPHA
                if OVOS_VERSION_MAJOR == 0 and OVOS_VERSION_MINOR == 0 and OVOS_VERSION_BUILD < 8:
                    is_old = True
                elif OVOS_VERSION_MAJOR == 0 and OVOS_VERSION_MINOR == 0 and OVOS_VERSION_BUILD == 8 \
                        and 0 < OVOS_VERSION_ALPHA < 5:
                    is_old = True
            except ImportError:
                pass
        if is_old:
            cls.__bases__ = (FallbackSkillV1, FallbackSkill, _MetaFB)
        else:
            cls.__bases__ = (FallbackSkillV2, FallbackSkill, _MetaFB)
        return super().__new__(cls, *args, **kwargs)

    @classmethod
    def make_intent_failure_handler(cls, bus):
        """backwards compat, old version of ovos-core call this method to bind the bus to old class"""
        return FallbackSkillV1.make_intent_failure_handler(bus)



class FallbackSkillV1(_MetaFB, metaclass=_MutableFallback):
    """Fallbacks come into play when no skill matches an Adapt or closely with
    a Padatious intent.  All Fallback skills work together to give them a
    view of the user's utterance.  Fallback handlers are called in an order
    determined the priority provided when the the handler is registered.

    ========   ========   ================================================
    Priority   Who?       Purpose
    ========   ========   ================================================
       1-4     RESERVED   Unused for now, slot for pre-Padatious if needed
         5     MYCROFT    Padatious near match (conf > 0.8)
      6-88     USER       General
        89     MYCROFT    Padatious loose match (conf > 0.5)
     90-99     USER       Uncaught intents
       100+    MYCROFT    Fallback Unknown or other future use
    ========   ========   ================================================

    Handlers with the numerically lowest priority are invoked first.
    Multiple fallbacks can exist at the same priority, but no order is
    guaranteed.

    A Fallback can either observe or consume an utterance. A consumed
    utterance will not be see by any other Fallback handlers.
    """
    fallback_handlers = {}
    wrapper_map = []  # Map containing (handler, wrapper) tuples

    def __init__(self, name=None, bus=None, use_settings=True):
        super().__init__(name, bus, use_settings)
        #  list of fallback handlers registered by this instance
        self.instance_fallback_handlers = []

        # "skill_id": priority (int)  overrides
        self.fallback_config = self.config_core["skills"].get("fallbacks", {})

    @classmethod
    def make_intent_failure_handler(cls, bus):
        """Goes through all fallback handlers until one returns True"""

        def handler(message):
            # No hard limit to 100, while not officially supported
            # mycroft-lib can handle fallback priorities up to 999
            start, stop = message.data.get('fallback_range', (0, 1000))
            # indicate fallback handling start
            LOG.debug('Checking fallbacks in range '
                      '{} - {}'.format(start, stop))
            bus.emit(message.forward("mycroft.skill.handler.start",
                                     data={'handler': "fallback"}))

            stopwatch = Stopwatch()
            handler_name = None
            with stopwatch:
                sorted_handlers = sorted(cls.fallback_handlers.items(),
                                         key=operator.itemgetter(0))
                handlers = [f[1] for f in sorted_handlers
                            if start <= f[0] < stop]
                for handler in handlers:
                    try:
                        if handler(message):
                            # indicate completion
                            status = True
                            handler_name = get_handler_name(handler)
                            bus.emit(message.forward(
                                'mycroft.skill.handler.complete',
                                data={'handler': "fallback",
                                      "fallback_handler": handler_name}))
                            break
                    except Exception:
                        LOG.exception('Exception in fallback.')
                else:
                    status = False
                    #  indicate completion with exception
                    warning = 'No fallback could handle intent.'
                    bus.emit(message.forward('mycroft.skill.handler.complete',
                                             data={'handler': "fallback",
                                                   'exception': warning}))

            # return if the utterance was handled to the caller
            bus.emit(message.response(data={'handled': status}))

            # Send timing metric
            if message.context.get('ident'):
                ident = message.context['ident']
                cls._report_timing(ident, 'fallback_handler', stopwatch,
                                   {'handler': handler_name})

        return handler

    @staticmethod
    def _report_timing(ident, system, timing, additional_data=None):
        """Create standardized message for reporting timing.

        Args:
            ident (str):            identifier of user interaction
            system (str):           system the that's generated the report
            timing (stopwatch):     Stopwatch object with recorded timing
            additional_data (dict): dictionary with related data
        """
        try:
            from mycroft.metrics import report_timing
            report_timing(ident, system, timing, additional_data)
        except ImportError:
            pass

    @classmethod
    def _register_fallback(cls, handler, wrapper, priority):
        """Register a function to be called as a general info fallback
        Fallback should receive message and return
        a boolean (True if succeeded or False if failed)

        Lower priority gets run first
        0 for high priority 100 for low priority

        Args:
            handler (callable): original handler, used as a reference when
                                removing
            wrapper (callable): wrapped version of handler
            priority (int): fallback priority
        """
        while priority in cls.fallback_handlers:
            priority += 1

        cls.fallback_handlers[priority] = wrapper
        cls.wrapper_map.append((handler, wrapper))

    def register_fallback(self, handler, priority):
        """Register a fallback with the list of fallback handlers and with the
        list of handlers registered by this instance
        """
        opmode = self.fallback_config.get("fallback_mode",
                                          FallbackMode.ACCEPT_ALL)
        priority_overrides = self.fallback_config.get("fallback_priorities", {})
        fallback_blacklist = self.fallback_config.get("fallback_blacklist", [])
        fallback_whitelist = self.fallback_config.get("fallback_whitelist", [])

        if opmode == FallbackMode.BLACKLIST and \
                self.skill_id in fallback_blacklist:
            return
        if opmode == FallbackMode.WHITELIST and \
                self.skill_id not in fallback_whitelist:
            return

        # check if .conf is overriding the priority for this skill
        priority = priority_overrides.get(self.skill_id, priority)

        def wrapper(*args, **kwargs):
            if handler(*args, **kwargs):
                self.activate()
                return True
            return False

        self.instance_fallback_handlers.append(handler)
        self._register_fallback(handler, wrapper, priority)

    @classmethod
    def _remove_registered_handler(cls, wrapper_to_del):
        """Remove a registered wrapper.

        Args:
            wrapper_to_del (callable): wrapped handler to be removed

        Returns:
            (bool) True if one or more handlers were removed, otherwise False.
        """
        found_handler = False
        for priority, handler in list(cls.fallback_handlers.items()):
            if handler == wrapper_to_del:
                found_handler = True
                del cls.fallback_handlers[priority]

        if not found_handler:
            LOG.warning('No fallback matching {}'.format(wrapper_to_del))
        return found_handler

    @classmethod
    def remove_fallback(cls, handler_to_del):
        """Remove a fallback handler.

        Args:
            handler_to_del: reference to handler
        Returns:
            (bool) True if at least one handler was removed, otherwise False
        """
        # Find wrapper from handler or wrapper
        wrapper_to_del = None
        for h, w in cls.wrapper_map:
            if handler_to_del in (h, w):
                wrapper_to_del = w
                break

        if wrapper_to_del:
            cls.wrapper_map.remove((h, w))
            remove_ok = cls._remove_registered_handler(wrapper_to_del)
        else:
            LOG.warning('Could not find matching fallback handler')
            remove_ok = False
        return remove_ok

    def remove_instance_handlers(self):
        """Remove all fallback handlers registered by the fallback skill."""
        self.log.info('Removing all handlers...')
        while len(self.instance_fallback_handlers):
            handler = self.instance_fallback_handlers.pop()
            self.remove_fallback(handler)

    def default_shutdown(self):
        """Remove all registered handlers and perform skill shutdown."""
        self.remove_instance_handlers()
        super().default_shutdown()

    def _register_decorated(self):
        """Register all intent handlers that are decorated with an intent.

        Looks for all functions that have been marked by a decorator
        and read the intent data from them.  The intent handlers aren't the
        only decorators used.  Skip properties as calling getattr on them
        executes the code which may have unintended side-effects
        """
        super()._register_decorated()
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'fallback_priority'):
                self.register_fallback(method, method.fallback_priority)


class FallbackSkillV2(_MetaFB, metaclass=_MutableFallback):
    """
    Fallbacks come into play when no skill matches an intent.

    Fallback handlers are called in an order determined the
    priority provided when the skill is registered.

    ========   ========   ================================================
    Priority   Who?       Purpose
    ========   ========   ================================================
       1-4     RESERVED   Unused for now, slot for pre-Padatious if needed
         5     MYCROFT    Padatious near match (conf > 0.8)
      6-88     USER       General
        89     MYCROFT    Padatious loose match (conf > 0.5)
     90-99     USER       Uncaught intents
       100+    MYCROFT    Fallback Unknown or other future use
    ========   ========   ================================================

    Handlers with the numerically lowest priority are invoked first.
    Multiple fallbacks can exist at the same priority, but no order is
    guaranteed.

    A Fallback can either observe or consume an utterance. A consumed
    utterance will not be see by any other Fallback handlers.

    A skill might register several handlers, the lowest priority will be reported to core
    If a skill is selected by core then all handlers are checked by
    their priority until one can handle the utterance

    A skill may return False in the can_answer method to request
    that core does not execute it's fallback handlers
    """

    # "skill_id": priority (int)  overrides
    fallback_config = Configuration().get("skills", {}).get("fallbacks", {})

    @classmethod
    def make_intent_failure_handler(cls, bus):
        """backwards compat, old version of ovos-core call this method to bind the bus to old class"""
        return FallbackSkillV1.make_intent_failure_handler(bus)

    def __init__(self, bus=None, skill_id=""):
        self._fallback_handlers = []
        super().__init__(bus=bus, skill_id=skill_id)

    @property
    def priority(self):
        priority_overrides = self.fallback_config.get("fallback_priorities", {})
        if self.skill_id in priority_overrides:
            return priority_overrides.get(self.skill_id)
        if len(self._fallback_handlers):
            return min([p[0] for p in self._fallback_handlers])
        return 101

    def can_answer(self, utterances, lang):
        """Check if the skill can answer the particular question.


        Arguments:
            utterances (list): list of possible transcriptions to parse
            lang (str) : lang code
        Returns:
            (bool) True if skill can handle the query
        """
        return len(self._fallback_handlers) > 0

    def _register_system_event_handlers(self):
        """Add all events allowing the standard interaction with the Mycroft
        system.
        """
        super()._register_system_event_handlers()
        self.add_event('ovos.skills.fallback.ping', self._handle_fallback_ack, speak_errors=False)
        self.add_event(f"ovos.skills.fallback.{self.skill_id}.request", self._handle_fallback_request, speak_errors=False)
        self.bus.emit(Message("ovos.skills.fallback.register",
                              {"skill_id": self.skill_id, "priority": self.priority}))

    def _handle_fallback_ack(self, message):
        """Inform skills service we can handle fallbacks."""
        utts = message.data.get("utterances", [])
        lang = message.data.get("lang")
        self.bus.emit(message.reply(
            "ovos.skills.fallback.pong",
            data={"skill_id": self.skill_id,
                  "can_handle": self.can_answer(utts, lang)},
            context={"skill_id": self.skill_id}))

    def _handle_fallback_request(self, message):
        # indicate fallback handling start
        self.bus.emit(message.forward(f"ovos.skills.fallback.{self.skill_id}.start"))

        handler_name = None

        # each skill can register multiple handlers with different priorities
        sorted_handlers = sorted(self._fallback_handlers, key=operator.itemgetter(0))
        for prio, handler in sorted_handlers:
            try:
                if handler(message):
                    # indicate completion
                    status = True
                    handler_name = get_handler_name(handler)
                    break
            except Exception:
                LOG.exception('Exception in fallback.')
        else:
            status = False

        self.bus.emit(message.forward(f"ovos.skills.fallback.{self.skill_id}.response",
                                      data={"result": status,
                                            "fallback_handler": handler_name}))

    def register_fallback(self, handler, priority):
        """Register a fallback with the list of fallback handlers and with the
        list of handlers registered by this instance
        """

        LOG.info(f"registering fallback handler -> ovos.skills.fallback.{self.skill_id}")

        def wrapper(*args, **kwargs):
            if handler(*args, **kwargs):
                self.activate()
                return True
            return False

        self._fallback_handlers.append((priority, wrapper))
        self.bus.on(f"ovos.skills.fallback.{self.skill_id}", wrapper)

    def default_shutdown(self):
        """Remove all registered handlers and perform skill shutdown."""
        self.bus.emit(Message("ovos.skills.fallback.deregister", {"skill_id": self.skill_id}))
        self.bus.remove_all_listeners(f"ovos.skills.fallback.{self.skill_id}")
        super().default_shutdown()

    def _register_decorated(self):
        """Register all intent handlers that are decorated with an intent.

        Looks for all functions that have been marked by a decorator
        and read the intent data from them.  The intent handlers aren't the
        only decorators used.  Skip properties as calling getattr on them
        executes the code which may have unintended side-effects
        """
        super()._register_decorated()
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'fallback_priority'):
                self.register_fallback(method, method.fallback_priority)
