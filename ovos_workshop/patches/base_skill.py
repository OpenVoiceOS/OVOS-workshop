import time
from copy import copy
from threading import Event

from ovos_utils import camel_case_split, get_handler_name
from ovos_utils import ensure_mycroft_import
from ovos_utils.dialog import get_dialog
from ovos_utils.intents import ConverseTracker
from ovos_utils.log import LOG
from ovos_utils.messagebus import create_wrapper, Message, dig_for_message, get_message_lang

from ovos_workshop.decorators.killable import AbortEvent

ensure_mycroft_import()

from mycroft.skills.mycroft_skill.mycroft_skill import MycroftSkill as _MycroftSkill
from mycroft.skills.fallback_skill import FallbackSkill as _FallbackSkill


class PatchedMycroftSkill(_MycroftSkill):
    """ porting some features from ovos-core to mycroft-core """
    monkey_patched = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._converse_response = None
        self._original_converse = self.converse
        self._converse_event = Event()

    @property
    def lang(self):
        """Get the current active language."""
        lang = self.config_core.get("lang", "en-us").lower()
        message = dig_for_message()
        if message:
            lang = get_message_lang(message)
        return lang.lower()

    def _on_event_start(self, message, handler_info, skill_data):
        """Indicate that the skill handler is starting."""
        if handler_info:
            # Indicate that the skill handler is starting if requested
            msg_type = handler_info + '.start'
            message.context["skill_id"] = self.skill_id
            self.bus.emit(message.forward(msg_type, skill_data))

    def _on_event_end(self, message, handler_info, skill_data):
        """Store settings and indicate that the skill handler has completed
        """
        if self.settings != self._initial_settings:
            try:  # ovos-core
                self.settings.store()
                self._initial_settings = copy(self.settings)
            except:  # mycroft-core
                from mycroft.skills.settings import save_settings
                save_settings(self.settings_write_path, self.settings)
                self._initial_settings = dict(self.settings)
        if handler_info:
            msg_type = handler_info + '.complete'
            message.context["skill_id"] = self.skill_id
            self.bus.emit(message.forward(msg_type, skill_data))

    def _on_event_error(self, error, message, handler_info, skill_data, speak_errors):
        """Speak and log the error."""
        # Convert "MyFancySkill" to "My Fancy Skill" for speaking
        handler_name = camel_case_split(self.name)
        msg_data = {'skill': handler_name}
        speech = get_dialog('skill.error', self.lang, msg_data)
        if speak_errors:
            self.speak(speech)
        LOG.exception(error)
        # append exception information in message
        skill_data['exception'] = repr(error)
        if handler_info:
            # Indicate that the skill handler errored
            msg_type = handler_info + '.error'
            message = message or Message("")
            message.context["skill_id"] = self.skill_id
            self.bus.emit(message.forward(msg_type, skill_data))

    def add_event(self, name, handler, handler_info=None, once=False, speak_errors=True):
        """Create event handler for executing intent or other event.

        Args:
            name (string): IntentParser name
            handler (func): Method to call
            handler_info (string): Base message when reporting skill event
                                   handler status on messagebus.
            once (bool, optional): Event handler will be removed after it has
                                   been run once.
            speak_errors (bool, optional): Determines if an error dialog should be
                                           spoken to inform the user whenever
                                           an exception happens inside the handler
        """
        skill_data = {'name': get_handler_name(handler)}

        def on_error(error, message):
            if isinstance(error, AbortEvent):
                LOG.info("Skill execution aborted")
                self._on_event_end(message, handler_info, skill_data)
                return
            self._on_event_error(error, message, handler_info, skill_data, speak_errors)

        def on_start(message):
            self._on_event_start(message, handler_info, skill_data)

        def on_end(message):
            self._on_event_end(message, handler_info, skill_data)

        wrapper = create_wrapper(handler, self.skill_id, on_start, on_end,
                                 on_error)
        return self.events.add(name, wrapper, once)

    def __get_response(self):
        """Helper to get a reponse from the user

        Returns:
            str: user's response or None on a timeout
        """

        def converse(utterances, lang=None):
            self._converse_response = utterances[0] if utterances else None
            self._converse_event.set()
            return True

        self._converse_event = Event()
        self._converse_response = None
        self.converse = converse
        self.make_active()

        # 10 for listener, 5 for SST, then timeout
        # NOTE: self._converse_event.wait(15) is not used otherwise we can't raise the
        # AbortEvent exception to kill the thread
        start = time.time()
        while time.time() - start <= 15 and not self._converse_event.is_set():
            time.sleep(0.1)
            if self._converse_response is not False:
                if self._converse_response is None:
                    # aborted externally (if None)
                    self.log.debug("get_response aborted")
                self._converse_event.set()

        self.converse = self._original_converse
        return self._converse_response

    # https://github.com/MycroftAI/mycroft-core/pull/1468
    def _handle_skill_deactivated(self, message):
        """ intent service deactivated a skill
        if it was this skill fire the skill deactivation event"""
        if message.data.get("skill_id") == self.skill_id:
            self.bus.emit(message.forward(f"{self.skill_id}.deactivate"))

    def handle_deactivate(self, message):
        """ skill is no longer considered active by the intent service
        converse method will not be called, skills might want to reset state here
        """

    def _register_system_event_handlers(self):
        """Add all events allowing the standard interaction with the Mycroft
        system.
        """
        super()._register_system_event_handlers()
        ConverseTracker.connect_bus(self.bus)  # pull/1468
        self.add_event("intent.service.skills.deactivated",
                       self._handle_skill_deactivated)


class MycroftSkill(_MycroftSkill):
    monkey_patched = False

    def __new__(cls, *args, **kwargs):
        # TODO - check for dinkum, return a UnDinkumSkill
        try:
            from mycroft.version import OVOS_VERSION_STR
            return super().__new__(cls, *args, **kwargs)
        except ImportError:
            return PatchedMycroftSkill(*args, **kwargs)


class FallbackSkill(MycroftSkill, _FallbackSkill):
    """ """
