import unittest
import shutil

from os import environ
from os.path import isdir, join, dirname


class TestResourceFileMethods(unittest.TestCase):
    def test_locate_base_directories(self):
        from ovos_workshop.resource_files import locate_base_directories
        # TODO

    def test_locate_lang_directories(self):
        from ovos_workshop.resource_files import locate_lang_directories
        # TODO

    def test_resolve_resource_file(self):
        from ovos_workshop.resource_files import resolve_resource_file
        # TODO

    def test_find_resource(self):
        from ovos_workshop.resource_files import find_resource


class TestResourceType(unittest.TestCase):
    from ovos_workshop.resource_files import ResourceType
    # TODO


class TestResourceFile(unittest.TestCase):
    def test_resource_file(self):
        from ovos_workshop.resource_files import ResourceFile
        # TODO

    def test_qml_file(self):
        from ovos_workshop.resource_files import QmlFile, ResourceFile
        self.assertTrue(issubclass(QmlFile, ResourceFile))

    def test_dialog_file(self):
        from ovos_workshop.resource_files import DialogFile, ResourceFile
        self.assertTrue(issubclass(DialogFile, ResourceFile))

    def test_vocab_file(self):
        from ovos_workshop.resource_files import VocabularyFile, ResourceFile
        self.assertTrue(issubclass(VocabularyFile, ResourceFile))

    def test_named_value_file(self):
        from ovos_workshop.resource_files import NamedValueFile, ResourceFile
        self.assertTrue(issubclass(NamedValueFile, ResourceFile))

    def test_list_file(self):
        from ovos_workshop.resource_files import ListFile, ResourceFile
        self.assertTrue(issubclass(ListFile, ResourceFile))

    def test_template_file(self):
        from ovos_workshop.resource_files import TemplateFile, ResourceFile
        self.assertTrue(issubclass(TemplateFile, ResourceFile))

    def test_regex_file(self):
        from ovos_workshop.resource_files import RegexFile, ResourceFile
        self.assertTrue(issubclass(RegexFile, ResourceFile))

    def test_word_file(self):
        from ovos_workshop.resource_files import WordFile, ResourceFile
        self.assertTrue(issubclass(WordFile, ResourceFile))


class TestSkillResources(unittest.TestCase):
    test_data_path = join(dirname(__file__), "xdg_data")

    @classmethod
    def setUpClass(cls) -> None:
        environ['XDG_DATA_HOME'] = cls.test_data_path

    @classmethod
    def tearDownClass(cls) -> None:
        data_path = environ.pop('XDG_DATA_HOME')
        try:
            shutil.rmtree(data_path)
        except:
            pass

    def test_skill_resources(self):
        from ovos_workshop.resource_files import SkillResources
        # TODO

    def test_core_resources(self):
        from ovos_workshop.resource_files import CoreResources, SkillResources
        core_res = CoreResources("en-us")
        self.assertIsInstance(core_res, SkillResources)
        self.assertEqual(core_res.language, "en-us")
        self.assertTrue(isdir(core_res.skill_directory))

    def test_user_resources(self):
        from ovos_workshop.resource_files import UserResources, SkillResources
        user_res = UserResources("en-us", "test.skill")
        self.assertIsInstance(user_res, SkillResources)
        self.assertEqual(user_res.language, "en-us")
        self.assertEqual(user_res.skill_directory,
                         join(self.test_data_path, "mycroft", "resources",
                              "test.skill"))


class TestRegexExtractor(unittest.TestCase):
    from ovos_workshop.resource_files import RegexExtractor
    # TODO
