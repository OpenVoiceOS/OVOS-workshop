import unittest

from os.path import join, dirname
from os import remove

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

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = Application(skill_id="TestApplication",
                              settings=cls.settings_obj, gui=cls.gui)
        cls.app._startup(cls.bus)


    def test_settings_init(self):
        self.assertEqual(self.app.settings, self.settings_obj)
        self.assertFalse(self.app.settings['__mycroft_skill_firstrun'])
        self.settings_obj['updated'] = True
        self.assertEqual(self.app.settings, self.settings_obj)

    def test_settings_init_invalid_arg(self):
        app = Application(skill_id="TestApplication",
                          settings=self.settings)
        app._startup(self.bus)
        self.assertNotEqual(app.settings, self.settings)
        self.assertFalse(app.settings['__mycroft_skill_firstrun'])

    def test_gui_init(self):
        self.assertEqual(self.app.gui, self.gui)

    def test_settings_path(self):
        self.assertIn("/apps/", self.app._settings_path)

        # Test settings path conflicts
        test_app = OVOSAbstractApplication(skill_id="test")
        from ovos_workshop.skills import OVOSSkill, MycroftSkill
        test_skill = OVOSSkill()
        mycroft_skill = MycroftSkill()

        test_app._startup(self.bus, "test")
        test_skill._startup(self.bus, "test")
        mycroft_skill._startup(self.bus, "test")

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
