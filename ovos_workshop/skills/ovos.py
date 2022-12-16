import re
import time

from ovos_utils.intents import IntentBuilder, Intent
from ovos_utils.log import LOG
from ovos_utils.messagebus import Message, dig_for_message
from ovos_utils.skills import get_non_properties
from ovos_utils.skills.audioservice import AudioServiceInterface
from ovos_utils.skills.settings import PrivateSettings
from ovos_utils.sound import play_audio

from ovos_workshop.decorators.killable import killable_event, \
    AbortQuestion
from ovos_workshop.skills.layers import IntentLayers
from ovos_workshop.skills.mycroft_skill import MycroftSkill


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
        self.audio_service = None

    def bind(self, bus):
        super().bind(bus)
        if bus:
            # here to ensure self.skill_id is populated
            self.private_settings = PrivateSettings(self.skill_id)
            self.intent_layers.bind(self)
            self.audio_service = AudioServiceInterface(self.bus)

    # new public api, these are not available in MycroftSkill
    @property
    def is_fully_initialized(self):
        """Determines if the skill has been fully loaded and setup.
        When True all data has been loaded and all internal state and events setup"""
        return self._is_fully_initialized

    @property
    def stop_is_implemented(self):
        return self._stop_is_implemented

    @property
    def converse_is_implemented(self):
        return self._converse_is_implemented

    def activate(self):
        """Bump skill to active_skill list in intent_service.
        This enables converse method to be called even without skill being
        used in last 5 minutes.
        """
        self._activate()

    def deactivate(self):
        """remove skill from active_skill list in intent_service.
        This stops converse method from being called
        """
        self._deactivate()

    def play_audio(self, filename):
        try:
            from mycroft.version import OVOS_VERSION_BUILD, OVOS_VERSION_MINOR, OVOS_VERSION_MAJOR
            if OVOS_VERSION_MAJOR >= 1 or \
                    OVOS_VERSION_MINOR > 0 or \
                    OVOS_VERSION_BUILD >= 4:
                self.bus.emit(Message("mycroft.audio.queue",
                                      {"filename": filename}))
                return
        except:
            pass
        LOG.warning("self.play_audio requires ovos-core >= 0.0.4a45, falling back to local skill playback")
        play_audio(filename).wait()

    @property
    def core_lang(self):
        """Get the configured default language."""
        return self._core_lang

    @property
    def secondary_langs(self):
        """Get the configured secondary languages, mycroft is not
        considered to be in these languages but i will load it's resource
        files. This provides initial support for multilingual input"""
        return self._secondary_langs

    @property
    def native_langs(self):
        """Languages natively supported by core
        ie, resource files available and explicitly supported
        """
        return self._native_langs

    @property
    def alphanumeric_skill_id(self):
        """skill id converted to only alphanumeric characters
         Non alpha-numeric characters are converted to "_"

        Returns:
            (str) String of letters
        """
        return self._alphanumeric_skill_id

    @property
    def resources(self):
        """Instantiates a ResourceFileLocator instance when needed.
        a new instance is always created to ensure self.lang
        reflects the active language and not the default core language
        """
        return self._resources

    def load_lang(self, root_directory=None, lang=None):
        """Instantiates a ResourceFileLocator instance when needed.
        a new instance is always created to ensure lang
        reflects the active language and not the default core language
        """
        return self._load_lang(root_directory, lang)

    def voc_match(self, *args, **kwargs):
        try:
            return super().voc_match(*args, **kwargs)
        except FileNotFoundError:
            return False

    def remove_voc(self, utt, voc_filename, lang=None):
        """ removes any entry in .voc file from the utterance """
        lang = lang or self.lang
        cache_key = lang + voc_filename

        if cache_key not in self.voc_match_cache:
            self.voc_match(utt, voc_filename, lang)

        if utt:
            # Check for matches against complete words
            for i in self.voc_match_cache.get(cache_key) or []:
                # Substitute only whole words matching the token
                utt = re.sub(r'\b' + i + r"\b", "", utt)

        return utt

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

            # TODO support for multiple converse handlers (?)
            if hasattr(method, 'converse'):
                self.converse = method

    def register_intent_layer(self, layer_name, intent_list):
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
    def send_stop_signal(self, stop_event=None):
        msg = dig_for_message() or Message("mycroft.stop")
        # stop event execution
        if stop_event:
            self.bus.emit(msg.forward(stop_event))

        # stop TTS
        self.bus.emit(msg.forward("mycroft.audio.speech.stop"))

        # Tell ovos-core to stop recording (not in mycroft-core)
        self.bus.emit(msg.forward('recognizer_loop:record_stop'))

        # special non-ovos handling
        try:
            from mycroft.version import OVOS_VERSION_STR
        except ImportError:
            # NOTE: mycroft does not have an event to stop recording
            # this attempts to force a stop by sending silence to end STT step
            self.bus.emit(Message('mycroft.mic.mute'))
            time.sleep(1.5)  # the silence from muting should make STT stop recording
            self.bus.emit(Message('mycroft.mic.unmute'))

        time.sleep(0.5)  # if TTS had not yet started
        self.bus.emit(msg.forward("mycroft.audio.speech.stop"))


# backwards compat alias, no functional difference
class OVOSFallbackSkill(OVOSSkill):
    def __new__(cls, *args, **kwargs):
        from ovos_workshop.skills.fallback import FallbackSkill
        return FallbackSkill(*args, **kwargs)
