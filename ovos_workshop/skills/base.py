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
"""Common functionality relating to the implementation of mycroft skills."""
import datetime
import re
import sys
import time
import traceback
from copy import copy
from hashlib import md5
from inspect import signature
from itertools import chain
from os.path import join, abspath, dirname, basename, isfile
from threading import Event, RLock
from typing import List, Optional, Dict, Callable, Union

from ovos_bus_client import MessageBusClient
from ovos_bus_client.session import SessionManager
from json_database import JsonStorage
from lingua_franca.format import pronounce_number, join_list
from lingua_franca.parse import yes_or_no, extract_number
from ovos_backend_client.api import EmailApi, MetricsApi
from ovos_bus_client.message import Message, dig_for_message
from ovos_config.config import Configuration
from ovos_config.locations import get_xdg_config_save_path
from ovos_utils import camel_case_split
from ovos_utils.dialog import get_dialog, MustacheDialogRenderer
from ovos_utils.enclosure.api import EnclosureAPI
from ovos_utils.events import EventContainer, EventSchedulerInterface
from ovos_utils.file_utils import FileWatcher
from ovos_utils.gui import GUIInterface, get_ui_directories
from ovos_utils.intents import ConverseTracker
from ovos_utils.intents import Intent, IntentBuilder
from ovos_utils.intents.intent_service_interface import munge_regex, \
    munge_intent_parser, IntentServiceInterface
from ovos_utils.json_helper import merge_dict
from ovos_utils.log import LOG, deprecated, log_deprecation
from ovos_utils.messagebus import get_handler_name, create_wrapper, \
    get_message_lang
from ovos_utils.parse import match_one
from ovos_utils.process_utils import RuntimeRequirements
from ovos_utils.skills import get_non_properties
from ovos_utils.sound import play_acknowledge_sound
from ovos_utils import classproperty

from ovos_workshop.decorators.killable import AbortEvent
from ovos_workshop.decorators.killable import killable_event, \
    AbortQuestion
from ovos_workshop.filesystem import FileSystemAccess
from ovos_workshop.resource_files import ResourceFile, \
    CoreResources, SkillResources, find_resource
from ovos_workshop.settings import SkillSettingsManager


# backwards compat alias
class SkillNetworkRequirements(RuntimeRequirements):
    def __init__(self, *args, **kwargs):
        log_deprecation("Replace with "
                        "`ovos_utils.process_utils.RuntimeRequirements`",
                        "0.1.0")
        super().__init__(*args, **kwargs)


def is_classic_core() -> bool:
    """
    Check if the current core is the classic mycroft-core
    """
    try:
        from mycroft.version import OVOS_VERSION_STR
        return False  # ovos-core
    except ImportError:
        try:
            log_deprecation("Support for `mycroft_core` will be deprecated",
                            "0.1.0")
            from mycroft.version import CORE_VERSION_STR
            return True  # mycroft-core
        except ImportError:
            return False  # standalone


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


class BaseSkill:
    """
    Base class for mycroft skills providing common behaviour and parameters
    to all Skill implementations. This base class does not require `mycroft` to
    be importable

    skill_launcher.py used to be skill_loader-py in mycroft-core

    for launching skills one can use skill_launcher.py to run them standalone
    (eg, docker), but the main objective is to make skills work more like proper
    python objects and allow usage of the class directly

    the considerations are:

    - most skills in the wild don't expose kwargs, so don't accept
      skill_id or bus
    - most skills expect a loader class to set up the bus and skill_id after
      object creation
    - skills can not do pythonic things in init, instead of doing things after
      super() devs are expected to use initialize() which is a mycroft invention
      and non-standard
    - main concern is that anything depending on self.skill_id being set can not
      be used in init method (eg. self.settings and self.file_system)
    - __new__ uncouples the skill init from a helper class, making skills work
      like regular python objects
    - the magic in `__new__` is just so we don't break everything in the wild,
      since we cant start requiring skill_id and bus args

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

        # Get directory of skill source (__init__.py)
        self.root_dir = dirname(abspath(sys.modules[self.__module__].__file__))
        self.res_dir = resources_dir or self.root_dir

        self.gui = gui
        self._bus = bus
        self._enclosure = EnclosureAPI()

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

        # Skill Public API
        self.public_api: Dict[str, dict] = {}

        self.__original_converse = self.converse

        # yay, following python best practices again!
        if self.skill_id and self.bus:
            self._startup(self.bus, self.skill_id)

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

    # not a property in mycroft-core
    @property
    def _is_fully_initialized(self) -> bool:
        """
        Determines if the skill has been fully loaded and setup.
        When True, all data has been loaded and all internal state
        and events set up.
        """
        return self._init_event.is_set()

    # not a property in mycroft-core
    @property
    def _settings_path(self) -> str:
        """
        Absolute file path of this skill's `settings.json` (file may not exist)
        """
        return join(get_xdg_config_save_path(), 'skills', self.skill_id,
                    'settings.json')

    # not a property in mycroft-core
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

    # not a property in mycroft-core
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

    # not a property in mycroft-core
    @property
    def dialog_renderer(self) -> Optional[MustacheDialogRenderer]:
        """
        Get a dialog renderer for this skill. Language will be determined by
        message history to match the language associated with the current
        session or else from Configuration.
        """
        return self._resources.dialog_renderer

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

    # not a property in mycroft-core
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
        lang = self._core_lang
        message = dig_for_message()
        if message:
            lang = get_message_lang(message)
        return lang.lower()

    # property not present in mycroft-core
    @property
    def _core_lang(self) -> str:
        """
        Get the configured default language as a BCP-47 language code.

        NOTE: this should be public, but since if a skill uses this it won't
        work in regular mycroft-core it was made private!
        """
        return self.config_core.get("lang", "en-us").lower()

    # property not present in mycroft-core
    @property
    def _secondary_langs(self) -> List[str]:
        """
        Get the configured secondary languages; resources will be loaded for
        these languages to provide support for multilingual input, in addition
        to `core_lang`. A skill may override this method to specify which
        languages intents are registered in.

        NOTE: this should be public, but since if a skill uses this it won't
        work in regular mycroft-core it was made private!
        """
        return [lang.lower() for lang in self.config_core.get(
                'secondary_langs', []) if lang != self._core_lang]

    # property not present in mycroft-core
    @property
    def _native_langs(self) -> List[str]:
        """
        Languages natively supported by this skill (ie, resource files available
        and explicitly supported). This is equivalent to normalized
        secondary_langs + core_lang.

        NOTE: this should be public, but since if a skill uses this it won't
        work in regular mycroft-core it was made private!
        """
        valid = set([lang.lower() for lang in self._secondary_langs if '-' in
                     lang and lang != self._core_lang] + [self._core_lang])
        return list(valid)

    # property not present in mycroft-core
    @property
    def _alphanumeric_skill_id(self) -> str:
        """
        Skill id converted to only alphanumeric characters and "_".
        Non alphanumeric characters are converted to "_"

        NOTE: this should be public, but since if a skill uses this it won't
        work in regular mycroft-core it was made private!
        """
        return ''.join(c if c.isalnum() else '_'
                       for c in str(self.skill_id))

    # property not present in mycroft-core
    @property
    def _resources(self) -> SkillResources:
        """
        Get a SkillResources object for the current language. Objects are
        initialized for the current language as needed.

        NOTE: this should be public, but since if a skill uses this it won't
        work in regular mycroft-core it was made private!
        """
        return self._load_lang(self.res_dir, self.lang)

    # property not present in mycroft-core
    @property
    def _stop_is_implemented(self) -> bool:
        """
        True if this skill implements a `stop` method
        """
        return self.__class__.stop is not BaseSkill.stop

    # property not present in mycroft-core
    @property
    def _converse_is_implemented(self) -> bool:
        """
        True if this skill implements a `converse` method
        """
        return self.__class__.converse is not BaseSkill.converse or \
            self.__original_converse != self.converse

    # method not present in mycroft-core
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

    # method not present in mycroft-core
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
        if self._is_fully_initialized:
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
        self._settings = JsonStorage(self._settings_path, disable_lock=True)
        with self._settings_lock:
            if self._initial_settings and not self._is_fully_initialized:
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

    # method not present in mycroft-core
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

    # method not present in mycroft-core
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

    # method not present in mycroft-core
    def _load_lang(self, root_directory: Optional[str] = None,
                   lang: Optional[str] = None) -> SkillResources:
        """
        Get a SkillResources object for this skill in the requested `lang` for
        resource files in the requested `root_directory`.
        @param root_directory: root path to find resources (default res_dir)
        @param lang: language to get resources for (default self.lang)
        @return: SkillResources object

        NOTE: this should be public, but since if a skill uses this it won't
        work in regular mycroft-core it was made private!
        """
        lang = lang or self.lang
        root_directory = root_directory or self.res_dir
        if lang not in self._lang_resources:
            self._lang_resources[lang] = SkillResources(root_directory, lang,
                                                        skill_id=self.skill_id)
        return self._lang_resources[lang]

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

            if is_classic_core():
                log_deprecation("Support for mycroft-core is deprecated",
                                "0.1.0")
                # inject ovos exclusive features in vanilla mycroft-core
                # if possible
                # limited support for missing skill deactivated event
                # TODO - update ConverseTracker
                ConverseTracker.connect_bus(self.bus)  # pull/1468
                self.add_event("converse.skill.deactivated",
                               self._handle_skill_deactivated,
                               speak_errors=False)

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
        if self._stop_is_implemented:
            self.add_event('mycroft.stop', self.__handle_stop,
                           speak_errors=False)
        self.add_event('skill.converse.ping', self._handle_converse_ack,
                       speak_errors=False)
        self.add_event('skill.converse.request', self._handle_converse_request,
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

    def detach(self):
        """
        Detach all intents for this skill from the intent_service.
        """
        for (name, _) in self.intent_service:
            name = f'{self.skill_id}:{name}'
            self.intent_service.detach_intent(name)

    def initialize(self):
        """
        Legacy method overridden by skills to perform extra init after __init__.
        Skills should now move any code in this method to `__init__`, after a
        call to `super().__init__`.
        """
        pass

    def _send_public_api(self, message: Message):
        """
        Respond with the skill's public api.
        @param message: `{self.skill_id}.public_api` Message
        """
        message.context["skill_id"] = self.skill_id
        self.bus.emit(message.response(data=self.public_api))

    def get_intro_message(self) -> str:
        """
        Override to return a string to speak on first run. i.e. for post-install
        setup instructions.
        """
        return ""

    # method not present in mycroft-core
    def _handle_skill_activated(self, message: Message):
        """
        Intent service activated a skill. If it was this skill,
        emit a skill activation message.
        @param message: `intent.service.skills.activated` Message
        """
        if message.data.get("skill_id") == self.skill_id:
            self.bus.emit(message.forward(f"{self.skill_id}.activate"))

    # method not present in mycroft-core
    def handle_activate(self, message: Message):
        """
        Called when this skill is considered active by the intent service;
        converse method will be called with every utterance.
        Override this method to do any optional preparation.
        @param message: `{self.skill_id}.activate` Message
        """

    # method not present in mycroft-core
    def _handle_skill_deactivated(self, message):
        """
        Intent service deactivated a skill. If it was this skill,
        emit a skill deactivation message.
        @param message: `intent.service.skills.deactivated` Message
        """
        if message.data.get("skill_id") == self.skill_id:
            self.bus.emit(message.forward(f"{self.skill_id}.deactivate"))

    # method not present in mycroft-core
    def handle_deactivate(self, message):
        """
        Called when this skill is no longer considered active by the intent
        service; converse method will not be called until skill is active again.
        Override this method to do any optional cleanup.
        @param message: `{self.skill_id}.deactivate` Message
        """

    # named make_active in mycroft-core
    def _activate(self):
        """
        Mark this skill as active and push to the top of the active skills list.
        This enables converse method to be called even without skill being
        used in last 5 minutes.
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id

        m1 = msg.forward("intent.service.skills.activate",
                         data={"skill_id": self.skill_id})
        self.bus.emit(m1)

        # backwards compat with mycroft-core
        # TODO - remove soon
        m2 = msg.forward("active_skill_request",
                         data={"skill_id": self.skill_id})
        self.bus.emit(m2)

    # method not present in mycroft-core
    def _deactivate(self):
        """
        Mark this skill as inactive and remove from the active skills list.
        This stops converse method from being called.
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward(f"intent.service.skills.deactivate",
                                  data={"skill_id": self.skill_id}))

    def _handle_converse_ack(self, message: Message):
        """
        Inform skills service if we want to handle converse. Individual skills
        may override the property self.converse_is_implemented to enable or
        disable converse support. Note that this does not affect a skill's
        `active` status.
        @param message: `skill.converse.ping` Message
        """
        self.bus.emit(message.reply(
            "skill.converse.pong",
            data={"skill_id": self.skill_id,
                  "can_handle": self._converse_is_implemented},
            context={"skill_id": self.skill_id}))

    # method not present in mycroft-core
    def _handle_converse_request(self, message: Message):
        """
        If this skill is requested and supports converse, handle the user input
        with `converse`.
        @param message: `skill.converse.request` Message
        """
        skill_id = message.data['skill_id']
        if skill_id == self.skill_id:
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

    def __get_response(self):
        """
        Helper to get a response from the user

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
        # TODO: Support `message` signature like default?
        def converse(utterances, lang=None):
            converse.response = utterances[0] if utterances else None
            converse.finished = True
            return True

        # install a temporary conversation handler
        self._activate()
        converse.finished = False
        converse.response = None
        self.converse = converse

        # 10 for listener, 5 for SST, then timeout
        # NOTE: a threading.Event is not used otherwise we can't raise the
        # AbortEvent exception to kill the thread
        start = time.time()
        while time.time() - start <= 15 and not converse.finished:
            # TODO: Refactor to event-based handling
            time.sleep(0.1)
            if self.__response is not False:
                if self.__response is None:
                    # aborted externally (if None)
                    self.log.debug("get_response aborted")
                converse.finished = True
                converse.response = self.__response  # external override
        self.converse = self.__original_converse
        return converse.response

    def get_response(self, dialog: str = '', data: Optional[dict] = None,
                     validator: Optional[Callable[[str], bool]] = None,
                     on_fail: Optional[Union[str, Callable[[str], str]]] = None,
                     num_retries: int = -1) -> Optional[str]:
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
        data = data or {}

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
            msg = dig_for_message()
            msg = msg.reply('mycroft.mic.listen') if msg else \
                Message('mycroft.mic.listen',
                        context={"skill_id": self.skill_id})
            self.bus.emit(msg)
        return self._wait_response(is_cancel, validator, on_fail_fn,
                                   num_retries)

    def _wait_response(self, is_cancel: callable, validator: callable,
                       on_fail: callable, num_retries: int) -> Optional[str]:
        """
        Loop until a valid response is received from the user or the retry
        limit is reached.
        @param is_cancel: Function that returns `True` if user asked to cancel
        @param validator: Function that returns `True` if user input is valid
        @param on_fail: Function to call if validator returns `False`
        @param num_retries: Number of times to retry getting a response
        @returns: User response if validated, else None
        """
        self.__response = False
        self._real_wait_response(is_cancel, validator, on_fail, num_retries)
        while self.__response is False:
            # TODO: Refactor to Event
            time.sleep(0.1)
        return self.__response or None

    def _handle_killed_wait_response(self):
        """
        Handle "stop" request when getting a response.
        """
        self.__response = None
        self.converse = self.__original_converse

    @killable_event("mycroft.skills.abort_question", exc=AbortQuestion,
                    callback=_handle_killed_wait_response, react_to_stop=True)
    def _real_wait_response(self, is_cancel, validator, on_fail, num_retries):
        """
        Loop until a valid response is received from the user or the retry
        limit is reached.

        Arguments:
            is_cancel (callable): function checking cancel criteria
            validator (callbale): function checking for a valid response
            on_fail (callable): function handling retries

        """
        msg = dig_for_message()
        msg = msg.reply('mycroft.mic.listen') if msg else \
            Message('mycroft.mic.listen',
                    context={"skill_id": self.skill_id})

        num_fails = 0
        while True:
            if self.__response is not False:
                # usually None when aborted externally
                # also allows overriding returned result from other events
                return self.__response

            response = self.__get_response()

            if response is None:
                # if nothing said, prompt one more time
                num_none_fails = 1 if num_retries < 0 else num_retries
                if num_fails >= num_none_fails:
                    self.__response = None
                    return
            else:
                # catch user saying 'cancel'
                if is_cancel(response):
                    self.__response = None
                    return

            validated = validator(response)
            # returns the validated value or the response
            # (backwards compat)
            if validated is not False and validated is not None:
                self.__response = response if validated is True else validated
                return

            num_fails += 1
            if 0 < num_retries < num_fails or self.__response is not False:
                self.__response = None
                return

            line = on_fail(response)
            if line:
                self.speak(line, expect_response=True)
            else:
                self.bus.emit(msg)

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

    # method not present in mycroft-core
    def _voc_list(self, voc_filename: str,
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
            vocab = self._resources.load_vocabulary_file(voc_filename) or \
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
        _vocs = self._voc_list(voc_filename, lang)

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

    def send_email(self, title: str, body: str):
        """
        Send an email to the registered user's email.

        Args:
            title (str): Title of email
            body  (str): HTML body of email. This supports
                         simple HTML like bold and italics
        """
        EmailApi().send_email(title, body, self.skill_id)

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

    # method not present in mycroft-core
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

    # method not present in mycroft-core
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

    # method not present in mycroft-core
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
        for lang in self._native_langs:
            name = f'{self.skill_id}:{intent_file}'
            resource_file = ResourceFile(self._resources.types.intent,
                                         intent_file)
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
        for lang in self._native_langs:
            entity = ResourceFile(self._resources.types.entity, entity_file)
            if entity.file_path is None:
                self.log.error(f'Unable to find "{entity_file}"')
                continue
            filename = str(entity.file_path)
            name = f"{self.skill_id}:{basename(entity_file)}_{md5(entity_file.encode('utf-8')).hexdigest()}"
            self.intent_service.register_padatious_entity(name, filename, lang)

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

            langs = [self._core_lang] + self._secondary_langs
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

        context = self._alphanumeric_skill_id + context
        self.intent_service.set_adapt_context(context, word, origin)

    def remove_context(self, context: str):
        """
        Remove a keyword from the context manager.
        """
        if not isinstance(context, str):
            raise ValueError('context should be a string')
        context = self._alphanumeric_skill_id + context
        self.intent_service.remove_adapt_context(context)

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

    def register_vocabulary(self, entity: str, entity_type: str,
                            lang: Optional[str] = None):
        """
        Register a word to a keyword
        @param entity: word to register
        @param entity_type: Intent handler entity name to associate entity to
        @param lang: language of `entity` (default self.lang)
        """
        keyword_type = self._alphanumeric_skill_id + entity_type
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

    @staticmethod
    def acknowledge():
        """
        Acknowledge a successful request.

        This method plays a sound to acknowledge a request that does not
        require a verbal response. This is intended to provide simple feedback
        to the user that their request was handled successfully.
        """
        return play_acknowledge_sound()

    # method named init_dialog in mycroft-core
    def load_dialog_files(self, root_directory: Optional[str] = None):
        """
        Load dialog files for all configured languages
        @param root_directory: Directory to locate resources in
            (default self.res_dir)
        """
        root_directory = root_directory or self.res_dir
        # If "<skill>/dialog/<lang>" exists, load from there. Otherwise,
        # load dialog from "<skill>/locale/<lang>"
        for lang in self._native_langs:
            resources = self._load_lang(root_directory, lang)
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
        for lang in self._native_langs:
            resources = self._load_lang(root_directory, lang)
            if resources.types.vocabulary.base_directory is None:
                self.log.debug(f'No vocab loaded for {lang}')
            else:
                skill_vocabulary = resources.load_skill_vocabulary(
                    self._alphanumeric_skill_id
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
        for lang in self._native_langs:
            resources = self._load_lang(root_directory, lang)
            if resources.types.regex.base_directory is not None:
                regexes = resources.load_skill_regex(self._alphanumeric_skill_id)
                for regex in regexes:
                    self.intent_service.register_adapt_regex(regex, lang)

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


class SkillGUI(GUIInterface):
    def __init__(self, skill: BaseSkill):
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
