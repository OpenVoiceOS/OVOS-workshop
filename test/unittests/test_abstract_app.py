import unittest

from os.path import join, dirname
from os import remove
from unittest.mock import Mock, patch

from ovos_utils.gui import GUIInterface
from ovos_utils.messagebus import FakeBus
from ovos_workshop.app import OVOSAbstractApplication
from json_database import JsonStorage


class Application(OVOSAbstractApplication):
    def __int__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class TestApp(unittest.TestCase):
    bus = FakeBus()

    test_path = join(dirname(__file__), "test_config.json")
    settings = {'test': True,
                'updated': False}
    settings_obj = JsonStorage(test_path, True)
    settings_obj.update(settings)

    gui = GUIInterface("TestApplication")

    app = Application(skill_id="TestApplication", settings=settings_obj,
                      gui=gui, bus=bus)

    def test_settings_manager_init(self):
        self.assertIsNone(self.app.settings_manager)

    def test_settings_init(self):
        self.assertNotEqual(self.app.settings, self.settings_obj)
        self.assertFalse(self.app.settings['__mycroft_skill_firstrun'])
        self.assertTrue(self.app.settings['test'])
        self.assertFalse(self.app.settings['updated'])
        self.settings_obj['updated'] = True
        self.assertFalse(self.app.settings['updated'])

    def test_settings_init_invalid_arg(self):
        app = Application(skill_id="TestApplication", bus=self.bus,
                          settings=self.settings)
        self.assertNotEqual(app.settings, self.settings)
        self.assertFalse(app.settings['__mycroft_skill_firstrun'])

    def test_gui_init(self):
        self.assertEqual(self.app.gui, self.gui)

    def test_settings_path(self):
        self.assertIn("/apps/", self.app._settings_path)

        # Test settings path conflicts
        test_app = OVOSAbstractApplication(skill_id="test", bus=self.bus)
        from ovos_workshop.skills import OVOSSkill, MycroftSkill
        test_skill = OVOSSkill(skill_id="test", bus=self.bus)
        mycroft_skill = MycroftSkill(skill_id="test", bus=self.bus)

        # Test app vs skill base directories
        self.assertIn("/apps/", test_app._settings_path)
        self.assertIn("/skills/", test_skill._settings_path)
        self.assertEqual(test_skill._settings_path,
                         mycroft_skill._settings_path)
        self.assertEqual(test_skill.settings.path,
                         mycroft_skill.settings.path)
        self.assertEqual(test_skill.settings, mycroft_skill.settings)

        # Test settings changes
        test_skill.settings['is_skill'] = True
        test_app.settings['is_skill'] = False
        self.assertTrue(test_skill.settings['is_skill'])
        self.assertFalse(test_app.settings['is_skill'])

        # Cleanup test files
        remove(test_app._settings_path)
        remove(test_skill._settings_path)

    @patch("ovos_workshop.app.OVOSSkill.default_shutdown")
    def test_default_shutdown(self, skill_shutdown):
        real_clear_intents = self.app.clear_intents
        real_bus_close = self.app.bus.close
        self.app.bus.close = Mock()
        self.app.clear_intents = Mock()
        self.app.default_shutdown()
        self.app.clear_intents.assert_called_once()
        self.app.bus.close.assert_not_called()  # No dedicated bus here
        skill_shutdown.assert_called_once()

        self.app.bus.close = real_bus_close
        self.app.clear_intents = real_clear_intents

    def test_get_language_dir(self):
        # TODO
        pass

    def test_clear_intents(self):
        # TODO
        pass

    def test_class_inheritance(self):
        from ovos_workshop.skills.base import BaseSkill
        from ovos_workshop.skills.ovos import OVOSSkill
        from ovos_workshop.skills.mycroft_skill import MycroftSkill
        from ovos_workshop.app import OVOSAbstractApplication

        self.assertIsInstance(self.app, BaseSkill)
        self.assertIsInstance(self.app, OVOSSkill)
        self.assertIsInstance(self.app, MycroftSkill)
        self.assertIsInstance(self.app, OVOSAbstractApplication)
