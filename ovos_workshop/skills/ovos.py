import re
from threading import Event

from typing import List, Optional, Union

from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message, dig_for_message
from ovos_utils.intents import IntentBuilder, Intent
from ovos_utils.log import LOG, log_deprecation
from ovos_utils.skills import get_non_properties
from ovos_utils.skills.audioservice import OCPInterface
from ovos_utils.skills.settings import PrivateSettings
from ovos_utils.sound import play_audio
from ovos_workshop.resource_files import SkillResources

from ovos_workshop.skills.layers import IntentLayers
from ovos_workshop.skills.mycroft_skill import MycroftSkill, is_classic_core


class OVOSSkill(MycroftSkill):
    """
    New features:
        - all patches for MycroftSkill class
        - self.private_settings
        - killable intents
        - IntentLayers
    """

    def __init__(self, *args, **kwargs):
        # note - define these before super() because of self.bind()
        self.private_settings = None
        self._threads = []
        self._original_converse = self.converse
        self.intent_layers = IntentLayers()
        self.audio_service = None
        super(OVOSSkill, self).__init__(*args, **kwargs)

    def bind(self, bus: MessageBusClient):
        super().bind(bus)
        if bus:
            # here to ensure self.skill_id is populated
            self.private_settings = PrivateSettings(self.skill_id)
            self.intent_layers.bind(self)
            self.audio_service = OCPInterface(self.bus)

    # new public api, these are not available in MycroftSkill
    @property
    def is_fully_initialized(self) -> bool:
        """
        Determines if the skill has been fully loaded and setup.
        When True, all data has been loaded and all internal state
        and events set up.
        """
        return self._is_fully_initialized

    @property
    def stop_is_implemented(self) -> bool:
        """
        True if this skill implements a `stop` method
        """
        return self._stop_is_implemented

    @property
    def converse_is_implemented(self) -> bool:
        """
        True if this skill implements a `converse` method
        """
        return self._converse_is_implemented

    @property
    def core_lang(self) -> str:
        """
        Get the configured default language as a BCP-47 language code.
        """
        return self._core_lang

    @property
    def secondary_langs(self) -> List[str]:
        """
        Get the configured secondary languages; resources will be loaded for
        these languages to provide support for multilingual input, in addition
        to `core_lang`. A skill may override this method to specify which
        languages intents are registered in.
        """
        return self._secondary_langs

    @property
    def native_langs(self) -> List[str]:
        """
        Languages natively supported by this skill (ie, resource files available
        and explicitly supported). This is equivalent to normalized
        secondary_langs + core_lang.
        """
        return self._native_langs

    @property
    def alphanumeric_skill_id(self) -> str:
        """
        Skill id converted to only alphanumeric characters and "_".
        Non alphanumeric characters are converted to "_"
        """
        return self._alphanumeric_skill_id

    @property
    def resources(self) -> SkillResources:
        """
        Get a SkillResources object for the current language. Objects are
        initialized for the current language as needed.
        """
        return self._resources

    def activate(self):
        """
        Mark this skill as active and push to the top of the active skills list.
        This enables converse method to be called even without skill being
        used in last 5 minutes.
        """
        self._activate()

    def deactivate(self):
        """
        Mark this skill as inactive and remove from the active skills list.
        This stops converse method from being called.
        """
        self._deactivate()

    def play_audio(self, filename: str):
        """
        Queue and audio file for playback
        @param filename: File to play
        """
        core_supported = False
        if not is_classic_core():
            try:
                from mycroft.version import OVOS_VERSION_BUILD, \
                    OVOS_VERSION_MINOR, OVOS_VERSION_MAJOR
                if OVOS_VERSION_MAJOR >= 1 or \
                        OVOS_VERSION_MINOR > 0 or \
                        OVOS_VERSION_BUILD >= 4:
                    core_supported = True  # min version of ovos-core
            except ImportError:
                # skills don't require core anymore, running standalone
                core_supported = True 

        if core_supported:
            message = dig_for_message() or Message("")
            self.bus.emit(message.forward("mycroft.audio.queue",
                                          {"filename": filename}))
        else:
            LOG.warning("self.play_audio requires ovos-core >= 0.0.4a45, "
                        "falling back to local skill playback")
            play_audio(filename).wait()

    def load_lang(self, root_directory: Optional[str] = None,
                  lang: Optional[str] = None):
        """
        Get a SkillResources object for this skill in the requested `lang` for
        resource files in the requested `root_directory`.
        @param root_directory: root path to find resources (default res_dir)
        @param lang: language to get resources for (default self.lang)
        @return: SkillResources object
        """
        return self._load_lang(root_directory, lang)

    def voc_match(self, *args, **kwargs) -> Union[str, bool]:
        """
        Wraps the default `voc_match` method, but returns `False` instead of
        raising FileNotFoundError when a resource can't be resolved
        """
        try:
            return super().voc_match(*args, **kwargs)
        except FileNotFoundError:
            return False

    def voc_list(self, voc_filename: str,
                 lang: Optional[str] = None) -> List[str]:
        """
        Get list of vocab options for the requested resource and cache the
        results for future references.
        @param voc_filename: Name of vocab resource to get options for
        @param lang: language to get vocab for (default self.lang)
        @return: list of string vocab options
        """
        return self._voc_list(voc_filename, lang)

    def remove_voc(self, utt: str, voc_filename: str,
                   lang: Optional[str] = None) -> str:
        """
        Removes any vocab match from the utterance.
        @param utt: Utterance to evaluate
        @param voc_filename: vocab resource to remove from utt
        @param lang: Optional language associated with vocab and utterance
        @return: string with vocab removed
        """
        if utt:
            # Check for matches against complete words
            for i in self.voc_list(voc_filename, lang):
                # Substitute only whole words matching the token
                utt = re.sub(r'\b' + i + r"\b", "", utt)

        return utt

    def _register_decorated(self):
        """
        Register all intent handlers that are decorated with an intent.

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

            # TODO support for multiple converse handlers (?)
            if hasattr(method, 'converse'):
                self.converse = method

    def register_intent_layer(self, layer_name: str,
                              intent_list: List[Union[IntentBuilder, Intent,
                                                str]]):
        """
        Register a named intent layer.
        @param layer_name: Name of intent layer to add
        @param intent_list: List of intents associated with the intent layer
        """
        for intent_file in intent_list:
            if IntentBuilder is not None and isinstance(intent_file, IntentBuilder):
                intent = intent_file.build()
                name = intent.name
            elif Intent is not None and isinstance(intent_file, Intent):
                name = intent_file.name
            else:
                name = f'{self.skill_id}:{intent_file}'
            self.intent_layers.update_layer(layer_name, [name])

    # killable_events support
    def send_stop_signal(self, stop_event: Optional[str] = None):
        """
        Notify services to stop current execution
        @param stop_event: optional `stop` event name to forward
        """
        waiter = Event()
        msg = dig_for_message() or Message("mycroft.stop")
        # stop event execution
        if stop_event:
            self.bus.emit(msg.forward(stop_event))

        # stop TTS
        self.bus.emit(msg.forward("mycroft.audio.speech.stop"))

        # Tell ovos-core to stop recording (not in mycroft-core)
        self.bus.emit(msg.forward('recognizer_loop:record_stop'))

        # special non-ovos handling
        if is_classic_core():
            # NOTE: mycroft does not have an event to stop recording
            # this attempts to force a stop by sending silence to end STT step
            self.bus.emit(Message('mycroft.mic.mute'))
            waiter.wait(1.5)  # the silence from muting should make STT stop recording
            self.bus.emit(Message('mycroft.mic.unmute'))

        # TODO: register TTS events to track state instead of guessing
        waiter.wait(0.5)  # if TTS had not yet started
        self.bus.emit(msg.forward("mycroft.audio.speech.stop"))


# backwards compat alias, no functional difference
class OVOSFallbackSkill(OVOSSkill):
    def __new__(cls, *args, **kwargs):
        log_deprecation("Implement "
                        "`ovos_workshop.skills.fallback.FallbackSkill`",
                        "0.1.0")
        from ovos_workshop.skills.fallback import FallbackSkill
        return FallbackSkill(*args, **kwargs)
