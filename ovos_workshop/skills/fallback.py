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

import operator
from typing import Optional, List, Callable, Tuple

from ovos_config import Configuration

from ovos_bus_client import MessageBusClient
from ovos_utils.log import LOG
from ovos_utils.events import get_handler_name
from ovos_bus_client.message import Message
from ovos_utils.metrics import Stopwatch
from ovos_utils.skills import get_non_properties
from ovos_workshop.decorators.compat import backwards_compat
from ovos_workshop.permissions import FallbackMode
from ovos_workshop.skills.ovos import OVOSSkill


class _MutableFallback(type(OVOSSkill)):
    """ To override isinstance checks we need to use a metaclass """

    def __instancecheck__(self, instance):
        if isinstance(instance, _MetaFB):
            return True
        return super().__instancecheck__(instance)


class _MetaFB(OVOSSkill):
    pass


class FallbackSkill(_MetaFB, metaclass=_MutableFallback):
    """
    Fallbacks come into play when no skill matches an Adapt or closely with
    a Padatious intent.  All Fallback skills work together to give them a
    view of the user's utterance.  Fallback handlers are called in an order
    determined the priority provided when the handler is registered.

    ========   ===========================================================
    Priority   Purpose
    ========   ===========================================================
       0-4     High-priority fallbacks before medium-confidence Padatious
      5-89     Medium-priority fallbacks between medium and low Padatious
    90-100     Low-priority fallbacks after all other intent matches

    Handlers with the numerically lowest priority are invoked first.
    Multiple fallbacks can exist at the same priority, but no order is
    guaranteed.

    A Fallback can either observe or consume an utterance. A consumed
    utterance will not be seen by any other Fallback handlers.
    """
    def __new__classic__(cls, *args, **kwargs):
        if cls is FallbackSkill:
            # direct instantiation of class, dynamic wizardry for unittests
            # return V2 as expected, V1 will eventually be dropped
            return FallbackSkillV2(*args, **kwargs)
        cls.__bases__ = (FallbackSkillV1, FallbackSkill, _MetaFB)
        return super().__new__(cls)

    @backwards_compat(classic_core=__new__classic__,
                      pre_008=__new__classic__)
    def __new__(cls, *args, **kwargs):
        if cls is FallbackSkill:
            # direct instantiation of class, dynamic wizardry for unittests
            # return V2 as expected, V1 will eventually be dropped
            return FallbackSkillV2(*args, **kwargs)
        cls.__bases__ = (FallbackSkillV2, FallbackSkill, _MetaFB)
        return super().__new__(cls)

    @classmethod
    def make_intent_failure_handler(cls, bus: MessageBusClient):
        """
        backwards compat, old version of ovos-core call this method to bind
        the bus to old class
        """
        return FallbackSkillV1.make_intent_failure_handler(bus)


class FallbackSkillV1(_MetaFB, metaclass=_MutableFallback):
    fallback_handlers = {}
    wrapper_map: List[Tuple[callable, callable]] = []  # [(handler, wrapper)]

    def __init__(self, name=None, bus=None, use_settings=True, **kwargs):
        #  list of fallback handlers registered by this instance
        self.instance_fallback_handlers = []
        # "skill_id": priority (int)  overrides
        self.fallback_config = Configuration()["skills"].get("fallbacks", {})

        super().__init__(name=name, bus=bus, **kwargs)

    @classmethod
    def make_intent_failure_handler(cls, bus: MessageBusClient):
        """
        Goes through all fallback handlers until one returns True
        """

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
    def _report_timing(ident: str, system: str, timing: Stopwatch,
                       additional_data: Optional[dict] = None):
        """
        Create standardized message for reporting timing.
        @param ident: identifier for user interaction
        @param system: identifier for system being timed
        @param timing: Stopwatch object with recorded timing
        @param additional_data: Optional dict data to include with metric
        """
        # TODO: Move to an imported function and deprecate this
        try:
            from mycroft.metrics import report_timing
            report_timing(ident, system, timing, additional_data)
        except ImportError:
            pass

    @classmethod
    def _register_fallback(cls, handler: callable, wrapper: callable,
                           priority: int):
        """
        Add a fallback handler to the class
        @param handler: original handler method used for reference
        @param wrapper: wrapped handler used to handle fallback requests
        @param priority: fallback priority
        """
        while priority in cls.fallback_handlers:
            priority += 1

        cls.fallback_handlers[priority] = wrapper
        cls.wrapper_map.append((handler, wrapper))

    def register_fallback(self, handler: Callable[[Message], None],
                          priority: int):
        """
        core >= 0.8.0 makes skill active
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
    def _remove_registered_handler(cls, wrapper_to_del: callable) -> bool:
        """
        Remove a registered wrapper.
        @param wrapper_to_del: wrapped handler to be removed
        @return: True if one or more handlers were removed, otherwise False.
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
    def remove_fallback(cls, handler_to_del: callable) -> bool:
        """
        Remove a fallback handler.
        @param handler_to_del: registered callback handler (or wrapped handler)
        @return: True if at least one handler was removed, otherwise False
        """
        # Find wrapper from handler or wrapper
        wrapper_to_del = None
        for h, w in cls.wrapper_map:
            if handler_to_del in (h, w):
                handler_to_del = h
                wrapper_to_del = w
                break

        if wrapper_to_del:
            cls.wrapper_map.remove((handler_to_del, wrapper_to_del))
            remove_ok = cls._remove_registered_handler(wrapper_to_del)
        else:
            LOG.warning('Could not find matching fallback handler')
            remove_ok = False
        return remove_ok

    def remove_instance_handlers(self):
        """
        Remove all fallback handlers registered by the fallback skill.
        """
        LOG.info('Removing all handlers...')
        while len(self.instance_fallback_handlers):
            handler = self.instance_fallback_handlers.pop()
            self.remove_fallback(handler)

    def default_shutdown(self):
        """
        Remove all registered handlers and perform skill shutdown.
        """
        self.remove_instance_handlers()
        super().default_shutdown()

    def _register_decorated(self):
        """
        Register all decorated fallback handlers.

        Looks for all functions that have been marked by a decorator
        and read the fallback priority from them. The handlers aren't the
        only decorators used. Skip properties as calling getattr on them
        executes the code which may have unintended side effects.
        """
        super()._register_decorated()
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'fallback_priority'):
                self.register_fallback(method, method.fallback_priority)


class FallbackSkillV2(_MetaFB, metaclass=_MutableFallback):
    # "skill_id": priority (int)  overrides
    fallback_config = Configuration().get("skills", {}).get("fallbacks", {})

    @classmethod
    def make_intent_failure_handler(cls, bus: MessageBusClient):
        """
        backwards compat, old version of ovos-core call this method to bind
        the bus to old class
        """
        return FallbackSkillV1.make_intent_failure_handler(bus)

    def __init__(self, bus=None, skill_id="", **kwargs):
        self._fallback_handlers = []
        super().__init__(bus=bus, skill_id=skill_id, **kwargs)

    @property
    def priority(self) -> int:
        """
        Get this skill's minimum priority. Priority is determined as:
            1) Configured fallback skill priority
            2) Highest fallback handler priority
            3) Default `101` (no fallback handlers are registered)
        """
        priority_overrides = self.fallback_config.get("fallback_priorities", {})
        if self.skill_id in priority_overrides:
            return priority_overrides.get(self.skill_id)
        if len(self._fallback_handlers):
            return min([p[0] for p in self._fallback_handlers])
        return 101

    def can_answer(self, utterances: List[str], lang: str) -> bool:
        """
        Check if the skill can answer the particular question. Override this
        method to validate whether a query can possibly be handled. By default,
        assumes a skill can answer if it has any registered handlers
        @param utterances: list of possible transcriptions to parse
        @param lang: BCP-47 language code associated with utterances
        @return: True if skill can handle the query
        """
        return len(self._fallback_handlers) > 0

    def _register_system_event_handlers(self):
        """
        Register messagebus event handlers and emit a message to register this
        fallback skill.
        """
        super()._register_system_event_handlers()
        self.add_event('ovos.skills.fallback.ping', self._handle_fallback_ack,
                       speak_errors=False)
        self.add_event(f"ovos.skills.fallback.{self.skill_id}.request",
                       self._handle_fallback_request, speak_errors=False)

    def _handle_fallback_ack(self, message: Message):
        """
        Inform skills service we can handle fallbacks.
        """
        utts = message.data.get("utterances", [])
        lang = message.data.get("lang")
        self.bus.emit(message.reply(
            "ovos.skills.fallback.pong",
            data={"skill_id": self.skill_id,
                  "can_handle": self.can_answer(utts, lang)},
            context={"skill_id": self.skill_id}))

    def _handle_fallback_request(self, message: Message):
        """
        Handle a fallback request, calling any registered handlers in priority
        order until one is successful. emits a response indicating whether the
        request was handled.
        @param message: `ovos.skills.fallback.<skill_id>.request` message
        """
        # indicate fallback handling start
        self.bus.emit(message.forward(
            f"ovos.skills.fallback.{self.skill_id}.start"))

        handler_name = None

        # each skill can register multiple handlers with different priorities
        sorted_handlers = sorted(self._fallback_handlers,
                                 key=operator.itemgetter(0))
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

        self.bus.emit(message.forward(
            f"ovos.skills.fallback.{self.skill_id}.response",
            data={"result": status, "fallback_handler": handler_name}))

    def _old_register_fallback(self, handler: callable, priority: int):
        """
        makes the skill active, done by core >= 0.0.8
        """

        LOG.info(f"registering fallback handler -> "
                 f"ovos.skills.fallback.{self.skill_id}")

        def wrapper(*args, **kwargs):
            if handler(*args, **kwargs):
                self.activate()
                return True
            return False

        self._fallback_handlers.append((priority, wrapper))
        self.bus.on(f"ovos.skills.fallback.{self.skill_id}", wrapper)
        # register with fallback service
        self.bus.emit(Message("ovos.skills.fallback.register",
                              {"skill_id": self.skill_id,
                               "priority": self.priority}))

    @backwards_compat(classic_core=_old_register_fallback, pre_008=_old_register_fallback)
    def register_fallback(self, handler: callable, priority: int):
        """
        Register a fallback handler and add a messagebus handler to call it on
        any fallback request.
        @param handler: Fallback handler
        @param priority: priority of the registered handler
        """

        LOG.info(f"registering fallback handler -> "
                 f"ovos.skills.fallback.{self.skill_id}")
        self._fallback_handlers.append((priority, handler))
        self.bus.on(f"ovos.skills.fallback.{self.skill_id}", handler)
        # register with fallback service
        self.bus.emit(Message("ovos.skills.fallback.register",
                              {"skill_id": self.skill_id,
                               "priority": self.priority}))
    
    def remove_fallback(self, handler_to_del: Optional[callable] = None) -> bool:
        """
        Remove fallback registration / fallback handler.
        @param handler_to_del: registered callback handler (or wrapped handler)
        @return: True if at least one handler was removed, otherwise False
        """
        found_handler = False
        for i in reversed(range(len(self._fallback_handlers))):
            _, handler = self._fallback_handlers[i]
            if handler_to_del is None or handler == handler_to_del:
                found_handler = True
                del self._fallback_handlers[i]

        if not found_handler:
            LOG.warning('No fallback matching {}'.format(handler_to_del))
        if len(self._fallback_handlers) == 0:
            self.bus.emit(Message("ovos.skills.fallback.deregister",
                          {"skill_id": self.skill_id}))
        return found_handler

    def default_shutdown(self):
        """
        Remove all registered handlers and perform skill shutdown.
        """
        self.bus.emit(Message("ovos.skills.fallback.deregister",
                              {"skill_id": self.skill_id}))
        self.bus.remove_all_listeners(f"ovos.skills.fallback.{self.skill_id}")
        super().default_shutdown()

    def _register_decorated(self):
        """
        Register all decorated fallback handlers.

        Looks for all functions that have been marked by a decorator
        and read the fallback priority from them. The handlers aren't the
        only decorators used. Skip properties as calling getattr on them
        executes the code which may have unintended side effects.
        """
        super()._register_decorated()
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'fallback_priority'):
                self.register_fallback(method, method.fallback_priority)
