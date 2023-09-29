import gc
import os
import sys
from os.path import isdir
from inspect import isclass
from types import ModuleType
from typing import Optional
from time import time
from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_config.config import Configuration
from ovos_config.locale import setup_locale
from ovos_plugin_manager.skills import find_skill_plugins
from ovos_utils import wait_for_exit_signal
from ovos_utils.file_utils import FileWatcher
from ovos_utils.log import LOG, deprecated, log_deprecation
from ovos_utils.process_utils import RuntimeRequirements
from ovos_utils.skills.locations import get_skill_directories as _get_skill_dirs

from ovos_workshop.skills.active import ActiveSkill
from ovos_workshop.skills.auto_translatable import UniversalSkill, UniversalFallback
from ovos_workshop.skills.base import BaseSkill
from ovos_workshop.skills.common_play import OVOSCommonPlaybackSkill
from ovos_workshop.skills.common_query_skill import CommonQuerySkill
from ovos_workshop.skills.fallback import FallbackSkill
from ovos_workshop.skills.mycroft_skill import MycroftSkill
from ovos_workshop.skills.ovos import OVOSSkill, OVOSFallbackSkill

SKILL_BASE_CLASSES = [
    BaseSkill, MycroftSkill, OVOSSkill, OVOSFallbackSkill,
    OVOSCommonPlaybackSkill, OVOSFallbackSkill, CommonQuerySkill, ActiveSkill,
    FallbackSkill, UniversalSkill, UniversalFallback
]

SKILL_MAIN_MODULE = '__init__.py'


@deprecated("This method has moved to `ovos_utils.skills.locations`", "0.1.0")
def get_skill_directories(conf=None):
    conf = conf or Configuration()
    return _get_skill_dirs(conf)


@deprecated("This method has moved to `ovos_utils.skills.locations`", "0.1.0")
def get_default_skills_directory(conf=None):
    from ovos_utils.skills.locations import get_default_skills_directory
    conf = conf or Configuration()
    return get_default_skills_directory(conf)


def remove_submodule_refs(module_name: str):
    """
    Ensure submodules are reloaded by removing the refs from sys.modules.

    Python import system puts a reference for each module in the sys.modules
    dictionary to bypass loading if a module is already in memory. To make
    sure skills are completely reloaded these references are deleted.

    Args:
        module_name: name of skill module.
    """
    submodules = []
    LOG.debug(f'Skill module: {module_name}')
    # Collect found submodules
    for m in sys.modules:
        if m.startswith(module_name + '.'):
            submodules.append(m)
    # Remove all references them to in sys.modules
    for m in submodules:
        LOG.debug(f'Removing sys.modules ref for {m}')
        del sys.modules[m]


def load_skill_module(path: str, skill_id: str) -> ModuleType:
    """
    Load a skill module

    This function handles the differences between python 3.4 and 3.5+ as well
    as makes sure the module is inserted into the sys.modules dict.

    Args:
        path: Path to the skill main file (__init__.py)
        skill_id: skill_id used as skill identifier in the module list
    Returns:
        loaded skill module
    """
    import importlib.util
    module_name = skill_id.replace('.', '_')

    remove_submodule_refs(module_name)

    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def get_skill_class(skill_module: ModuleType) -> Optional[callable]:
    """
    Find MycroftSkill based class in skill module.

    Arguments:
        skill_module (module): module to search for Skill class

    Returns:
        (MycroftSkill): Found subclass of MycroftSkill or None.
    """
    if not skill_module:
        raise ValueError("Expected module and got None")
    if callable(skill_module):
        # it's a skill plugin
        # either a func that returns the skill or the skill class itself
        return skill_module

    candidates = []
    for name, obj in skill_module.__dict__.items():
        if isclass(obj):
            if any(issubclass(obj, c) for c in SKILL_BASE_CLASSES) and \
                    not any(obj is c for c in SKILL_BASE_CLASSES):
                candidates.append(obj)

    for candidate in list(candidates):
        others = [clazz for clazz in candidates if clazz != candidate]
        # if we found a subclass of this candidate, it is not the final skill
        if any(issubclass(clazz, candidate) for clazz in others):
            candidates.remove(candidate)

    if candidates:
        if len(candidates) > 1:
            LOG.warning(f"Multiple skills found in a single file!\n"
                        f"{candidates}")
        LOG.debug(f"Loading skill class: {candidates[0]}")
        return candidates[0]
    return None


def get_create_skill_function(skill_module: ModuleType) -> Optional[callable]:
    """Find create_skill function in skill module.

    Arguments:
        skill_module (module): module to search for create_skill function

    Returns:
        (function): Found create_skill function or None.
    """
    if hasattr(skill_module, "create_skill") and \
            callable(skill_module.create_skill):
        log_deprecation("`create_skill` method is no longer supported", "0.1.0")
        return skill_module.create_skill
    return None


class SkillLoader:
    def __init__(self, bus: MessageBusClient,
                 skill_directory: Optional[str] = None,
                 skill_id: Optional[str] = None):
        """
        Create a SkillLoader object to load/unload a skill and
        @param bus: MessageBusClient object
        @param skill_directory: path to skill source
            (containing __init__.py, locale, gui, etc.)
        @param skill_id: Unique ID for the skill
        """
        self.bus = bus
        self._skill_directory = skill_directory
        self._skill_id = skill_id
        self._skill_class = None
        self._loaded = None
        self.load_attempted = False
        self.last_loaded = 0
        self.instance: Optional[BaseSkill] = None
        self.active = True
        self._watchdog = None
        self.config = Configuration()
        self.skill_module = None

    @property
    def loaded(self) -> bool:
        """
        Return True if skill is loaded
        """
        return self._loaded

    @loaded.setter
    def loaded(self, val: bool):
        """
        Set the skill loaded state
        """
        self._loaded = val

    @property
    def skill_directory(self) -> Optional[str]:
        """
        Return the skill directory or `None` if unset and no instance exists
        """
        skill_dir = self._skill_directory
        if self.instance and not skill_dir:
            skill_dir = self.instance.root_dir
        return skill_dir

    @skill_directory.setter
    def skill_directory(self, val: str):
        """
        Set (override) the skill directory
        """
        self._skill_directory = val

    @property
    def skill_id(self) -> Optional[str]:
        """
        Return the skill's reported Skill ID
        """
        skill_id = self._skill_id
        if self.instance and not skill_id:
            skill_id = self.instance.skill_id
        if self.skill_directory and not skill_id:
            skill_id = os.path.basename(self.skill_directory)
        return skill_id

    @skill_id.setter
    def skill_id(self, val: str):
        """
        Set (override) the skill ID
        """
        self._skill_id = val

    @property
    def skill_class(self) -> Optional[callable]:
        """
        Get the skill's class
        """
        skill_class = self._skill_class
        if self.instance and not skill_class:
            skill_class = self.instance.__class__
        if self.skill_module and not skill_class:
            skill_class = get_skill_class(self.skill_module)
        return skill_class

    @skill_class.setter
    def skill_class(self, val: callable):
        """
        Set (override) the skill class
        """
        self._skill_class = val

    @property
    def runtime_requirements(self) -> RuntimeRequirements:
        """
        Return the skill's runtime requirements
        """
        if not self.skill_class or not hasattr(self.skill_class,
                                               "runtime_requirements"):
            return RuntimeRequirements()
        return self.skill_class.runtime_requirements

    @property
    def is_blacklisted(self) -> bool:
        """
        Return true if the skill is blacklisted in configuration
        """
        blacklist = self.config['skills'].get('blacklisted_skills') or []
        if self.skill_id in blacklist:
            return True
        else:
            return False

    @property
    def reload_allowed(self) -> bool:
        """
        Return true if the skill can be reloaded
        """
        return self.active and (self.instance is None or
                                self.instance.reload_skill)

    def reload(self) -> bool:
        """
        Request reload the skill
        @return: True if skill was reloaded
        """
        self.load_attempted = True
        LOG.info(f'ATTEMPTING TO RELOAD SKILL: {self.skill_id}')
        if self.instance:
            if not self.instance.reload_skill:
                LOG.info("skill does not allow reloading!")
                return False  # not allowed
            self._unload()
        return self._load()

    def load(self, _=None) -> bool:
        """
        Request to load the skill
        @return: True if skill was loaded
        """
        LOG.info(f'ATTEMPTING TO LOAD SKILL: {self.skill_id}')
        return self._load()

    def _unload(self):
        """
        Remove listeners and stop threads before loading
        """
        if self._watchdog:
            self._watchdog.shutdown()
            self._watchdog = None

        self._execute_instance_shutdown()
        if self.config.get("debug", False):
            self._garbage_collect()
        self._emit_skill_shutdown_event()

    def unload(self):
        """
        Shutdown and unload the skill instance
        """
        if self.instance:
            self._execute_instance_shutdown()

    def activate(self):
        """
        Mark skill as active and (re)load the skill
        """
        self.active = True
        self.load()

    def deactivate(self):
        """
        Mark skill as inactive and unload the skill
        """
        self.active = False
        self.unload()

    def _execute_instance_shutdown(self):
        """
        Call the shutdown method of the skill being reloaded.
        """
        try:
            self.instance.default_shutdown()
        except Exception as e:
            LOG.exception(f'An error occurred while shutting down '
                          f'{self.skill_id}: {e}')
        else:
            LOG.info(f'Skill {self.skill_id} shut down successfully')
        del self.instance
        self.instance = None

    def _garbage_collect(self):
        """
        Invoke Python garbage collector to remove false references
        """
        gc.collect()
        # Remove two local references that are known
        refs = sys.getrefcount(self.instance) - 2
        if refs > 0:
            LOG.warning(
                f"After shutdown of {self.skill_id} there are still {refs} "
                f"references remaining. The skill won't be cleaned from memory."
            )

    def _emit_skill_shutdown_event(self):
        """
        Emit `mycroft.skills.shutdown` to notify the skill is being shutdown
        """
        message = Message("mycroft.skills.shutdown",
                          {"path": self.skill_directory, "id": self.skill_id})
        self.bus.emit(message)

    def _load(self) -> bool:
        """
        Load the skill if it is not blacklisted, emit load status, start file
        watchers, and return load status.
        @return: True if skill was loaded
        """
        self._prepare_for_load()
        if self.is_blacklisted:
            self._skip_load()
        else:
            self.skill_module = self._load_skill_source()
            self.loaded = self._create_skill_instance()

        self.last_loaded = time()
        self._communicate_load_status()
        self._start_filewatcher()
        return self.loaded

    def _start_filewatcher(self):
        """
        Start a FileWatcher if one isn't already active
        """
        if not self._watchdog:
            self._watchdog = FileWatcher([self.skill_directory],
                                         callback=self._handle_filechange,
                                         recursive=True)

    def _handle_filechange(self, path: str):
        """
        Handle a file change notification by reloading the skill
        """
        LOG.info(f'Skill change detected! {path}')
        try:
            if self.reload_allowed:
                self.reload()
        except Exception as e:
            LOG.exception(f'Unhandled exception occurred while reloading '
                          f'{self.skill_directory}: {e}')

    def _prepare_for_load(self):
        """
        Prepare SkillLoader for skill load
        """
        self.load_attempted = True
        self.instance = None

    def _skip_load(self):
        """
        Log a warning when requested skill load is skipped
        """
        LOG.info(f'Skill {self.skill_id} is blacklisted - '
                 f'it will not be loaded')

    def _load_skill_source(self) -> ModuleType:
        """
        Use Python's import library to load a skill's source code.
        @return: Skill module to instantiate
        """
        main_file_path = os.path.join(self.skill_directory, SKILL_MAIN_MODULE)
        skill_module = None
        if not os.path.exists(main_file_path):
            LOG.error(f'Failed to load {self.skill_id} due to a missing file.')
        else:
            try:
                skill_module = load_skill_module(main_file_path, self.skill_id)
            except Exception as e:
                LOG.exception(f'Failed to load skill: {self.skill_id} ({e})')
        return skill_module

    def _create_skill_instance(self,
                               skill_module: Optional[ModuleType] = None) -> \
            bool:
        """
        Create the skill object.

        Arguments:
            skill_module (module): Module to load from

        Returns:
            (bool): True if skill was loaded successfully.
        """
        skill_module = skill_module or self.skill_module

        try:
            # in skill classes __new__ should fully create the skill object
            skill_class = get_skill_class(skill_module)
            self.instance = skill_class(bus=self.bus, skill_id=self.skill_id)
            return self.instance is not None
        except Exception as e:
            LOG.warning(f"Skill load raised exception: {e}")

        try:
            # attempt to use old style create_skill function entrypoint
            skill_creator = get_create_skill_function(skill_module) or \
                self.skill_class
        except Exception as e:
            LOG.exception(f"Failed to load skill creator: {e}")
            self.instance = None
            return False

        # if the signature supports skill_id and bus pass them
        # to fully initialize the skill in 1 go
        try:
            # skills that do will have bus and skill_id available
            # as soon as they call super()
            self.instance = skill_creator(bus=self.bus,
                                          skill_id=self.skill_id)
        except Exception as e:
            # most old skills do not expose bus/skill_id kwargs
            LOG.warning(f"Legacy skill: {e}")
            self.instance = skill_creator()

        try:
            # finish initialization of skill if we didn't manage to inject
            # skill_id and bus kwargs.
            # these skills only have skill_id and bus available in initialize,
            # not in __init__
            log_deprecation("This initialization is deprecated. Update skill to"
                            "handle passed `skill_id` and `bus` kwargs",
                            "0.1.0")
            if not self.instance.is_fully_initialized:
                self.instance._startup(self.bus, self.skill_id)
        except Exception as e:
            LOG.exception(f'Skill __init__ failed with {e}')
            self.instance = None

        return self.instance is not None

    def _communicate_load_status(self):
        """
        Check internal parameters and emit `mycroft.skills.loaded` or
        `mycroft.skills.loading_failure` as appropriate
        """
        if self.loaded:
            message = Message('mycroft.skills.loaded',
                              {"path": self.skill_directory,
                               "id": self.skill_id,
                               "name": self.instance.name})
            self.bus.emit(message)
            LOG.info(f'Skill {self.skill_id} loaded successfully')
        else:
            message = Message('mycroft.skills.loading_failure',
                              {"path": self.skill_directory,
                               "id": self.skill_id})
            self.bus.emit(message)
            if not self.is_blacklisted:
                LOG.error(f'Skill {self.skill_id} failed to load')
            else:
                LOG.info(f'Skill {self.skill_id} not loaded')


class PluginSkillLoader(SkillLoader):
    def __init__(self, bus, skill_id):
        super().__init__(bus, skill_id=skill_id)

    def load(self, skill_class: Optional[callable] = None) -> bool:
        """
        Load a skill plugin
        @param skill_class: Skill class to instantiate
        @return: True if skill was loaded
        """
        LOG.info('ATTEMPTING TO LOAD PLUGIN SKILL: ' + self.skill_id)
        self._skill_class = skill_class or self._skill_class
        if not self._skill_class:
            raise RuntimeError(f"_skill_class not defined for {self.skill_id}")
        return self._load()

    def _load(self):
        """
        Load the skill if it is not blacklisted, emit load status,
        and return load status.
        @return: True if skill was loaded
        """
        self._prepare_for_load()
        if self.is_blacklisted:
            self._skip_load()
        else:
            self.loaded = self._create_skill_instance()

        self.last_loaded = time()
        self._communicate_load_status()
        return self.loaded


class SkillContainer:
    def __init__(self, skill_id: str, skill_directory: Optional[str] = None,
                 bus: Optional[MessageBusClient] = None):
        """
        Init a SkillContainer.
        @param skill_id: Unique ID of the skill being loaded
        @param skill_directory: path to skill source (if None, directory will be
            located by `skill_id`)
        @param bus: MessageBusClient object to connect (else one is created)
        """
        # ensure any initializations and resource loading is handled
        setup_locale()
        self.bus = bus
        self.skill_id = skill_id
        if not skill_directory:  # preference to local skills instead of plugins
            for p in _get_skill_dirs():
                if isdir(f"{p}/{skill_id}"):
                    skill_directory = f"{p}/{skill_id}"
                    LOG.debug(f"found local skill {skill_id}: {skill_directory}")
                    break
        self.skill_directory = skill_directory
        self.skill_loader = None

    def _connect_to_core(self):
        """
        Initialize messagebus connection and register event to load skill once
        core reports ready.
        """
        if not self.bus:
            self.bus = MessageBusClient()
            self.bus.run_in_thread()
            self.bus.connected_event.wait()

        LOG.debug("checking skills service status")
        response = self.bus.wait_for_response(
            Message(f'mycroft.skills.is_ready',
                    context={"source": "workshop", "destination": "skills"}))
        if response and response.data['status']:
            LOG.info("connected to core")
            self.load_skill()
        else:
            LOG.warning("Skills service not ready yet. Load on ready event.")

        self.bus.on("mycroft.ready", self.load_skill)

    def load_skill(self, message: Optional[Message] = None):
        """
        Load the skill associated with this SkillContainer instance.
        @param message: Message triggering skill load if available
        """
        if self.skill_loader:
            LOG.info("detected core reload, reloading skill")
            self.skill_loader.reload()
            return
        LOG.info("launching skill")
        if not self.skill_directory:
            self._launch_plugin_skill()
        else:
            self._launch_standalone_skill()

    def run(self):
        """
        Connect to core and run until KeyboardInterrupt.
        """
        self._connect_to_core()
        try:
            wait_for_exit_signal()
        except KeyboardInterrupt:
            pass
        if self.skill_loader:
            self.skill_loader.deactivate()

    def _launch_plugin_skill(self):
        """
        Launch a skill plugin associated with this SkillContainer instance.
        """
        plugins = find_skill_plugins()
        if self.skill_id not in plugins:
            raise ValueError(f"unknown skill_id: {self.skill_id}")
        skill_plugin = plugins[self.skill_id]
        self.skill_loader = PluginSkillLoader(self.bus, self.skill_id)
        try:
            self.skill_loader.load(skill_plugin)
        except Exception as e:
            LOG.exception(f'Load of skill {self.skill_id} failed! {e}')

    def _launch_standalone_skill(self):
        """
        Launch a local skill associated with this SkillContainer instance.
        """
        self.skill_loader = SkillLoader(self.bus, self.skill_directory,
                                        skill_id=self.skill_id)
        try:
            self.skill_loader.load()
        except Exception as e:
            LOG.exception(f'Load of skill {self.skill_directory} failed! {e}')


def _launch_script():
    """
    Console script entrypoint
    USAGE: ovos-skill-launcher {skill_id} [path/to/my/skill_id]
    """
    args_count = len(sys.argv)
    if args_count == 2:
        skill_id = sys.argv[1]
        skill = SkillContainer(skill_id)
    elif args_count == 3:
        # user asked explicitly for a directory
        skill_id = sys.argv[1]
        skill_directory = sys.argv[2]
        skill = SkillContainer(skill_id, skill_directory)
    else:
        print("USAGE: ovos-skill-launcher {skill_id} [path/to/my/skill_id]")
        raise SystemExit(2)

    skill.run()


