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

    @classmethod
    def tearDownClass(cls) -> None:
        remove(cls.test_path)

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
