import unittest

from ovos_utils.process_utils import RuntimeRequirements
from ovos_utils.messagebus import FakeBus
from ovos_utils import classproperty
from ovos_workshop import IntentLayers
from ovos_workshop.resource_files import SkillResources

from ovos_workshop.settings import SkillSettingsManager
from ovos_workshop.skills.ovos import OVOSSkill


class OfflineSkill(OVOSSkill):
    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(internet_before_load=False,
                                   network_before_load=False,
                                   requires_internet=False,
                                   requires_network=False,
                                   no_internet_fallback=True,
                                   no_network_fallback=True)


class LANSkill(OVOSSkill):
    @classproperty
    def runtime_requirements(self):
        scans_on_init = True
        return RuntimeRequirements(internet_before_load=False,
                                   network_before_load=scans_on_init,
                                   requires_internet=False,
                                   requires_network=True,
                                   no_internet_fallback=True,
                                   no_network_fallback=False)


class MockSkill(OVOSSkill):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class TestOVOSSkill(unittest.TestCase):
    bus = FakeBus()
    skill = OVOSSkill(bus=bus, skill_id="test_ovos_skill")

    def test_00_skill_init(self):
        from ovos_utils.skills.audioservice import AudioServiceInterface
        self.assertIsInstance(self.skill.private_settings, dict)
        self.assertIsInstance(self.skill._threads, list)
        self.assertIsNotNone(self.skill._original_converse)
        self.assertIsInstance(self.skill.intent_layers, IntentLayers)
        self.assertIsInstance(self.skill.audio_service, AudioServiceInterface)
        self.assertTrue(self.skill.is_fully_initialized)
        self.assertFalse(self.skill.stop_is_implemented)
        self.assertFalse(self.skill.converse_is_implemented)
        self.assertIsInstance(self.skill.core_lang, str)
        self.assertIsInstance(self.skill.secondary_langs, list)
        self.assertIsInstance(self.skill.native_langs, list)
        self.assertIsInstance(self.skill.alphanumeric_skill_id, str)
        self.assertIsInstance(self.skill.resources, SkillResources)

    def test_activate(self):
        # TODO
        pass

    def test_deactivate(self):
        # TODO
        pass

    def test_play_audio(self):
        # TODO
        pass

    def test_load_lang(self):
        # TODO
        pass

    def test_voc_match(self):
        # TODO
        pass

    def test_voc_list(self):
        # TODO
        pass

    def test_remove_voc(self):
        # TODO
        pass

    def test_register_decorated(self):
        # TODO
        pass

    def test_register_intent_layer(self):
        # TODO
        pass

    def test_send_stop_signal(self):
        # TODO
        pass

    def test_settings_manager_init(self):
        bus = FakeBus()
        skill_default = MockSkill(bus=bus)
        skill_default._startup(bus)

        self.assertIsInstance(skill_default.settings_manager,
                              SkillSettingsManager)

        skill_disabled_settings = MockSkill(bus=bus,
                                            enable_settings_manager=False)
        skill_disabled_settings._startup(bus)
        self.assertIsNone(skill_disabled_settings.settings_manager)

    def test_bus_setter(self):
        bus = FakeBus()
        skill = MockSkill()
        skill._startup(bus)
        self.assertEqual(skill.bus, bus)
        new_bus = FakeBus()
        skill.bus = new_bus
        self.assertEqual(skill.bus, new_bus)
        with self.assertRaises(TypeError):
            skill.bus = None

    def test_runtime_requirements(self):
        self.assertEqual(OfflineSkill.runtime_requirements,
                         RuntimeRequirements(internet_before_load=False,
                                             network_before_load=False,
                                             requires_internet=False,
                                             requires_network=False,
                                             no_internet_fallback=True,
                                             no_network_fallback=True)
                         )
        self.assertEqual(LANSkill.runtime_requirements,
                         RuntimeRequirements(internet_before_load=False,
                                             network_before_load=True,
                                             requires_internet=False,
                                             requires_network=True,
                                             no_internet_fallback=True,
                                             no_network_fallback=False)
                         )
        self.assertEqual(OVOSSkill.runtime_requirements,
                         RuntimeRequirements())

    def test_class_inheritance(self):
        from ovos_workshop.skills.base import BaseSkill
        from ovos_workshop.skills.ovos import OVOSSkill
        from ovos_workshop.skills.mycroft_skill import MycroftSkill
        from ovos_workshop.app import OVOSAbstractApplication

        skill = MockSkill()
        self.assertIsInstance(skill, BaseSkill)
        self.assertIsInstance(skill, OVOSSkill)
        self.assertIsInstance(skill, MycroftSkill)
        self.assertNotIsInstance(skill, OVOSAbstractApplication)

