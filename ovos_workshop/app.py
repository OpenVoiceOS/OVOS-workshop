from os.path import isdir, join
from typing import Optional
from ovos_config.locations import get_xdg_config_save_path
from ovos_utils.messagebus import get_mycroft_bus
from ovos_utils.log import log_deprecation
from ovos_utils.gui import GUIInterface
from ovos_bus_client.client.client import MessageBusClient
from ovos_workshop.resource_files import locate_lang_directories
from ovos_workshop.skills.ovos import OVOSSkill


class OVOSAbstractApplication(OVOSSkill):
    def __init__(self, skill_id: str, bus: Optional[MessageBusClient] = None,
                 resources_dir: Optional[str] = None,
                 lang=None, settings: Optional[dict] = None,
                 gui: Optional[GUIInterface] = None,
                 enable_settings_manager: bool = False, **kwargs):
        """
        Create an Application. An application is essentially a skill, but
        designed such that it may be run without an intent service.
        @param skill_id: Unique ID for this application
        @param bus: MessageBusClient to bind to application
        @param resources_dir: optional root resource directory (else defaults to
            application `root_dir`
        @param lang: DEPRECATED language of the application
        @param settings: DEPRECATED settings object
        @param gui: GUIInterface to bind (if `None`, one is created)
        @param enable_settings_manager: if True, enables a SettingsManager for
            this application to manage default settings and backend sync
        """
        self._dedicated_bus = False
        if bus:
            self._dedicated_bus = False
        else:
            self._dedicated_bus = True
            bus = get_mycroft_bus()

        super().__init__(skill_id=skill_id, bus=bus, gui=gui,
                         resources_dir=resources_dir,
                         enable_settings_manager=enable_settings_manager,
                         **kwargs)

        if settings:
            log_deprecation(f"Settings should be set in {self.settings_path}. "
                            f"Passing `settings` to __init__ is not supported.",
                            "0.1.0")
            self.settings.merge(settings)

    @property
    def settings_path(self) -> str:
        """
        Overrides the default path to put settings in `apps` subdirectory.
        """
        return join(get_xdg_config_save_path(), 'apps', self.skill_id,
                    'settings.json')

    def default_shutdown(self):
        """
        Shutdown this application.
        """
        self.clear_intents()
        super().default_shutdown()
        if self._dedicated_bus:
            self.bus.close()

    def get_language_dir(self, base_path: Optional[str] = None,
                         lang: Optional[str] = None) -> Optional[str]:
        """
        Get the best matched language resource directory for the requested lang.
        This will consider dialects for the requested language, i.e. if lang is
        set to pt-pt but only pt-br resources exist, the `pt-br` resource path
        will be returned.
        @param base_path: root path to find resources (default res_dir)
        @param lang: language to get resources for (default self.lang)
        @return: path to language resources if they exist, else None
        """

        base_path = base_path or self.res_dir
        lang = lang or self.lang
        lang_path = join(base_path, lang)

        # base_path/en-us
        if isdir(lang_path):
            return lang_path

        # check for subdialects of same language as a fallback
        # eg, language is set to en-au but only en-us resources are available
        similar_dialect_directories = locate_lang_directories(lang, base_path)
        for directory in similar_dialect_directories:
            if directory.exists():
                return str(directory)

    def clear_intents(self):
        """
        Remove bus event handlers and detach from the intent service to prevent
        multiple registered handlers.
        """
        for intent_name, _ in self.intent_service:
            event_name = f'{self.skill_id}:{intent_name}'
            self.remove_event(event_name)
        # delete old intents before re-registering
        self.intent_service.detach_all()
