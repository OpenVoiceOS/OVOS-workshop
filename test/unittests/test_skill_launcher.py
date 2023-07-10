import shutil
import unittest
import sys

from os import environ
from os.path import basename, join, dirname, isdir

from ovos_utils.messagebus import FakeBus


class TestSkillLauncherFunctions(unittest.TestCase):
    test_data_path = join(dirname(__file__), "xdg_data")

    @classmethod
    def setUpClass(cls) -> None:
        environ['XDG_DATA_HOME'] = cls.test_data_path

    @classmethod
    def tearDownClass(cls) -> None:
        data_path = environ.pop('XDG_DATA_HOME')
        if isdir(data_path):
            shutil.rmtree(data_path)

    def test_get_skill_directories(self):
        from ovos_workshop.skill_launcher import get_skill_directories
        # Default directory
        mock_config = {'skills': {}}
        default_directories = get_skill_directories(mock_config)
        for directory in default_directories:
            self.assertEqual(basename(directory), 'skills')
        # Configured directory
        mock_config['skills']['directory'] = 'test'
        test_directories = get_skill_directories(mock_config)
        for directory in test_directories:
            self.assertEqual(basename(directory), 'test')
        self.assertEqual(len(default_directories), len(test_directories))

    def test_get_default_skills_directory(self):
        from ovos_workshop.skill_launcher import get_default_skills_directory
        # Default directory
        mock_config = {'skills': {}}
        default_dir = get_default_skills_directory(mock_config)
        self.assertTrue(isdir(default_dir))
        self.assertEqual(basename(default_dir), 'skills')
        self.assertEqual(dirname(dirname(default_dir)), self.test_data_path)
        # Override directory
        mock_config['skills']['directory'] = 'test'
        test_dir = get_default_skills_directory(mock_config)
        self.assertTrue(isdir(test_dir))
        self.assertEqual(basename(test_dir), 'test')
        self.assertEqual(dirname(dirname(test_dir)), self.test_data_path)

    def test_remove_submodule_refs(self):
        from ovos_workshop.skill_launcher import remove_submodule_refs
        pass

    def test_load_skill_module(self):
        from ovos_workshop.skill_launcher import load_skill_module
        test_path = join(dirname(__file__), "ovos_tskill_abort",
                         "__init__.py")
        skill_id = "test_skill.test"
        module = load_skill_module(test_path, skill_id)
        self.assertIn("test_skill_test", sys.modules)
        self.assertIsNotNone(module)
        self.assertTrue(callable(module.create_skill))

    def test_get_skill_class(self):
        from ovos_workshop.skill_launcher import get_skill_class, \
            load_skill_module
        from ovos_workshop.skills.mycroft_skill import _SkillMetaclass
        test_path = join(dirname(__file__), "ovos_tskill_abort",
                         "__init__.py")
        skill_id = "test_skill.test"
        module = load_skill_module(test_path, skill_id)
        skill = get_skill_class(module)
        self.assertIsNotNone(skill)
        self.assertEqual(skill.__class__, _SkillMetaclass, skill.__class__)

        # Test invalid request
        with self.assertRaises(ValueError):
            get_skill_class(None)

    def test_get_create_skill_function(self):
        from ovos_workshop.skill_launcher import get_create_skill_function, \
            load_skill_module
        test_path = join(dirname(__file__), "ovos_tskill_abort",
                         "__init__.py")
        skill_id = "test_skill.test"
        module = load_skill_module(test_path, skill_id)
        func = get_create_skill_function(module)
        self.assertIsNotNone(func)
        self.assertEqual(func.__name__, "create_skill")

    def test_launch_script(self):
        from ovos_workshop.skill_launcher import _launch_script
        # TODO


class TestSkillLoader(unittest.TestCase):
    bus = FakeBus()

    def test_skill_loader_init(self):
        from ovos_workshop.skill_launcher import SkillLoader
        from ovos_utils.process_utils import RuntimeRequirements

        loader = SkillLoader(self.bus)
        self.assertEqual(loader.bus, self.bus)
        self.assertIsNone(loader.loaded)
        self.assertIsNone(loader.skill_directory)
        self.assertIsNone(loader.skill_id)
        self.assertIsNone(loader.skill_class)
        self.assertEqual(loader.runtime_requirements, RuntimeRequirements())
        self.assertFalse(loader.is_blacklisted)
        self.assertTrue(loader.reload_allowed)

    def test_skill_loader_reload(self):
        from ovos_workshop.skill_launcher import SkillLoader
        # TODO

    def test_skill_loader_load(self):
        from ovos_workshop.skill_launcher import SkillLoader
        # TODO

    def test__unload(self):
        # TODO
        pass

    def test_unload(self):
        # TODO
        pass

    def test_activate(self):
        # TODO
        pass

    def test_deactivate(self):
        # TODO
        pass

    def test_execute_instance_shutdown(self):
        # TODO
        pass

    def test_garbage_collect(self):
        # TODO
        pass

    def test_emit_skill_shutdown_event(self):
        # TODO
        pass

    def test__load(self):
        # TODO
        pass

    def test_start_filewatcher(self):
        # TODO
        pass

    def test_handle_filechange(self):
        # TODO
        pass

    def test_prepare_for_load(self):
        # TODO
        pass

    def test_skip_load(self):
        # TODO
        pass

    def test_load_skill_source(self):
        # TODO
        pass

    def test_create_skill_instance(self):
        # TODO
        pass

    def test_communicate_load_status(self):
        # TODO
        pass


class TestPluginSkillLoader(unittest.TestCase):
    bus = FakeBus()

    def test_plugin_skill_loader_init(self):
        from ovos_workshop.skill_launcher import PluginSkillLoader, SkillLoader
        loader = PluginSkillLoader(self.bus, "test_skill.test")
        self.assertIsInstance(loader, PluginSkillLoader)
        self.assertIsInstance(loader, SkillLoader)
        self.assertEqual(loader.bus, self.bus)
        self.assertEqual(loader.skill_id, "test_skill.test")

    def test_plugin_skill_loader_load(self):
        from ovos_workshop.skill_launcher import PluginSkillLoader
        # TODO


class TestSkillContainer(unittest.TestCase):
    # TODO
    pass
