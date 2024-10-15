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
from typing import Optional, List

from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message, dig_for_message
from ovos_config import Configuration
from ovos_utils.events import get_handler_name
from ovos_utils.log import LOG
from ovos_utils.metrics import Stopwatch
from ovos_utils.skills import get_non_properties

from ovos_workshop.decorators.killable import AbortEvent, killable_event
from ovos_workshop.skills.ovos import OVOSSkill


class FallbackSkill(OVOSSkill):
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
    # "skill_id": priority (int)  overrides
    fallback_config = Configuration().get("skills", {}).get("fallbacks", {})

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
        self.add_event('ovos.skills.fallback.ping', self._handle_fallback_ack, speak_errors=False)
        self.add_event(f"ovos.skills.fallback.{self.skill_id}.request", self._handle_fallback_request,
                       speak_errors=False)

    def _handle_fallback_ack(self, message: Message):
        """
        Inform skills service we can handle fallbacks.
        """
        utts = message.data.get("utterances", [])
        lang = message.data.get("lang")
        self.bus.emit(message.reply("ovos.skills.fallback.pong",
                                    data={"skill_id": self.skill_id,
                                          "can_handle": self.can_answer(utts, lang)},
                                    context={"skill_id": self.skill_id}))

    def _on_timeout(self):
        """_handle_fallback_request timed out and was forcefully killed by ovos-core"""
        message = dig_for_message()
        self.bus.emit(message.forward(f"ovos.skills.fallback.{self.skill_id}.killed",
                                      data={"error": "timed out"}))

    @killable_event("ovos.skills.fallback.force_timeout",
                    callback=_on_timeout, check_skill_id=True)
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
                handler_name = get_handler_name(handler)
                # call handler, conditionally activating the skill
                status = self._conditional_activate(handler, message=message)
                if status:
                    # indicate completion
                    break
            except AbortEvent:
                LOG.debug(f"fallback handler '{handler_name}' killed because it timed out!")
            except Exception:
                LOG.exception('Exception in fallback.')
        else:
            status = False

        self.bus.emit(message.forward(
            f"ovos.skills.fallback.{self.skill_id}.response",
            data={"result": status, "fallback_handler": handler_name}))
        if status:
            self.bus.emit(message.forward("ovos.utterance.handled",
                                          {"handler": handler_name}))

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
