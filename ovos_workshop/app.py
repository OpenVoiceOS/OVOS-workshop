from os.path import isdir, join

from ovos_config.locations import get_xdg_config_save_path
from ovos_utils.messagebus import get_mycroft_bus
from ovos_utils.log import LOG

from ovos_workshop.resource_files import locate_lang_directories
from ovos_workshop.skills.ovos import OVOSSkill


class OVOSAbstractApplication(OVOSSkill):
    def __init__(self, skill_id, bus=None, resources_dir=None,
                 lang=None, settings=None, gui=None, enable_settings_manager=False):
        super().__init__(bus=bus, gui=gui, resources_dir=resources_dir,
                         enable_settings_manager=enable_settings_manager)
        self.skill_id = skill_id
        self._dedicated_bus = False
        if bus:
            self._dedicated_bus = False
        else:
            self._dedicated_bus = True
            bus = get_mycroft_bus()
        self._startup(bus, skill_id)
        if settings:
            LOG.warning("settings arg is deprecated and will be removed "
                        "in a future release")
            self.settings.merge(settings)

    @property
    def _settings_path(self):
        return join(get_xdg_config_save_path(), 'apps', self.skill_id,
                    'settings.json')

    def default_shutdown(self):
        self.clear_intents()
        super().default_shutdown()
        if self._dedicated_bus:
            self.bus.close()

    def get_language_dir(self, base_path=None, lang=None):
        """ checks for all language variations and returns best path
        eg, if lang is set to pt-pt but only pt-br resources exist,
        those will be loaded instead of failing, or en-gb vs en-us and so on
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
                return directory

    def clear_intents(self):
        # remove bus handlers, otherwise if re-registered we get multiple
        # handler executions
        for intent_name, _ in self.intent_service:
            event_name = f'{self.skill_id}:{intent_name}'
            self.remove_event(event_name)

        self.intent_service.detach_all()  # delete old intents before re-registering
