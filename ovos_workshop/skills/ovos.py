import binascii
import datetime
import os
import re
import sys
import time
import traceback
from abc import ABCMeta
from copy import copy
from hashlib import md5
from inspect import signature
from itertools import chain
from os.path import join, abspath, dirname, basename, isfile
from threading import Event, RLock
from typing import Dict, Callable, List, Optional, Union

from json_database import JsonStorage
from lingua_franca.format import pronounce_number, join_list
from lingua_franca.parse import yes_or_no, extract_number
from ovos_config.config import Configuration
from ovos_config.locations import get_xdg_config_save_path

from ovos_backend_client.api import EmailApi, MetricsApi
from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message, dig_for_message
from ovos_bus_client.session import SessionManager, Session
from ovos_plugin_manager.language import OVOSLangTranslationFactory, OVOSLangDetectionFactory
from ovos_utils import camel_case_split, classproperty
from ovos_utils.dialog import get_dialog, MustacheDialogRenderer
from ovos_utils.enclosure.api import EnclosureAPI
from ovos_utils.events import EventContainer, EventSchedulerInterface
from ovos_utils.file_utils import FileWatcher
from ovos_utils.gui import GUIInterface, get_ui_directories
from ovos_utils.intents import ConverseTracker, IntentBuilder, Intent
from ovos_utils.intents.intent_service_interface import munge_regex, \
    munge_intent_parser, IntentServiceInterface
from ovos_utils.json_helper import merge_dict
from ovos_utils.log import LOG, log_deprecation, deprecated
from ovos_utils.messagebus import get_handler_name, create_wrapper, \
    get_message_lang
from ovos_utils.parse import match_one
from ovos_utils.process_utils import RuntimeRequirements
from ovos_utils.skills import get_non_properties
from ovos_utils.skills.audioservice import OCPInterface
from ovos_utils.skills.settings import PrivateSettings
from ovos_utils.sound import play_audio
from ovos_workshop.decorators.compat import backwards_compat
from ovos_workshop.decorators.killable import AbortEvent, killable_event, \
    AbortQuestion
from ovos_workshop.decorators.layers import IntentLayers
from ovos_workshop.filesystem import FileSystemAccess
from ovos_workshop.resource_files import ResourceFile, \
    CoreResources, find_resource, SkillResources
from ovos_workshop.settings import SkillSettingsManager


def is_classic_core():
    try:
        from mycroft.version import OVOS_VERSION_STR
        return False
    except:
        try:
            import mycroft
            return True
        except:
            return False


def simple_trace(stack_trace: List[str]) -> str:
    """
    Generate a simplified traceback.
    @param stack_trace: Formatted stack trace (each string ends with \n)
    @return: Stack trace with any empty lines removed and last line removed
    """
    stack_trace = stack_trace[:-1]
    tb = 'Traceback:\n'
    for line in stack_trace:
        if line.strip():
            tb += line
    return tb


class _OVOSSkillMetaclass(ABCMeta):
    """
    To override isinstance checks
    """

    def __instancecheck_classic__(self, instance):
        # instance imported from vanilla mycroft
        from mycroft.skills import MycroftSkill as _CoreSkill
        if issubclass(instance.__class__, _CoreSkill):
            return True
        return issubclass(instance.__class__, OVOSSkill)

    @backwards_compat(classic_core=__instancecheck_classic__)
    def __instancecheck__(self, instance):
        return super().__instancecheck__(instance)


class OVOSSkill(metaclass=_OVOSSkillMetaclass):
    """
    Base class for OpenVoiceOS skills providing common behaviour and parameters
    to all Skill implementations.

    skill_launcher.py used to be skill_loader-py in mycroft-core

    for launching skills one can use skill_launcher.py to run them standalone
    (eg, docker)

    KwArgs:
        name (str): skill name - DEPRECATED
        skill_id (str): unique skill identifier
        bus (MycroftWebsocketClient): Optional bus connection
    """

    def __init__(self, name: Optional[str] = None,
                 bus: Optional[MessageBusClient] = None,
                 resources_dir: Optional[str] = None,
                 settings: Optional[JsonStorage] = None,
                 gui: Optional[GUIInterface] = None,
                 enable_settings_manager: bool = True,
                 skill_id: str = ""):
        """
        Create an OVOSSkill object.
        @param name: DEPRECATED skill_name
        @param bus: MessageBusClient to bind to skill
        @param resources_dir: optional root resource directory (else defaults to
            skill `root_dir`
        @param settings: Optional settings object, else defined in skill config
            path
        @param gui: Optional SkillGUI, else one is initialized
        @param enable_settings_manager: if True, enables a SettingsManager for
            this skill to manage default settings and backend sync
        @param skill_id: Unique ID for this skill
        """

        self.log = LOG  # a dedicated namespace will be assigned in _startup
        self._enable_settings_manager = enable_settings_manager
        self._init_event = Event()
        self.name = name or self.__class__.__name__
        self.resting_name = None
        self.skill_id = skill_id  # set by SkillLoader, guaranteed unique
        self._settings_meta = None  # DEPRECATED - backwards compat only
        self.settings_manager = None
        self.private_settings = None

        # Get directory of skill source (__init__.py)
        self.root_dir = dirname(abspath(sys.modules[self.__module__].__file__))
        self.res_dir = resources_dir or self.root_dir

        self.gui = gui
        self._bus = bus
        self._enclosure = EnclosureAPI()

        # optional lang translation, lazy inited on first access
        self._lang_detector = None
        self._translator = None  # can be passed to solvers plugins

        # Core configuration
        self.config_core: Configuration = Configuration()

        self._settings = None
        self._initial_settings = settings or dict()
        self._settings_watchdog = None
        self._settings_lock = RLock()

        # Override to register a callback method that will be called every time
        # the skill's settings are updated. The referenced method should
        # include any logic needed to handle the updated settings.
        self.settings_change_callback = None

        # fully initialized when self.skill_id is set
        self._file_system = None

        self.reload_skill = True  # allow reloading (default True)

        self.events = EventContainer(bus)

        # Cached voc file contents
        self._voc_cache = {}

        # loaded lang file resources
        self._lang_resources = {}

        # Delegator classes
        self.event_scheduler = EventSchedulerInterface()
        self.intent_service = IntentServiceInterface()
        self.audio_service = None
        self.intent_layers = IntentLayers()

        # Skill Public API
        self.public_api: Dict[str, dict] = {}

        self._original_converse = self.converse  # for get_response

        self.__responses = {}
        self.__validated_responses = {}
        self._threads = []  # for killable events decorator

        # yay, following python best practices again!
        if self.skill_id and bus:
            self._startup(bus, self.skill_id)

    # skill developer abstract methods
    # devs are meant to override these
    def initialize(self):
        """
        Legacy method overridden by skills to perform extra init after __init__.
        Skills should now move any code in this method to `__init__`, after a
        call to `super().__init__`.
        """
        pass

    def get_intro_message(self) -> str:
        """
        Override to return a string to speak on first run. i.e. for post-install
        setup instructions.
        """
        return ""

    def handle_activate(self, message: Message):
        """
        Called when this skill is considered active by the intent service;
        converse method will be called with every utterance.
        Override this method to do any optional preparation.
        @param message: `{self.skill_id}.activate` Message
        """

    def handle_deactivate(self, message: Message):
        """
        Called when this skill is no longer considered active by the intent
        service; converse method will not be called until skill is active again.
        Override this method to do any optional cleanup.
        @param message: `{self.skill_id}.deactivate` Message
        """

    def converse(self, message: Optional[Message] = None) -> bool:
        """
        Override to handle an utterance before intent parsing while this skill
        is active. Active skills are called in order of most recently used to
        least recently used until one handles the converse request. If no skill
        handles an utterance in `converse`, then the utterance will continue to
        normal intent parsing.
        @param message: Message containing user utterances to optionally handle
        @return: True if the utterance was handled, else False
        """
        return False

    def stop(self):
        """
        Optional method implemented by subclass. Called when system or user
        requests `stop` to cancel current execution.
        """
        pass

    def shutdown(self):
        """
        Optional shutdown procedure implemented by subclass.

        This method is intended to be called during the skill process
        termination. The skill implementation must shut down all processes and
        operations in execution.
        """
        pass

    # skill class properties
    @classproperty
    def runtime_requirements(self) -> RuntimeRequirements:
        """
        Override to specify what a skill expects to be available at init and at
        runtime. Default will assume network and internet are required and GUI
        is not required for backwards-compat.

        some examples:

        IOT skill that controls skills via LAN could return:
        scans_on_init = True
        RuntimeRequirements(internet_before_load=False,
                            network_before_load=scans_on_init,
                            requires_internet=False,
                            requires_network=True,
                            no_internet_fallback=True,
                            no_network_fallback=False)

        online search skill with a local cache:
        has_cache = False
        RuntimeRequirements(internet_before_load=not has_cache,
                            network_before_load=not has_cache,
                            requires_internet=True,
                            requires_network=True,
                            no_internet_fallback=True,
                            no_network_fallback=True)

        a fully offline skill:
        RuntimeRequirements(internet_before_load=False,
                            network_before_load=False,
                            requires_internet=False,
                            requires_network=False,
                            no_internet_fallback=True,
                            no_network_fallback=True)
        """
        return RuntimeRequirements()

    @property
    def is_fully_initialized(self) -> bool:
        """
        Determines if the skill has been fully loaded and setup.
        When True, all data has been loaded and all internal state
        and events set up.
        """
        return self._init_event.is_set()

    @property
    def stop_is_implemented(self) -> bool:
        """
        True if this skill implements a `stop` method
        """
        return self.__class__.stop is not OVOSSkill.stop

    @property
    def converse_is_implemented(self) -> bool:
        """
        True if this skill implements a `converse` method
        """
        return self.__class__.converse is not OVOSSkill.converse or \
            self._original_converse != self.converse

    # safe skill_id/bus wrapper properties
    @property
    def alphanumeric_skill_id(self) -> str:
        """
        Skill id converted to only alphanumeric characters and "_".
        Non alphanumeric characters are converted to "_"
        """
        return ''.join(c if c.isalnum() else '_'
                       for c in str(self.skill_id))

    @property
    def lang_detector(self):
        """ language detector, lazy init on first access"""
        if not self._lang_detector:
            # if it's being used, there is no recovery, do not try: except:
            self._lang_detector = OVOSLangDetectionFactory.create(self.config_core)
        return self._lang_detector

    @lang_detector.setter
    def lang_detector(self, val):
        self._lang_detector = val

    @property
    def translator(self):
        """ language translator, lazy init on first access"""
        if not self._translator:
            # if it's being used, there is no recovery, do not try: except:
            self._translator = OVOSLangTranslationFactory.create(self.config_core)
        return self._translator

    @translator.setter
    def translator(self, val):
        self._translator = val

    @property
    def settings_path(self) -> str:
        """
        Absolute file path of this skill's `settings.json` (file may not exist)
        """
        return join(get_xdg_config_save_path(), 'skills', self.skill_id,
                    'settings.json')

    @property
    def settings(self) -> JsonStorage:
        """
        Get settings specific to this skill
        """
        if self._settings is not None:
            return self._settings
        else:
            self.log.warning('Skill not fully initialized. Only default values '
                             'can be set, no settings can be read or changed.'
                             f"to correct this add kwargs "
                             f"__init__(bus=None, skill_id='') "
                             f"to skill class {self.__class__.__name__}")
            self.log.error(simple_trace(traceback.format_stack()))
            return self._initial_settings

    @settings.setter
    def settings(self, val: dict):
        """
        Update settings specific to this skill
        """
        assert isinstance(val, dict)
        # init method
        if self._settings is None:
            self._initial_settings = val
            return
        with self._settings_lock:
            # ensure self._settings remains a JsonDatabase
            self._settings.clear()  # clear data
            self._settings.merge(val, skip_empty=False)  # merge new data

    @property
    def enclosure(self) -> EnclosureAPI:
        """
        Get an EnclosureAPI object to interact with hardware
        """
        if self._enclosure:
            return self._enclosure
        else:
            self.log.warning('Skill not fully initialized.'
                             f"to correct this add kwargs "
                             f"__init__(bus=None, skill_id='') "
                             f"to skill class {self.__class__.__name__}")
            self.log.error(simple_trace(traceback.format_stack()))
            raise Exception('Accessed MycroftSkill.enclosure in __init__')

    @property
    def file_system(self) -> FileSystemAccess:
        """
        Get an object that provides managed access to a local Filesystem.
        """
        if not self._file_system and self.skill_id:
            self._file_system = FileSystemAccess(join('skills', self.skill_id))
        if self._file_system:
            return self._file_system
        else:
            self.log.warning('Skill not fully initialized.'
                             f"to correct this add kwargs __init__(bus=None, skill_id='') "
                             f"to skill class {self.__class__.__name__}")
            self.log.error(simple_trace(traceback.format_stack()))
            raise Exception('Accessed MycroftSkill.file_system in __init__')

    @file_system.setter
    def file_system(self, fs: FileSystemAccess):
        """
        Provided mainly for backwards compatibility with derivative
        MycroftSkill classes. Skills are advised against redefining the file
        system directory.
        @param fs: new FileSystemAccess object to use
        """
        self.log.warning(f"Skill manually overriding file_system path to: "
                         f"{fs.path}")
        self._file_system = fs

    @property
    def bus(self) -> MessageBusClient:
        """
        Get the MessageBusClient bound to this skill
        """
        if self._bus:
            return self._bus
        else:
            self.log.warning('Skill not fully initialized.'
                             f"to correct this add kwargs "
                             f"__init__(bus=None, skill_id='') "
                             f"to skill class {self.__class__.__name__}")
            self.log.error(simple_trace(traceback.format_stack()))
            raise Exception('Accessed MycroftSkill.bus in __init__')

    @bus.setter
    def bus(self, value: MessageBusClient):
        """
        Set the MessageBusClient bound to this skill. Note that setting this
        after init may have unintended consequences as expected events might
        not be registered. Call `bind` to connect a new MessageBusClient.
        @param value: new MessageBusClient object
        """
        from ovos_bus_client import MessageBusClient
        from ovos_utils.messagebus import FakeBus
        if isinstance(value, (MessageBusClient, FakeBus)):
            self._bus = value
        else:
            raise TypeError(f"Expected a MessageBusClient, got: {type(value)}")

    # magic properties -> depend on message.context / Session
    @property
    def dialog_renderer(self) -> Optional[MustacheDialogRenderer]:
        """
        Get a dialog renderer for this skill. Language will be determined by
        message history to match the language associated with the current
        session or else from Configuration.
        """
        return self.resources.dialog_renderer

    @property
    def location(self) -> dict:
        """
        Get the JSON data struction holding location information.
        """
        # TODO: Allow Enclosure to override this for devices that
        #       contain a GPS.
        return self.config_core.get('location')

    @property
    def location_pretty(self) -> Optional[str]:
        """
        Get a speakable city from the location config if available
        """
        loc = self.location
        if type(loc) is dict and loc['city']:
            return loc['city']['name']
        return None

    @property
    def location_timezone(self) -> Optional[str]:
        """
        Get the timezone code, such as 'America/Los_Angeles'
        """
        loc = self.location
        if type(loc) is dict and loc['timezone']:
            return loc['timezone']['code']
        return None

    @property
    def lang(self) -> str:
        """
        Get the current language as a BCP-47 language code. This will consider
        current session data if available, else Configuration.
        """
        lang = self.core_lang
        message = dig_for_message()
        if message:
            lang = get_message_lang(message)
        return lang.lower()

    @property
    def core_lang(self) -> str:
        """
        Get the configured default language as a BCP-47 language code.
        """
        return self.config_core.get("lang", "en-us").lower()

    @property
    def secondary_langs(self) -> List[str]:
        """
        Get the configured secondary languages; resources will be loaded for
        these languages to provide support for multilingual input, in addition
        to `core_lang`. A skill may override this method to specify which
        languages intents are registered in.
        """
        return [lang.lower() for lang in self.config_core.get('secondary_langs', [])
                if lang != self.core_lang]

    @property
    def native_langs(self) -> List[str]:
        """
        Languages natively supported by this skill (ie, resource files available
        and explicitly supported). This is equivalent to normalized
        secondary_langs + core_lang.
        """
        valid = set([lang.lower() for lang in self.secondary_langs if '-' in
                     lang and lang != self.core_lang] + [self.core_lang])
        return list(valid)

    @property
    def resources(self) -> SkillResources:
        """
        Get a SkillResources object for the current language. Objects are
        initialized for the current language as needed.
        """
        return self.load_lang(self.res_dir, self.lang)

    # resource file loading
    def load_lang(self, root_directory: Optional[str] = None,
                  lang: Optional[str] = None) -> SkillResources:
        """
        Get a SkillResources object for this skill in the requested `lang` for
        resource files in the requested `root_directory`.
        @param root_directory: root path to find resources (default res_dir)
        @param lang: language to get resources for (default self.lang)
        @return: SkillResources object
        """
        lang = lang or self.lang
        root_directory = root_directory or self.res_dir
        if lang not in self._lang_resources:
            self._lang_resources[lang] = SkillResources(root_directory, lang,
                                                        skill_id=self.skill_id)
        return self._lang_resources[lang]

    def load_dialog_files(self, root_directory: Optional[str] = None):
        """
        Load dialog files for all configured languages
        @param root_directory: Directory to locate resources in
            (default self.res_dir)
        """
        root_directory = root_directory or self.res_dir
        # If "<skill>/dialog/<lang>" exists, load from there. Otherwise,
        # load dialog from "<skill>/locale/<lang>"
        for lang in self.native_langs:
            resources = self.load_lang(root_directory, lang)
            if resources.types.dialog.base_directory is None:
                self.log.debug(f'No dialog loaded for {lang}')

    def load_data_files(self, root_directory: Optional[str] = None):
        """
        Called by the skill loader to load intents, dialogs, etc.

        Args:
            root_directory (str): root folder to use when loading files.
        """
        root_directory = root_directory or self.res_dir
        self.load_dialog_files(root_directory)
        self.load_vocab_files(root_directory)
        self.load_regex_files(root_directory)

    def load_vocab_files(self, root_directory: Optional[str] = None):
        """ Load vocab files found under skill's root directory."""
        root_directory = root_directory or self.res_dir
        for lang in self.native_langs:
            resources = self.load_lang(root_directory, lang)
            if resources.types.vocabulary.base_directory is None:
                self.log.debug(f'No vocab loaded for {lang}')
            else:
                skill_vocabulary = resources.load_skill_vocabulary(
                    self.alphanumeric_skill_id
                )
                # For each found intent register the default along with any aliases
                for vocab_type in skill_vocabulary:
                    for line in skill_vocabulary[vocab_type]:
                        entity = line[0]
                        aliases = line[1:]
                        self.intent_service.register_adapt_keyword(
                            vocab_type, entity, aliases, lang)

    def load_regex_files(self, root_directory=None):
        """ Load regex files found under the skill directory."""
        root_directory = root_directory or self.res_dir
        for lang in self.native_langs:
            resources = self.load_lang(root_directory, lang)
            if resources.types.regex.base_directory is not None:
                regexes = resources.load_skill_regex(self.alphanumeric_skill_id)
                for regex in regexes:
                    self.intent_service.register_adapt_regex(regex, lang)

    def find_resource(self, res_name: str, res_dirname: Optional[str] = None,
                      lang: Optional[str] = None):
        """
        Find a resource file.

        Searches for the given filename using this scheme:
            1. Search the resource lang directory:
                <skill>/<res_dirname>/<lang>/<res_name>
            2. Search the resource directory:
                <skill>/<res_dirname>/<res_name>

            3. Search the locale lang directory or other subdirectory:
                <skill>/locale/<lang>/<res_name> or
                <skill>/locale/<lang>/.../<res_name>

        Args:
            res_name (string): The resource name to be found
            res_dirname (string, optional): A skill resource directory, such
                                            'dialog', 'vocab', 'regex' or 'ui'.
                                            Defaults to None.
            lang (string, optional): language folder to be used.
                                     Defaults to self.lang.

        Returns:
            string: The full path to the resource file or None if not found
        """
        lang = lang or self.lang
        x = find_resource(res_name, self.res_dir, res_dirname, lang)
        if x:
            return str(x)
        self.log.error(f"Skill {self.skill_id} resource '{res_name}' for lang "
                       f"'{lang}' not found in skill")

    # skill object setup
    def _handle_first_run(self):
        """
        The very first time a skill is run, speak a provided intro_message.
        """
        intro = self.get_intro_message()
        if intro:
            # supports .dialog files for easy localization
            # when .dialog does not exist, the text is spoken
            # it is backwards compatible
            self.speak_dialog(intro)

    def _check_for_first_run(self):
        """
        Determine if this is the very first time a skill is run by looking for
        `__mycroft_skill_firstrun` in skill settings.
        """
        first_run = self.settings.get("__mycroft_skill_firstrun", True)
        if first_run:
            self.log.info("First run of " + self.skill_id)
            self._handle_first_run()
            self.settings["__mycroft_skill_firstrun"] = False
            self.settings.store()

    def _startup(self, bus: MessageBusClient, skill_id: str = ""):
        """
        Startup the skill. Connects the skill to the messagebus, loads resources
        and finally calls the skill's "intialize" method.
        @param bus: MessageBusClient to bind to skill
        @param skill_id: Unique skill identifier, defaults to skill path for
            legacy skills and python entrypoints for modern skills
        """
        if self.is_fully_initialized:
            self.log.warning(f"Tried to initialize {self.skill_id} multiple "
                             f"times, ignoring")
            return

        # NOTE: this method is called by SkillLoader
        # it is private to make it clear to skill devs they should not touch it
        try:
            # set the skill_id
            self.skill_id = skill_id or basename(self.root_dir)
            self.intent_service.set_id(self.skill_id)
            self.event_scheduler.set_id(self.skill_id)
            self.enclosure.set_id(self.skill_id)

            # initialize anything that depends on skill_id
            self.log = LOG.create_logger(self.skill_id)
            self._init_settings()

            # initialize anything that depends on the messagebus
            self.bind(bus)
            if not self.gui:
                self._init_skill_gui()
            if self._enable_settings_manager:
                self._init_settings_manager()
            self.load_data_files()
            self._register_decorated()
            self.register_resting_screen()

            # run skill developer initialization code
            self.initialize()
            self._check_for_first_run()
            self._init_event.set()
        except Exception as e:
            self.log.exception('Skill initialization failed')
            # If an exception occurs, attempt to clean up the skill
            try:
                self.default_shutdown()
            except Exception as e2:
                LOG.debug(e2)
            raise e

    def _init_settings(self):
        """
        Set up skill settings. Defines settings in the specified file path,
        handles any settings passed to skill init, and starts watching the
        settings file for changes.
        """
        self.log.debug(f"initializing skill settings for {self.skill_id}")

        # NOTE: lock is disabled due to usage of deepcopy and to allow json
        # serialization
        self._settings = JsonStorage(self.settings_path, disable_lock=True)
        with self._settings_lock:
            if self._initial_settings and not self.is_fully_initialized:
                self.log.warning("Copying default settings values defined in "
                                 "__init__ \nto correct this add kwargs "
                                 "__init__(bus=None, skill_id='') "
                                 f"to skill class {self.__class__.__name__}")
                for k, v in self._initial_settings.items():
                    if k not in self._settings:
                        self._settings[k] = v
            self._initial_settings = copy(self.settings)

        self._start_filewatcher()

    def _init_skill_gui(self):
        """
        Set up the SkillGUI for this skill and connect relevant bus events.
        """
        self.gui = SkillGUI(self)
        self.gui.setup_default_handlers()

    def _init_settings_manager(self):
        """
        Set up the SkillSettingsManager for this skill.
        """
        self.settings_manager = SkillSettingsManager(self)

    def register_resting_screen(self):
        """
        Registers resting screen from the resting_screen_handler decorator.

        This only allows one screen and if two is registered only one
        will be used.
        """
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'resting_handler'):
                self.resting_name = method.resting_handler
                self.log.info(f'Registering resting screen {method} for {self.resting_name}.')

                # Register for handling resting screen
                self.add_event(f'{self.skill_id}.idle', method, speak_errors=False)
                # Register handler for resting screen collect message
                self.add_event('mycroft.mark2.collect_idle',
                               self._handle_collect_resting, speak_errors=False)

                # Do a send at load to make sure the skill is registered
                # if reloaded
                self._handle_collect_resting()
                break

    def _start_filewatcher(self):
        """
        Start watching settings for file changes if settings file exists and
        there isn't already a FileWatcher watching it
        """
        if self._settings_watchdog is None and isfile(self._settings.path):
            self._settings_watchdog = \
                FileWatcher([self._settings.path],
                            callback=self._handle_settings_file_change,
                            ignore_creation=True)

    def _register_decorated(self):
        """
        Register all intent handlers that are decorated with an intent.

        Looks for all functions that have been marked by a decorator
        and read the intent data from them.  The intent handlers aren't the
        only decorators used.  Skip properties as calling getattr on them
        executes the code which may have unintended side effects
        """
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'intents'):
                for intent in getattr(method, 'intents'):
                    self.register_intent(intent, method)

            if hasattr(method, 'intent_files'):
                for intent_file in getattr(method, 'intent_files'):
                    self.register_intent_file(intent_file, method)

            if hasattr(method, 'intent_layers'):
                for layer_name, intent_files in \
                        getattr(method, 'intent_layers').items():
                    self.register_intent_layer(layer_name, intent_files)

            # TODO support for multiple converse handlers (?)
            if hasattr(method, 'converse'):
                self.converse = method

    def _upload_settings(self):
        """
        Upload settings to a remote backend if configured.
        """
        if self.settings_manager and self.config_core.get("skills",
                                                          {}).get("sync2way"):
            # upload new settings to backend
            generate = self.config_core.get("skills", {}).get("autogen_meta",
                                                              True)
            # this will check global sync flag
            self.settings_manager.upload(generate)
            if generate:
                # update settingsmeta file on disk
                self.settings_manager.save_meta()

    def __bind_classic(self, bus):
        self._bus = bus
        self.events.set_bus(bus)
        self.intent_service.set_bus(bus)
        self.event_scheduler.set_bus(bus)
        self._enclosure.set_bus(bus)
        self._register_system_event_handlers()
        self._register_public_api()
        self.intent_layers.bind(self)
        self.audio_service = OCPInterface(self.bus)
        self.private_settings = PrivateSettings(self.skill_id)

        log_deprecation("Support for mycroft-core is deprecated", "0.1.0")
        # inject ovos exclusive features in vanilla mycroft-core
        # if possible
        # limited support for missing skill deactivated event
        # TODO - update ConverseTracker
        ConverseTracker.connect_bus(self.bus)  # pull/1468
        self.add_event("converse.skill.deactivated",
                       self._handle_skill_deactivated,
                       speak_errors=False)

    @backwards_compat(classic_core=__bind_classic)
    def bind(self, bus: MessageBusClient):
        """
        Register MessageBusClient with skill.
        @param bus: MessageBusClient to bind to skill and internal objects
        """
        if bus:
            self._bus = bus
            self.events.set_bus(bus)
            self.intent_service.set_bus(bus)
            self.event_scheduler.set_bus(bus)
            self._enclosure.set_bus(bus)
            self._register_system_event_handlers()
            self._register_public_api()
            self.intent_layers.bind(self)
            self.audio_service = OCPInterface(self.bus)
            self.private_settings = PrivateSettings(self.skill_id)

    def _register_public_api(self):
        """
        Find and register API methods decorated with `@api_method` and create a
        messagebus handler for fetching the api info if any handlers exist.
        """

        def wrap_method(fn):
            """Boilerplate for returning the response to the sender."""

            def wrapper(message):
                result = fn(*message.data['args'], **message.data['kwargs'])
                message.context["skill_id"] = self.skill_id
                self.bus.emit(message.response(data={'result': result}))

            return wrapper

        methods = [attr_name for attr_name in get_non_properties(self)
                   if hasattr(getattr(self, attr_name), '__name__')]

        for attr_name in methods:
            method = getattr(self, attr_name)

            if hasattr(method, 'api_method'):
                doc = method.__doc__ or ''
                name = method.__name__
                self.public_api[name] = {
                    'help': doc,
                    'type': f'{self.skill_id}.{name}',
                    'func': method
                }
        for key in self.public_api:
            if ('type' in self.public_api[key] and
                    'func' in self.public_api[key]):
                self.log.debug(f"Adding api method: "
                               f"{self.public_api[key]['type']}")

                # remove the function member since it shouldn't be
                # reused and can't be sent over the messagebus
                func = self.public_api[key].pop('func')
                self.add_event(self.public_api[key]['type'],
                               wrap_method(func), speak_errors=False)

        if self.public_api:
            self.add_event(f'{self.skill_id}.public_api',
                           self._send_public_api, speak_errors=False)

    def _register_system_event_handlers(self):
        """
        Register default messagebus event handlers
        """
        # Only register stop if it's been implemented
        if self.stop_is_implemented:
            self.add_event('mycroft.stop', self.__handle_stop,
                           speak_errors=False)
        # TODO: deprectate 0.0.9
        self.add_event("skill.converse.ping", self._handle_converse_ack,
                       speak_errors=False)
        self.add_event(f"{self.skill_id}.converse.ping", self._handle_converse_ack,
                       speak_errors=False)
        # TODO: deprecate 0.0.9
        self.add_event("skill.converse.request", self._handle_converse_request,
                       speak_errors=False)
        self.add_event(f"{self.skill_id}.converse.request", self._handle_converse_request,
                       speak_errors=False)
        self.add_event(f"{self.skill_id}.activate", self.handle_activate,
                       speak_errors=False)
        self.add_event(f"{self.skill_id}.deactivate", self.handle_deactivate,
                       speak_errors=False)
        self.add_event("intent.service.skills.deactivated",
                       self._handle_skill_deactivated, speak_errors=False)
        self.add_event("intent.service.skills.activated",
                       self._handle_skill_activated, speak_errors=False)
        self.add_event('mycroft.skill.enable_intent', self.handle_enable_intent,
                       speak_errors=False)
        self.add_event('mycroft.skill.disable_intent',
                       self.handle_disable_intent, speak_errors=False)
        self.add_event('mycroft.skill.set_cross_context',
                       self.handle_set_cross_context, speak_errors=False)
        self.add_event('mycroft.skill.remove_cross_context',
                       self.handle_remove_cross_context, speak_errors=False)
        self.add_event('mycroft.skills.settings.changed',
                       self.handle_settings_change, speak_errors=False)

        # TODO: deprecate 0.0.9
        self.add_event("skill.converse.get_response", self.__handle_get_response, speak_errors=False)
        self.add_event(f"{self.skill_id}.converse.get_response", self.__handle_get_response, speak_errors=False)

    def _send_public_api(self, message: Message):
        """
        Respond with the skill's public api.
        @param message: `{self.skill_id}.public_api` Message
        """
        message.context["skill_id"] = self.skill_id
        self.bus.emit(message.response(data=self.public_api))

    # skill internal events amd lifecycle
    def _handle_settings_file_change(self, path: str):
        """
        Handle a FileWatcher notification that a file was changed. Reload
        settings, call `self.settings_change_callback` if defined, and upload
        changes if a backend is configured.
        @param path: Modified file path
        """
        if path != self._settings.path:
            LOG.debug(f"Ignoring non-settings change")
            return
        if self._settings:
            with self._settings_lock:
                self._settings.reload()
        if self.settings_change_callback:
            try:
                self.settings_change_callback()
            except Exception as e:
                self.log.exception("settings change callback failed, "
                                   f"file changes not handled!: {e}")
        self._upload_settings()

    def handle_settings_change(self, message: Message):
        """
        Update settings if a remote settings changes apply to this skill.

        The skill settings downloader uses a single API call to retrieve the
        settings for all skills to limit the number API calls.
        A "mycroft.skills.settings.changed" event is emitted for each skill
        with settings changes. Only update this skill's settings if its remote
        settings were among those changed.
        """
        remote_settings = message.data.get(self.skill_id)
        if remote_settings is not None:
            self.log.info('Updating settings for skill ' + self.skill_id)
            self.settings.update(**remote_settings)
            self.settings.store()
            if self.settings_change_callback is not None:
                try:
                    self.settings_change_callback()
                except Exception as e:
                    self.log.exception("settings change callback failed, "
                                       f"remote changes not handled!: {e}")
            self._start_filewatcher()

    def _handle_skill_activated(self, message: Message):
        """
        Intent service activated a skill. If it was this skill,
        emit a skill activation message.
        @param message: `intent.service.skills.activated` Message
        """
        if message.data.get("skill_id") == self.skill_id:
            self.bus.emit(message.forward(f"{self.skill_id}.activate"))

    def _handle_skill_deactivated(self, message):
        """
        Intent service deactivated a skill. If it was this skill,
        emit a skill deactivation message.
        @param message: `intent.service.skills.deactivated` Message
        """
        if message.data.get("skill_id") == self.skill_id:
            self.bus.emit(message.forward(f"{self.skill_id}.deactivate"))

    def _handle_converse_ack(self, message: Message):
        """
        Inform skills service if we want to handle converse. Individual skills
        may override the property self.converse_is_implemented to enable or
        disable converse support. Note that this does not affect a skill's
        `active` status.
        @param message: `{self.skill_id}.converse.ping` Message
        """
        if message.msg_type == "skill.converse.ping":
            log_deprecation(
                "Support for message type `skill.converse.ping` is deprecated, use `{skill_id}.converse.ping`", "0.0.9")
            if message.data.get("skill_id") != self.skill_id:
                return  # not for us!

        self.bus.emit(message.reply(
            "skill.converse.pong",
            data={"skill_id": self.skill_id,
                  "can_handle": self.converse_is_implemented},
            context={"skill_id": self.skill_id}))

    def _handle_converse_request(self, message: Message):
        """
        If this skill is requested and supports converse, handle the user input
        with `converse`.
        @param message: `{self.skill_id}.converse.request` Message
        """
        if message.msg_type == "skill.converse.request":
            log_deprecation(
                "Support for message type `skill.converse.request` is deprecated, use `{skill_id}.converse.request`",
                "0.0.9")
            if message.data.get("skill_id") != self.skill_id:
                return  # not for us!

        try:
            # converse can have multiple signatures
            params = signature(self.converse).parameters
            kwargs = {"message": message,
                      "utterances": message.data['utterances'],
                      "lang": message.data['lang']}
            kwargs = {k: v for k, v in kwargs.items() if k in params}
            result = self.converse(**kwargs)
            self.bus.emit(message.reply('skill.converse.response',
                                        {"skill_id": self.skill_id,
                                         "result": result}))
        except Exception as e:
            LOG.error(e)
            self.bus.emit(message.reply('skill.converse.response',
                                        {"skill_id": self.skill_id,
                                         "result": False}))

    def _handle_collect_resting(self, message: Optional[Message] = None):
        """
        Handler for collect resting screen messages.

        Sends info on how to trigger this skill's resting page.
        """
        self.log.info('Registering resting screen')
        msg = message or Message("")
        message = msg.reply(
            'mycroft.mark2.register_idle',
            data={'name': self.resting_name, 'id': self.skill_id},
            context={"skill_id": self.skill_id}
        )
        self.bus.emit(message)

    def __handle_stop(self, message):
        """Handler for the "mycroft.stop" signal. Runs the user defined
        `stop()` method.
        """
        message.context['skill_id'] = self.skill_id
        self.bus.emit(message.forward(self.skill_id + ".stop"))
        try:
            if self.stop():
                self.bus.emit(message.reply("mycroft.stop.handled",
                                            {"by": "skill:" + self.skill_id},
                                            {"skill_id": self.skill_id}))
        except Exception as e:
            self.log.exception(f'Failed to stop skill: {self.skill_id}: {e}')

    def default_shutdown(self):
        """
        Parent function called internally to shut down everything.
        1) Call skill.stop() to allow skill to clean up any active processes
        2) Store skill settings and remove file watchers
        3) Shutdown skill GUI to clear any active pages
        4) Shutdown the event_scheduler and remove any pending events
        5) Call skill.shutdown() to allow skill to do any other shutdown tasks
        6) Emit `detach_skill` Message to notify skill is shut down
        """

        try:
            # Allow skill to handle `stop` actions before shutting things down
            self.stop()
        except Exception as e:
            self.log.error(f'Failed to stop skill: {self.skill_id}: {e}',
                           exc_info=True)

        try:
            self.settings_change_callback = None

            # Store settings
            if self.settings != self._initial_settings:
                self.settings.store()
            if self._settings_meta:
                self._settings_meta.stop()
            if self._settings_watchdog:
                self._settings_watchdog.shutdown()
        except Exception as e:
            self.log.error(f"Failed to store settings for {self.skill_id}: {e}")

        try:
            # Clear skill from gui
            if self.gui:
                self.gui.shutdown()
        except Exception as e:
            self.log.error(f"Failed to shutdown gui for {self.skill_id}: {e}")

        try:
            # removing events
            if self.event_scheduler:
                self.event_scheduler.shutdown()
                self.events.clear()
        except Exception as e:
            self.log.error(f"Failed to remove events for {self.skill_id}: {e}")

        try:
            self.shutdown()
        except Exception as e:
            self.log.error(f'Skill specific shutdown function encountered an '
                           f'error: {e}')

        self.bus.emit(
            Message('detach_skill', {'skill_id': f"{self.skill_id}:"},
                    {"skill_id": self.skill_id}))

    def detach(self):
        """
        Detach all intents for this skill from the intent_service.
        """
        for (name, _) in self.intent_service:
            name = f'{self.skill_id}:{name}'
            self.intent_service.detach_intent(name)

    # intents / resource files management
    def register_intent_layer(self, layer_name: str,
                              intent_list: List[Union[IntentBuilder, Intent, str]]):
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

    def register_intent(self, intent_parser: Union[IntentBuilder, Intent, str],
                        handler: callable):
        """
        Register an Intent with the intent service.

        Args:
            intent_parser: Intent, IntentBuilder object or padatious intent
                           file to parse utterance for the handler.
            handler (func): function to register with intent
        """
        if isinstance(intent_parser, IntentBuilder):
            intent_parser = intent_parser.build()
        if (isinstance(intent_parser, str) and
                intent_parser.endswith('.intent')):
            return self.register_intent_file(intent_parser, handler)
        elif not isinstance(intent_parser, Intent):
            raise ValueError('"' + str(intent_parser) + '" is not an Intent')

        return self._register_adapt_intent(intent_parser, handler)

    def register_intent_file(self, intent_file: str, handler: callable):
        """Register an Intent file with the intent service.

        For example:
            food.order.intent:
                Order some {food}.
                Order some {food} from {place}.
                I'm hungry.
                Grab some {food} from {place}.

        Optionally, you can also use <register_entity_file>
        to specify some examples of {food} and {place}

        In addition, instead of writing out multiple variations
        of the same sentence you can write:
            food.order.intent:
                (Order | Grab) some {food} (from {place} | ).
                I'm hungry.

        Args:
            intent_file: name of file that contains example queries
                         that should activate the intent.  Must end with
                         '.intent'
            handler:     function to register with intent
        """
        for lang in self.native_langs:
            name = f'{self.skill_id}:{intent_file}'
            resources = self.load_lang(self.res_dir, lang)
            resource_file = ResourceFile(resources.types.intent, intent_file)
            if resource_file.file_path is None:
                self.log.error(f'Unable to find "{intent_file}"')
                continue
            filename = str(resource_file.file_path)
            self.intent_service.register_padatious_intent(name, filename, lang)
            if handler:
                self.add_event(name, handler, 'mycroft.skill.handler')

    def register_entity_file(self, entity_file: str):
        """
        Register an Entity file with the intent service.

        An Entity file lists the exact values that an entity can hold.
        For example:
            ask.day.intent:
                Is it {weekend}?
            weekend.entity:
                Saturday
                Sunday

        Args:
            entity_file (string): name of file that contains examples of an
                                  entity.
        """
        if entity_file.endswith('.entity'):
            entity_file = entity_file.replace('.entity', '')
        for lang in self.native_langs:
            resources = self.load_lang(self.res_dir, lang)
            entity = ResourceFile(resources.types.entity, entity_file)
            if entity.file_path is None:
                self.log.error(f'Unable to find "{entity_file}"')
                continue
            filename = str(entity.file_path)
            name = f"{self.skill_id}:{basename(entity_file)}_" \
                   f"{md5(entity_file.encode('utf-8')).hexdigest()}"
            self.intent_service.register_padatious_entity(name, filename, lang)

    def register_vocabulary(self, entity: str, entity_type: str,
                            lang: Optional[str] = None):
        """
        Register a word to a keyword
        @param entity: word to register
        @param entity_type: Intent handler entity name to associate entity to
        @param lang: language of `entity` (default self.lang)
        """
        keyword_type = self.alphanumeric_skill_id + entity_type
        lang = lang or self.lang
        self.intent_service.register_adapt_keyword(keyword_type, entity,
                                                   lang=lang)

    def register_regex(self, regex_str: str, lang: Optional[str] = None):
        """
        Register a new regex.
        @param regex_str: Regex string to add
        @param lang: language of regex_str (default self.lang)
        """
        self.log.debug('registering regex string: ' + regex_str)
        regex = munge_regex(regex_str, self.skill_id)
        re.compile(regex)  # validate regex
        self.intent_service.register_adapt_regex(regex, lang=lang or self.lang)

    # event/intent registering internal handlers
    def handle_enable_intent(self, message: Message):
        """
        Listener to enable a registered intent if it belongs to this skill.
        @param message: `mycroft.skill.enable_intent` Message
        """
        intent_name = message.data['intent_name']
        for (name, _) in self.intent_service.detached_intents:
            if name == intent_name:
                return self.enable_intent(intent_name)

    def handle_disable_intent(self, message: Message):
        """
        Listener to disable a registered intent if it belongs to this skill.
        @param message: `mycroft.skill.disable_intent` Message
        """
        intent_name = message.data['intent_name']
        for (name, _) in self.intent_service.registered_intents:
            if name == intent_name:
                return self.disable_intent(intent_name)

    def handle_set_cross_context(self, message: Message):
        """
        Add global context to the intent service.
        @param message: `mycroft.skill.set_cross_context` Message
        """
        context = message.data.get('context')
        word = message.data.get('word')
        origin = message.data.get('origin')

        self.set_context(context, word, origin)

    def handle_remove_cross_context(self, message: Message):
        """
        Remove global context from the intent service.
        @param message: `mycroft.skill.remove_cross_context` Message
        """
        context = message.data.get('context')
        self.remove_context(context)

    def _on_event_start(self, message: Message, handler_info: str,
                        skill_data: dict):
        """
        Indicate that the skill handler is starting.
        """
        if handler_info:
            # Indicate that the skill handler is starting if requested
            msg_type = handler_info + '.start'
            message.context["skill_id"] = self.skill_id
            self.bus.emit(message.forward(msg_type, skill_data))

    def _on_event_end(self, message: Message, handler_info: str,
                      skill_data: dict):
        """
        Store settings (if changed) and indicate that the skill handler has
        completed.
        """
        if self.settings != self._initial_settings:
            self.settings.store()
            self._initial_settings = copy(self.settings)
        if handler_info:
            msg_type = handler_info + '.complete'
            message.context["skill_id"] = self.skill_id
            self.bus.emit(message.forward(msg_type, skill_data))

    def _on_event_error(self, error: str, message: Message, handler_info: str,
                        skill_data: dict, speak_errors: bool):
        """Speak and log the error."""
        # Convert "MyFancySkill" to "My Fancy Skill" for speaking
        handler_name = camel_case_split(self.name)
        msg_data = {'skill': handler_name}
        speech = get_dialog('skill.error', self.lang, msg_data)
        if speak_errors:
            self.speak(speech)
        self.log.exception(error)
        # append exception information in message
        skill_data['exception'] = repr(error)
        if handler_info:
            # Indicate that the skill handler errored
            msg_type = handler_info + '.error'
            message = message or Message("")
            message.context["skill_id"] = self.skill_id
            self.bus.emit(message.forward(msg_type, skill_data))

    def _register_adapt_intent(self,
                               intent_parser: Union[IntentBuilder, Intent, str],
                               handler: callable):
        """
        Register an adapt intent.

        Args:
            intent_parser: Intent object to parse utterance for the handler.
            handler (func): function to register with intent
        """
        # Default to the handler's function name if none given
        is_anonymous = not intent_parser.name
        name = intent_parser.name or handler.__name__
        if is_anonymous:
            # Find a good name
            original_name = name
            nbr = 0
            while name in self.intent_service.intent_names:
                nbr += 1
                name = f'{original_name}{nbr}'
        elif name in self.intent_service.intent_names and \
                not self.intent_service.intent_is_detached(name):
            raise ValueError(f'The intent name {name} is already taken')

        munge_intent_parser(intent_parser, name, self.skill_id)
        self.intent_service.register_adapt_intent(name, intent_parser)
        if handler:
            self.add_event(intent_parser.name, handler,
                           'mycroft.skill.handler')

    # skill developer facing utils
    def speak(self, utterance: str, expect_response: bool = False,
              wait: bool = False, meta: Optional[dict] = None):
        """Speak a sentence.

        Args:
            utterance (str):        sentence mycroft should speak
            expect_response (bool): set to True if Mycroft should listen
                                    for a response immediately after
                                    speaking the utterance.
            wait (bool):            set to True to block while the text
                                    is being spoken.
            meta:                   Information of what built the sentence.
        """
        # registers the skill as being active
        meta = meta or {}
        meta['skill'] = self.skill_id
        self.enclosure.register(self.skill_id)
        data = {'utterance': utterance,
                'expect_response': expect_response,
                'meta': meta,
                'lang': self.lang}

        # grab message that triggered speech so we can keep context
        message = dig_for_message()
        m = message.forward("speak", data) if message \
            else Message("speak", data)
        m.context["skill_id"] = self.skill_id

        # update any auto-translation metadata in message.context
        if "translation_data" in meta:
            tx_data = merge_dict(m.context.get("translation_data", {}),
                                 meta["translation_data"])
            m.context["translation_data"] = tx_data

        self.bus.emit(m)

        if wait:
            sessid = SessionManager.get(m).session_id
            event = Event()

            def handle_output_end(msg):
                sess = SessionManager.get(msg)
                if sessid == sess.session_id:
                    event.set()

            self.bus.on("recognizer_loop:audio_output_end", handle_output_end)
            event.wait(timeout=15)
            self.bus.remove("recognizer_loop:audio_output_end",
                            handle_output_end)

    def speak_dialog(self, key: str, data: Optional[dict] = None,
                     expect_response: bool = False, wait: bool = False):
        """
        Speak a random sentence from a dialog file.

        Args:
            key (str): dialog file key (e.g. "hello" to speak from the file
                                        "locale/en-us/hello.dialog")
            data (dict): information used to populate sentence
            expect_response (bool): set to True if Mycroft should listen
                                    for a response immediately after
                                    speaking the utterance.
            wait (bool):            set to True to block while the text
                                    is being spoken.
        """
        if self.dialog_renderer:
            data = data or {}
            self.speak(
                self.dialog_renderer.render(key, data),
                expect_response, wait, meta={'dialog': key, 'data': data}
            )
        else:
            self.log.warning(
                'dialog_render is None, does the locale/dialog folder exist?'
            )
            self.speak(key, expect_response, wait, {})

    def _play_audio_old(self, filename: str, instant: bool = False):
        """ compat for ovos-core <= 0.0.7 """
        if instant:
            LOG.warning("self.play_audio instant flag requires ovos-core >= 0.0.8, "
                        "falling back to local skill playback")
            play_audio(filename).wait()
        else:
            message = dig_for_message() or Message("")
            self.bus.emit(message.forward("mycroft.audio.queue",
                                          {"filename": filename,  # TODO - deprecate filename in ovos-audio
                                           "uri": filename  # new namespace
                                           }))

    def _play_audio_classic(self, filename: str, instant: bool = False):
        """ compat for classic mycroft-core """
        LOG.warning("self.play_audio requires ovos-core >= 0.0.4, "
                    "falling back to local skill playback")
        play_audio(filename).wait()

    @backwards_compat(pre_008=_play_audio_old, classic_core=_play_audio_classic)
    def play_audio(self, filename: str, instant: bool = False):
        """
        Queue and audio file for playback
        @param filename: File to play
        @param instant: if True audio will be played instantly instead of queued with TTS
        """
        message = dig_for_message() or Message("")
        # if running in docker we need to send binary data to the ovos-audio container
        # if sessions is not default we also need to do it since
        # it likely is a remote client such as hivemind
        send_binary = os.environ.get("IS_OVOS_CONTAINER") or \
                      SessionManager.get(message).session_id != "default"

        if instant:
            mtype = "mycroft.audio.play_sound"
        else:
            mtype = "mycroft.audio.queue"

        if not send_binary:
            data = {"uri": filename}
        else:
            with open(filename, "rb") as f:
                bindata = binascii.hexlify(f.read()).decode('utf-8')
            data = {"audio_ext": filename.split(".")[-1],
                    "binary_data": bindata}

        self.bus.emit(message.forward(mtype, data))

    def __get_response_v1(self, session=None):
        """Helper to get a response from the user

        NOTE:  There is a race condition here.  There is a small amount of
        time between the end of the device speaking and the converse method
        being overridden in this method.  If an utterance is injected during
        this time, the wrong converse method is executed.  The condition is
        hidden during normal use due to the amount of time it takes a user
        to speak a response. The condition is revealed when an automated
        process injects an utterance quicker than this method can flip the
        converse methods.

        Returns:
            str: user's response or None on a timeout
        """
        session = session or SessionManager.get()

        def converse(utterances, lang=None):
            self.__responses[session.session_id] = utterances
            converse.response = utterances[0] if utterances else None
            converse.finished = True
            return True

        # install a temporary conversation handler
        self.activate()
        converse.finished = False
        converse.response = None
        self.converse = converse

        # 10 for listener, 5 for SST, then timeout
        ans = []
        # NOTE: a threading.Event is not used otherwise we can't raise the
        # AbortEvent exception to kill the thread
        # this is for compat with killable_intents decorators
        start = time.time()
        while time.time() - start <= 15 and not ans:
            ans = self.__responses[session.session_id]
            time.sleep(0.1)
            if ans is None:
                # aborted externally (if None)
                self.log.debug("get_response aborted")
                converse.finished = True
                break

        self.converse = self._original_converse
        return ans

    def __handle_get_response(self, message):
        """
        Handle the response message to a previous get_response / speak call
        sent from the intent service
        """
        if message.msg_type == "skill.converse.get_response":
            log_deprecation(
                "Support for message type `skill.converse.get_response` is deprecated, use `{skill_id}.converse.get_response`",
                "0.0.9")
            if message.data.get("skill_id") != self.skill_id:
                return  # not for us!

        # validate session_id to ensure this isnt another
        # user querying the skill at same time
        sess2 = SessionManager.get(message)
        if sess2.session_id not in self.__responses:
            LOG.debug(f"ignoring get_response answer for session: {sess2.session_id}")
            return  # not for us!

        utterances = message.data["utterances"]
        # received get_response
        self.__responses[sess2.session_id] = utterances

    @backwards_compat(classic_core=__get_response_v1, pre_008=__get_response_v1)
    def __get_response(self, session: Session):
        """Helper to get a response from the user

        this method is unsafe and contains a race condition for
         multiple simultaneous queries in ovos-core < 0.0.8

        Returns:
            str: user's response or None on a timeout
        """
        # during alpha 0.0.8 this check is here to handle the edge case missed by the decorator
        # TODO - remove before 0.0.8 stable
        from ovos_core.version import OVOS_VERSION_ALPHA
        if OVOS_VERSION_ALPHA < 40:  # introduced in 0.0.8a40
            return self.__get_response_v1()

        srcm = dig_for_message() or Message("", context={"source": "skills",
                                                         "skill_id": self.skill_id})
        srcm.context["session"] = session.serialize()

        LOG.debug(f"get_response session: {session.session_id}")
        ans = []

        # NOTE: a threading.Event is not used otherwise we can't raise the
        # AbortEvent exception to kill the thread
        # this is for compat with killable_intents decorators
        start = time.time()
        while time.time() - start <= 15 and not ans:
            ans = self.__responses[session.session_id]
            time.sleep(0.1)
            if ans is None:
                # aborted externally (if None)
                self.log.debug("get_response aborted")
                break
        return ans

    def get_response(self, dialog: str = '', data: Optional[dict] = None,
                     validator: Optional[Callable[[str], bool]] = None,
                     on_fail: Optional[Union[str, Callable[[str], str]]] = None,
                     num_retries: int = -1, message: Message = None) -> Optional[str]:
        """
        Get a response from the user. If a dialog is supplied it is spoken,
        followed immediately by listening for a user response. If the dialog is
        omitted, listening is started directly. The response may optionally be
        validated before returning.
        @param dialog: Optional dialog resource or string to speak
        @param data: Optional data to render dialog with
        @param validator: Optional method to validate user input with. Accepts
            the user's utterance as an arg and returns True if it is valid.
        @param on_fail: Optional string or method that accepts a failing
            utterance and returns a string to be spoken when validation fails.
        @param num_retries: Number of times to retry getting a user response;
            -1 will retry infinitely.
            * If the user asks to "cancel", this method will exit
            * If the user doesn't respond and this is `-1` this will only retry
              once.
        @return: String user response (None if no valid response is given)
        """
        message = message or dig_for_message() or \
                  Message('mycroft.mic.listen', context={"skill_id": self.skill_id})
        data = data or {}

        session = SessionManager.get(message)
        self.__responses[session.session_id] = []
        self.bus.emit(message.forward("skill.converse.get_response.enable",
                                      {"skill_id": self.skill_id}))

        def on_fail_default(utterance):
            fail_data = data.copy()
            fail_data['utterance'] = utterance
            if on_fail:
                if self.dialog_renderer:
                    return self.dialog_renderer.render(on_fail, fail_data)
                return on_fail
            else:
                if self.dialog_renderer:
                    return self.dialog_renderer.render(dialog, data)
                return dialog

        def is_cancel(utterance):
            return self.voc_match(utterance, 'cancel')

        def validator_default(utterance):
            # accept anything except 'cancel'
            return not is_cancel(utterance)

        on_fail_fn = on_fail if callable(on_fail) else on_fail_default
        validator = validator or validator_default

        # Speak query and wait for user response
        if dialog:
            self.speak_dialog(dialog, data, expect_response=True, wait=True)
        else:
            self.bus.emit(message.forward('mycroft.mic.listen'))

        # NOTE: self._wait_response launches a killable thread
        #  the thread waits for a user response for 15 seconds
        #  if no response it will re-prompt the user up to num_retries
        # see killable_event decorators for more info

        #  _wait_response contains a loop that gets validated results
        #  from the killable thread and returns the answer
        ans = self._wait_response(is_cancel, validator, on_fail_fn,
                                  num_retries, message)
        self.bus.emit(message.forward("skill.converse.get_response.disable",
                                      {"skill_id": self.skill_id}))
        return ans

    def _wait_response(self, is_cancel: callable, validator: callable,
                       on_fail: callable, num_retries: int,
                       message: Message) -> Optional[str]:
        """
        Loop until a valid response is received from the user or the retry
        limit is reached.
        @param is_cancel: Function that returns `True` if user asked to cancel
        @param validator: Function that returns `True` if user input is valid
        @param on_fail: Function to call if validator returns `False`
        @param num_retries: Number of times to retry getting a response
        @returns: User response if validated, else None
        """
        session = SessionManager.get(message)

        # self.__validated_responses.get(session.session_id) <- set in a killable thread
        self._real_wait_response(is_cancel, validator, on_fail, num_retries, message)

        # wait for answer from killable thread
        ans = []
        while not ans:
            # TODO: Refactor to Event
            time.sleep(0.1)
            ans = self.__validated_responses.get(session.session_id)
            if ans or ans is None:  # canceled response
                break

        if session.session_id in self.__validated_responses:
            self.__validated_responses.pop(session.session_id)

        if isinstance(ans, list):
            ans = ans[0]  # TODO handle multiple transcriptions

        return ans

    def _validate_response(self, response: list,
                           sess: Session,
                           is_cancel: callable,
                           validator: callable,
                           on_fail: callable):
        reprompt_speak = None
        ans = response[0]  # TODO handle multiple transcriptions

        # catch user saying 'cancel'
        if is_cancel(ans):
            # signal get_response loop to stop
            self.__responses[sess.session_id] = None
            # return None in self.get_response
            self.__validated_responses[sess.session_id] = None
            return None

        validated = validator(ans)
        if not validated:
            reprompt_speak = on_fail(response)
            self.__responses[sess.session_id] = []  # re-prompt
        else:
            # returns the validated value or the response
            # (backwards compat)
            self.__validated_responses[sess.session_id] = ans if validated is True else validated
            # signal get_response loop to stop
            self.__responses[sess.session_id] = None

        return reprompt_speak

    def _handle_killed_wait_response(self):
        """
        Handle "stop" request when getting a response.
        """
        self.__responses = {k: None for k in self.__responses}
        self.__validated_responses = {k: None for k in self.__validated_responses}
        self.converse = self._original_converse

    @killable_event("mycroft.skills.abort_question", exc=AbortQuestion,
                    callback=_handle_killed_wait_response, react_to_stop=True)
    def _real_wait_response(self, is_cancel, validator, on_fail, num_retries,
                            message: Message):
        """

        runs in a thread, result retrieved via self.__responses[sess.session_id]

        Loop until a valid response is received from the user or the retry
        limit is reached.

        Arguments:
            is_cancel (callable): function checking cancel criteria
            validator (callbale): function checking for a valid response
            on_fail (callable): function handling retries

        """
        sess = SessionManager.get(message)

        num_fails = 0
        self.__validated_responses[sess.session_id] = []

        while True:

            response = self.__get_response(sess)
            reprompt = None

            if response is None:
                break  # killed externally
            elif response:
                reprompt = self._validate_response(response, sess,
                                                   is_cancel, validator, on_fail)
                if reprompt:
                    # reset counter, user said something and we reformulated the question
                    num_fails = 0
            else:
                # empty response
                num_fails += 1
                LOG.debug(f"get_response N fails: {num_fails}")

                # if nothing said, prompt one more time
                if num_fails >= num_retries and num_retries >= 0:  # stop trying, exceeded num_retries
                    # signal get_response loop to stop
                    self.__responses[sess.session_id] = None
                    # return None in self.get_response
                    self.__validated_responses[sess.session_id] = None

            if self.__responses.get(sess.session_id) is None:
                return  # dont prompt

            # re-prompt user
            if reprompt:
                self.speak(reprompt, expect_response=True)
            else:
                self.bus.emit(message.reply('mycroft.mic.listen'))

    @staticmethod
    def __acknowledge_classic():
        """
        Acknowledge a successful request.

        This method plays a sound to acknowledge a request that does not
        require a verbal response. This is intended to provide simple feedback
        to the user that their request was handled successfully.
        """
        # DEPRECATED - note that this is a staticmethod and uses the old endpoint
        # the OVOSSkill class does things properly
        from ovos_utils.sound import play_acknowledge_sound
        return play_acknowledge_sound()

    @backwards_compat(classic_core=__acknowledge_classic)
    def acknowledge(self):
        """
        Acknowledge a successful request.

        This method plays a sound to acknowledge a request that does not
        require a verbal response. This is intended to provide simple feedback
        to the user that their request was handled successfully.
        """
        audio_file = self.config_core.get('sounds', {}).get('acknowledge',
                                                            'snd/acknowledge.mp3')
        self.play_audio(audio_file, instant=True)

    def ask_yesno(self, prompt: str,
                  data: Optional[dict] = None) -> Optional[str]:
        """
        Read prompt and wait for a yes/no answer. This automatically deals with
        translation and common variants, such as 'yeah', 'sure', etc.
        @param prompt: a dialog id or string to read
        @param data: optional data to render dialog with
        @return: 'yes', 'no' or the user response if not matched to 'yes' or
            'no', including a response of None.
        """
        resp = self.get_response(dialog=prompt, data=data)
        answer = yes_or_no(resp, lang=self.lang) if resp else resp
        if answer is True:
            return "yes"
        elif answer is False:
            return "no"
        else:
            return resp

    def ask_selection(self, options: List[str], dialog: str = '',
                      data: Optional[dict] = None, min_conf: float = 0.65,
                      numeric: bool = False):
        """
        Read options, ask dialog question and wait for an answer.

        This automatically deals with fuzzy matching and selection by number
        e.g.

        * "first option"
        * "last option"
        * "second option"
        * "option number four"

        Args:
              options (list): list of options to present user
              dialog (str): a dialog id or string to read AFTER all options
              data (dict): Data used to render the dialog
              min_conf (float): minimum confidence for fuzzy match, if not
                                reached return None
              numeric (bool): speak options as a numeric menu
        Returns:
              string: list element selected by user, or None
        """
        assert isinstance(options, list)

        if not len(options):
            return None
        elif len(options) == 1:
            return options[0]

        if numeric:
            for idx, opt in enumerate(options):
                number = pronounce_number(idx + 1, self.lang)
                self.speak(f"{number}, {opt}", wait=True)
        else:
            opt_str = join_list(options, "or", lang=self.lang) + "?"
            self.speak(opt_str, wait=True)

        resp = self.get_response(dialog=dialog, data=data)

        if resp:
            match, score = match_one(resp, options)
            if score < min_conf:
                if self.voc_match(resp, 'last'):
                    resp = options[-1]
                else:
                    num = extract_number(resp, ordinals=True, lang=self.lang)
                    resp = None
                    if num and num <= len(options):
                        resp = options[num - 1]
            else:
                resp = match
        return resp

    def voc_list(self, voc_filename: str,
                 lang: Optional[str] = None) -> List[str]:
        """
        Get list of vocab options for the requested resource and cache the
        results for future references.
        @param voc_filename: Name of vocab resource to get options for
        @param lang: language to get vocab for (default self.lang)
        @return: list of string vocab options
        """
        lang = lang or self.lang
        cache_key = lang + voc_filename

        if cache_key not in self._voc_cache:
            vocab = self.resources.load_vocabulary_file(voc_filename) or \
                    CoreResources(lang).load_vocabulary_file(voc_filename)
            if vocab:
                self._voc_cache[cache_key] = list(chain(*vocab))

        return self._voc_cache.get(cache_key) or []

    def voc_match(self, utt: str, voc_filename: str, lang: Optional[str] = None,
                  exact: bool = False):
        """
        Determine if the given utterance contains the vocabulary provided.

        By default the method checks if the utterance contains the given vocab
        thereby allowing the user to say things like "yes, please" and still
        match against "Yes.voc" containing only "yes". An exact match can be
        requested.

        The method first checks in the current Skill's .voc files and secondly
        in the "res/text" folder of mycroft-core. The result is cached to
        avoid hitting the disk each time the method is called.

        Args:
            utt (str): Utterance to be tested
            voc_filename (str): Name of vocabulary file (e.g. 'yes' for
                                'res/text/en-us/yes.voc')
            lang (str): Language code, defaults to self.lang
            exact (bool): Whether the vocab must exactly match the utterance

        Returns:
            bool: True if the utterance has the given vocabulary it
        """
        match = False
        try:
            _vocs = self.voc_list(voc_filename, lang)
        except FileNotFoundError:
            return False

        if utt and _vocs:
            if exact:
                # Check for exact match
                match = any(i.strip() == utt
                            for i in _vocs)
            else:
                # Check for matches against complete words
                match = any([re.match(r'.*\b' + i + r'\b.*', utt)
                             for i in _vocs])

        return match

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

    # event related skill developer facing utils
    def add_event(self, name: str, handler: callable,
                  handler_info: Optional[str] = None, once: bool = False,
                  speak_errors: bool = True):
        """
        Create event handler for executing intent or other event.

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
                self.log.info("Skill execution aborted")
                self._on_event_end(message, handler_info, skill_data)
                return
            self._on_event_error(error, message, handler_info, skill_data,
                                 speak_errors)

        def on_start(message):
            self._on_event_start(message, handler_info, skill_data)

        def on_end(message):
            self._on_event_end(message, handler_info, skill_data)

        wrapper = create_wrapper(handler, self.skill_id, on_start, on_end,
                                 on_error)
        return self.events.add(name, wrapper, once)

    def remove_event(self, name: str) -> bool:
        """
        Removes an event from bus emitter and events list.

        Args:
            name (string): Name of Intent or Scheduler Event
        Returns:
            bool: True if found and removed, False if not found
        """
        return self.events.remove(name)

    def schedule_event(self, handler: callable,
                       when: Union[int, float, datetime.datetime],
                       data: Optional[dict] = None, name: Optional[str] = None,
                       context: Optional[dict] = None):
        """
        Schedule a single-shot event.

        Args:
            handler:               method to be called
            when (datetime/int/float):   datetime (in system timezone) or
                                   number of seconds in the future when the
                                   handler should be called
            data (dict, optional): data to send when the handler is called
            name (str, optional):  reference name
                                   NOTE: This will not warn or replace a
                                   previously scheduled event of the same
                                   name.
            context (dict, optional): context (dict, optional): message
                                      context to send when the handler
                                      is called
        """
        message = dig_for_message()
        context = context or message.context if message else {}
        context["skill_id"] = self.skill_id
        return self.event_scheduler.schedule_event(handler, when, data, name,
                                                   context=context)

    def schedule_repeating_event(self, handler: callable,
                                 when: Union[int, float, datetime.datetime],
                                 frequency: Union[int, float],
                                 data: Optional[dict] = None,
                                 name: Optional[str] = None,
                                 context: Optional[dict] = None):
        """
        Schedule a repeating event.

        Args:
            handler:                method to be called
            when (datetime):        time (in system timezone) for first
                                    calling the handler, or None to
                                    initially trigger <frequency> seconds
                                    from now
            frequency (float/int):  time in seconds between calls
            data (dict, optional):  data to send when the handler is called
            name (str, optional):   reference name, must be unique
            context (dict, optional): context (dict, optional): message
                                      context to send when the handler
                                      is called
        """
        message = dig_for_message()
        context = context or message.context if message else {}
        context["skill_id"] = self.skill_id
        self.event_scheduler.schedule_repeating_event(handler, when, frequency,
                                                      data, name,
                                                      context=context)

    def update_scheduled_event(self, name: str, data: Optional[dict] = None):
        """
        Change data of event.

        Args:
            name (str): reference name of event (from original scheduling)
            data (dict): event data
        """
        self.event_scheduler.update_scheduled_event(name, data)

    def cancel_scheduled_event(self, name: str):
        """
        Cancel a pending event. The event will no longer be scheduled
        to be executed

        Args:
            name (str): reference name of event (from original scheduling)
        """
        self.event_scheduler.cancel_scheduled_event(name)

    def get_scheduled_event_status(self, name: str) -> int:
        """Get scheduled event data and return the amount of time left

        Args:
            name (str): reference name of event (from original scheduling)

        Returns:
            int: the time left in seconds

        Raises:
            Exception: Raised if event is not found
        """
        return self.event_scheduler.get_scheduled_event_status(name)

    def cancel_all_repeating_events(self):
        """
        Cancel any repeating events started by the skill.
        """
        self.event_scheduler.cancel_all_repeating_events()

    # intent/context skill dev facing utils
    def activate(self, duration_minutes=None):
        """
        Mark this skill as active and push to the top of the active skills list.
        This enables converse method to be called even without skill being
        used in last 5 minutes.

        :param duration_minutes: duration in minutes for skill to remain active
         (-1 for infinite)
        """
        if duration_minutes is None:
            duration_minutes = Configuration().get("converse", {}).get("timeout", 300) / 60  # convert to minutes

        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id

        m1 = msg.forward("intent.service.skills.activate",
                         data={"skill_id": self.skill_id,
                               "timeout": duration_minutes})
        self.bus.emit(m1)

        # backwards compat with mycroft-core
        # TODO - remove soon
        m2 = msg.forward("active_skill_request",
                         data={"skill_id": self.skill_id,
                               "timeout": duration_minutes})
        self.bus.emit(m2)

    def deactivate(self):
        """
        Mark this skill as inactive and remove from the active skills list.
        This stops converse method from being called.
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward(f"intent.service.skills.deactivate",
                                  data={"skill_id": self.skill_id}))

    def disable_intent(self, intent_name: str) -> bool:
        """
        Disable a registered intent if it belongs to this skill.

        Args:
            intent_name (string): name of the intent to be disabled

        Returns:
                bool: True if disabled, False if it wasn't registered
        """
        if intent_name in self.intent_service:
            self.log.info('Disabling intent ' + intent_name)
            name = f'{self.skill_id}:{intent_name}'
            self.intent_service.detach_intent(name)

            langs = [self.core_lang] + self.secondary_langs
            for lang in langs:
                lang_intent_name = f'{name}_{lang}'
                self.intent_service.detach_intent(lang_intent_name)
            return True
        else:
            self.log.error(f'Could not disable {intent_name}, it hasn\'t been registered.')
            return False

    def enable_intent(self, intent_name: str) -> bool:
        """
        (Re)Enable a registered intent if it belongs to this skill.

        Args:
            intent_name: name of the intent to be enabled

        Returns:
            bool: True if enabled, False if it wasn't registered
        """
        intent = self.intent_service.get_intent(intent_name)
        if intent:
            if ".intent" in intent_name:
                self.register_intent_file(intent_name, None)
            else:
                intent.name = intent_name
                self.register_intent(intent, None)
            self.log.debug(f'Enabling intent {intent_name}')
            return True
        else:
            self.log.error(f'Could not enable {intent_name}, it hasn\'t been registered.')
            return False

    def set_context(self, context: str, word: str = '', origin: str = ''):
        """
        Add context to intent service

        Args:
            context:    Keyword
            word:       word connected to keyword
            origin:     origin of context
        """
        if not isinstance(context, str):
            raise ValueError('Context should be a string')
        if not isinstance(word, str):
            raise ValueError('Word should be a string')

        context = self.alphanumeric_skill_id + context
        self.intent_service.set_adapt_context(context, word, origin)

    def remove_context(self, context: str):
        """
        Remove a keyword from the context manager.
        """
        if not isinstance(context, str):
            raise ValueError('context should be a string')
        context = self.alphanumeric_skill_id + context
        self.intent_service.remove_adapt_context(context)

    def set_cross_skill_context(self, context: str, word: str = ''):
        """
        Tell all skills to add a context to the intent service

        Args:
            context:    Keyword
            word:       word connected to keyword
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward('mycroft.skill.set_cross_context',
                                  {'context': context, 'word': word,
                                   'origin': self.skill_id}))

    def remove_cross_skill_context(self, context: str):
        """
        Tell all skills to remove a keyword from the context manager.
        """
        if not isinstance(context, str):
            raise ValueError('context should be a string')
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward('mycroft.skill.remove_cross_context',
                                  {'context': context}))

    # killable_events support
    def __send_stop_signal_classic(self, stop_event: Optional[str] = None):
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

        # NOTE: mycroft does not have an event to stop recording
        # this attempts to force a stop by sending silence to end STT step
        self.bus.emit(Message('mycroft.mic.mute'))
        waiter.wait(1.5)  # the silence from muting should make STT stop recording
        self.bus.emit(Message('mycroft.mic.unmute'))

        # TODO: register TTS events to track state instead of guessing
        waiter.wait(0.5)  # if TTS had not yet started
        self.bus.emit(msg.forward("mycroft.audio.speech.stop"))

    @backwards_compat(classic_core=__send_stop_signal_classic)
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

        # TODO: register TTS events to track state instead of guessing
        waiter.wait(0.5)  # if TTS had not yet started
        self.bus.emit(msg.forward("mycroft.audio.speech.stop"))

    # below deprecated and marked for removal
    @deprecated("use MetricsApi().report_metric", "0.1.0")
    def report_metric(self, name: str, data: dict):
        """
        Report a skill metric to the Mycroft servers.

        Args:
            name (str): Name of metric. Must use only letters and hyphens
            data (dict): JSON dictionary to report. Must be valid JSON
        """
        try:
            if Configuration().get('opt_in', False):
                MetricsApi().report_metric(name, data)
        except Exception as e:
            self.log.error(f'Metric couldn\'t be uploaded, due to a network error ({e})')

    @deprecated("use EmailApi().send_email", "0.1.0")
    def send_email(self, title: str, body: str):
        """
        Send an email to the registered user's email.

        Args:
            title (str): Title of email
            body  (str): HTML body of email. This supports
                         simple HTML like bold and italics
        """
        EmailApi().send_email(title, body, self.skill_id)

    @classproperty
    def network_requirements(self) -> RuntimeRequirements:
        LOG.warning("network_requirements renamed to runtime_requirements, "
                    "will be removed in ovos-core 0.0.8")
        return self.runtime_requirements

    @property
    def voc_match_cache(self) -> Dict[str, List[str]]:
        """
        Backwards-compatible accessor method for vocab cache
        @return: dict vocab resources to parsed resources
        """
        return self._voc_cache

    @voc_match_cache.setter
    def voc_match_cache(self, val):
        self.log.warning("self._voc_cache should not be modified externally. This"
                         "functionality will be deprecated in a future release")
        if isinstance(val, dict):
            self._voc_cache = val

    # below only for api compat with MycroftSkill class
    @deprecated("Use `self.resources.render_dialog`", "0.1.0")
    def translate(self, text: str, data: Optional[dict] = None):
        """
        Deprecated method for translating a dialog file.
        use self.resources.render_dialog(text, data) instead
        """
        return self.resources.render_dialog(text, data)

    @deprecated("Use `self.resources.load_named_value_file`", "0.1.0")
    def translate_namedvalues(self, name: str, delim: str = ','):
        """
        Deprecated method for translating a name/value file.
        use self.resources.load_named_value_filetext, data) instead
        """
        return self.resources.load_named_value_file(name, delim)

    @deprecated("Use `self.resources.load_list_file`", "0.1.0")
    def translate_list(self, list_name: str, data: Optional[dict] = None):
        """
        Deprecated method for translating a list.
        use self.resources.load_list_file(text, data) instead
        """
        return self.resources.load_list_file(list_name, data)

    @deprecated("Use `self.resources.load_template_file`", "0.1.0")
    def translate_template(self, template_name: str,
                           data: Optional[dict] = None):
        """
        Deprecated method for translating a template file
        use self.resources.template_file(text, data) instead
        """
        return self.resources.load_template_file(template_name, data)

    @deprecated("Use `self.resources.load_dialog_files`", "0.1.0")
    def init_dialog(self, root_directory: Optional[str] = None):
        """
        DEPRECATED: use load_dialog_files instead
        """
        self.load_dialog_files(root_directory)

    @deprecated("Use `activate`", "0.1.0")
    def make_active(self):
        """
        Bump skill to active_skill list in intent_service.

        This enables converse method to be called even without skill being
        used in last 5 minutes.

        deprecated: use self.activate() instead
        """
        self.activate()


class SkillGUI(GUIInterface):
    def __init__(self, skill: OVOSSkill):
        """
        Wraps `GUIInterface` for use with a skill.
        """
        self._skill = skill
        skill_id = skill.skill_id
        bus = skill.bus
        config = skill.config_core.get('gui')
        ui_directories = get_ui_directories(skill.root_dir)
        GUIInterface.__init__(self, skill_id=skill_id, bus=bus, config=config,
                              ui_directories=ui_directories)

    @property
    @deprecated("`skill` should not be referenced directly", "0.1.0")
    def skill(self):
        return self._skill


# backwards compat alias, no functional difference
class OVOSFallbackSkill(OVOSSkill):
    def __new__(cls, *args, **kwargs):
        log_deprecation("Implement "
                        "`ovos_workshop.skills.fallback.FallbackSkill`",
                        "0.1.0")
        from ovos_workshop.skills.fallback import FallbackSkill
        return FallbackSkill(*args, **kwargs)
