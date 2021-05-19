import time
from copy import deepcopy

from ovos_utils.log import LOG
from ovos_utils import camel_case_split, get_handler_name
from ovos_utils.messagebus import Message
from ovos_utils.skills.settings import PrivateSettings

# ensure mycroft can be imported
from ovos_utils import ensure_mycroft_import
ensure_mycroft_import()
from adapt.intent import Intent, IntentBuilder
from mycroft import dialog
from mycroft.skills.mycroft_skill.event_container import create_wrapper
from mycroft.skills.settings import get_local_settings, save_settings
from mycroft.skills.mycroft_skill.mycroft_skill import get_non_properties
from ovos_workshop.patches.base_skill import MycroftSkill, FallbackSkill
from ovos_workshop.skills.decorators.killable import killable_event, \
    AbortEvent, AbortQuestion
from ovos_workshop.skills.layers import IntentLayers


class OVOSSkill(MycroftSkill):
    """
    New features:
        - all patches for MycroftSkill class
        - self.private_settings
        - killable intents
        - IntentLayers
    """
    def __init__(self, *args, **kwargs):
        super(OVOSSkill, self).__init__(*args, **kwargs)
        self.private_settings = None
        self._threads = []
        self._original_converse = self.converse
        self.intent_layers = IntentLayers()

    def bind(self, bus):
        super().bind(bus)
        if bus:
            # here to ensure self.skill_id is populated
            self.private_settings = PrivateSettings(self.skill_id)
            self.intent_layers.bind(self)

    def voc_match(self, *args, **kwargs):
        try:
            return super().voc_match(*args, **kwargs)
        except FileNotFoundError:
            return False

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
            if hasattr(method, 'intent_layers'):
                for layer_name, intent_files in \
                        getattr(method, 'intent_layers').items():
                    self.register_intent_layer(layer_name, intent_files)
            # TODO support for multiple converse handler
            if hasattr(method, 'converse'):
                self.converse = method

    def register_intent_layer(self, layer_name, intent_list):
        for intent_file in intent_list:
            if isinstance(intent_file, IntentBuilder):
                intent = intent_file.build()
                name = intent.name
            elif isinstance(intent_file, Intent):
                name = intent_file.name
            else:
                name = f'{self.skill_id}:{intent_file}'
            self.intent_layers.update_layer(layer_name, [name])

    # this method can probably use a better refactor, we are only changing one
    # of the internal callbacks
    def add_event(self, name, handler, handler_info=None, once=False):
        """Create event handler for executing intent or other event.

        Arguments:
            name (string): IntentParser name
            handler (func): Method to call
            handler_info (string): Base message when reporting skill event
                                   handler status on messagebus.
            once (bool, optional): Event handler will be removed after it has
                                   been run once.
        """
        skill_data = {'name': get_handler_name(handler)}

        def on_error(e):
            """Speak and log the error."""
            if not isinstance(e, AbortEvent):
                # Convert "MyFancySkill" to "My Fancy Skill" for speaking
                handler_name = camel_case_split(self.name)
                msg_data = {'skill': handler_name}
                msg = dialog.get('skill.error', self.lang, msg_data)
                self.speak(msg)
                LOG.exception(msg)
            else:
                LOG.info("Skill execution aborted")
            # append exception information in message
            skill_data['exception'] = repr(e)

        def on_start(message):
            """Indicate that the skill handler is starting."""
            if handler_info:
                # Indicate that the skill handler is starting if requested
                msg_type = handler_info + '.start'
                message.context["skill_id"] = self.skill_id
                self.bus.emit(message.forward(msg_type, skill_data))

        def on_end(message):
            """Store settings and indicate that the skill handler has completed
            """
            if self.settings != self._initial_settings:
                save_settings(self.settings_write_path, self.settings)
                self._initial_settings = deepcopy(self.settings)
            if handler_info:
                msg_type = handler_info + '.complete'
                message.context["skill_id"] = self.skill_id
                self.bus.emit(message.forward(msg_type, skill_data))

        wrapper = create_wrapper(handler, self.skill_id,
                                 on_start, on_end, on_error)
        return self.events.add(name, wrapper, once)

    def __handle_stop(self, _):
        self.bus.emit(Message(self.skill_id + ".stop",
                              context={"skill_id": self.skill_id}))
        super().__handle_stop(_)

    # abort get_response gracefully
    def _wait_response(self, is_cancel, validator, on_fail, num_retries):
        """Loop until a valid response is received from the user or the retry
        limit is reached.

        Arguments:
            is_cancel (callable): function checking cancel criteria
            validator (callbale): function checking for a valid response
            on_fail (callable): function handling retries

        """
        self._response = False
        self._real_wait_response(is_cancel, validator, on_fail, num_retries)
        while self._response is False:
            time.sleep(0.1)
        return self._response

    def __get_response(self):
        """Helper to get a reponse from the user

        Returns:
            str: user's response or None on a timeout
        """

        def converse(utterances, lang=None):
            converse.response = utterances[0] if utterances else None
            converse.finished = True
            return True

        # install a temporary conversation handler
        self.make_active()
        converse.finished = False
        converse.response = None
        self.converse = converse

        # 10 for listener, 5 for SST, then timeout
        # NOTE a threading event is not used otherwise we can't raise the
        # AbortEvent exception to kill the thread
        start = time.time()
        while time.time() - start <= 15 and not converse.finished:
            time.sleep(0.1)
            if self._response is not False:
                if self._response is None:
                    # aborted externally (if None)
                    self.log.debug("get_response aborted")
                converse.finished = True
                converse.response = self._response  # external override
        self.converse = self._original_converse
        return converse.response

    def _handle_killed_wait_response(self):
        self._response = None
        self.converse = self._original_converse

    @killable_event("mycroft.skills.abort_question", exc=AbortQuestion,
                    callback=_handle_killed_wait_response, react_to_stop=True)
    def _real_wait_response(self, is_cancel, validator, on_fail, num_retries):
        """Loop until a valid response is received from the user or the retry
        limit is reached.

        Arguments:
            is_cancel (callable): function checking cancel criteria
            validator (callbale): function checking for a valid response
            on_fail (callable): function handling retries

        """
        num_fails = 0
        while True:
            if self._response is not False:
                # usually None when aborted externally
                # also allows overriding returned result from other events
                return self._response

            response = self.__get_response()

            if response is None:
                # if nothing said, prompt one more time
                num_none_fails = 1 if num_retries < 0 else num_retries
                if num_fails >= num_none_fails:
                    self._response = None
                    return
            else:
                if validator(response):
                    self._response = response
                    return

                # catch user saying 'cancel'
                if is_cancel(response):
                    self._response = None
                    return

            num_fails += 1
            if 0 < num_retries < num_fails or self._response is not False:
                self._response = None
                return

            line = on_fail(response)
            if line:
                self.speak(line, expect_response=True)
            else:
                self.bus.emit(Message('mycroft.mic.listen',
                                      context={"skill_id": self.skill_id}))


class OVOSFallbackSkill(FallbackSkill, OVOSSkill):
    """ monkey patched mycroft fallback skill """

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

