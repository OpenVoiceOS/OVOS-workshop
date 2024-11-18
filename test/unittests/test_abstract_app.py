import unittest
from os import remove
from os.path import join, dirname
from unittest.mock import Mock, patch

from json_database import JsonStorage
from ovos_bus_client.apis.gui import GUIInterface
from ovos_utils.messagebus import FakeBus

from ovos_workshop.app import OVOSAbstractApplication
from ovos_workshop.skills.ovos import OVOSSkill


class Application(OVOSAbstractApplication):
    def __int__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class TestApp(unittest.TestCase):
    bus = FakeBus()

    gui = GUIInterface("TestApplication")

    app = Application(skill_id="TestApplication", gui=gui, bus=bus)

    def test_gui_init(self):
        self.assertEqual(self.app.gui, self.gui)

    def test_settings_path(self):
        self.assertIn("/apps/", self.app.settings_path)

        # Test settings path conflicts
        test_app = OVOSAbstractApplication(skill_id="test", bus=self.bus)
        test_skill = OVOSSkill(skill_id="test", bus=self.bus)

        # Test app vs skill base directories
        self.assertIn("/apps/", test_app.settings_path)
        self.assertIn("/skills/", test_skill.settings_path)

        # Test settings changes
        test_skill.settings['is_skill'] = True
        test_app.settings['is_skill'] = False
        self.assertTrue(test_skill.settings['is_skill'])
        self.assertFalse(test_app.settings['is_skill'])

        # Cleanup test files
        remove(test_app.settings_path)
        remove(test_skill.settings_path)

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
        from ovos_workshop.skills.ovos import OVOSSkill
        from ovos_workshop.app import OVOSAbstractApplication

        self.assertIsInstance(self.app, OVOSSkill)
        self.assertIsInstance(self.app, OVOSAbstractApplication)
