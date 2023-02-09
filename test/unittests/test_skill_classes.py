import unittest

from unittest.mock import Mock
from ovos_workshop import OVOSAbstractApplication
from ovos_workshop.decorators import classproperty
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.skills.mycroft_skill import is_classic_core


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


class TestSkill(OVOSSkill):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class TestApplication(OVOSAbstractApplication):
    def __init__(self, *args, **kwargs):
        super().__init__(skill_id="Test Application", *args, **kwargs)


class TestSkills(unittest.TestCase):

    def test_settings_manager_init(self):
        from ovos_utils.messagebus import FakeBus
        bus = FakeBus()
        skill_default = TestSkill(bus=bus)
        skill_default._startup(bus)
        # This doesn't apply to `mycroft-core`, only `ovos-core`
        if not is_classic_core():
            from mycroft.skills.settings import SkillSettingsManager
            self.assertIsInstance(skill_default.settings_manager, SkillSettingsManager)

            skill_disabled_settings = TestSkill(bus=bus,
                                                enable_settings_manager=False)
            skill_disabled_settings._startup(bus)
            self.assertIsNone(skill_disabled_settings.settings_manager)

            plugin = TestApplication(bus=bus)
            plugin._startup(bus)
            self.assertIsNone(plugin.settings_manager)

    def test_bus_setter(self):
        from ovos_utils.messagebus import FakeBus
        bus = FakeBus()
        skill = TestSkill()
        skill._startup(bus)
        self.assertEqual(skill.bus, bus)
        new_bus = FakeBus()
        skill.bus = new_bus
        self.assertEqual(skill.bus, new_bus)
        with self.assertRaises(TypeError):
            skill.bus = None

    def test_class_property(self):
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
                         RuntimeRequirements()
                         )

    def test_class_inheritance(self):
        from ovos_workshop.skills.base import BaseSkill
        from ovos_workshop.skills.ovos import OVOSSkill
        from ovos_workshop.skills.mycroft_skill import MycroftSkill
        from ovos_workshop.skills.fallback import FallbackSkill
        from ovos_workshop.app import OVOSAbstractApplication

        skill = TestSkill()
        self.assertIsInstance(skill, BaseSkill)
        self.assertIsInstance(skill, OVOSSkill)
        self.assertIsInstance(skill, MycroftSkill)
        self.assertNotIsInstance(skill, OVOSAbstractApplication)

        app = TestApplication()
        self.assertIsInstance(app, BaseSkill)
        self.assertIsInstance(app, OVOSSkill)
        self.assertIsInstance(app, MycroftSkill)
        self.assertIsInstance(app, OVOSAbstractApplication)

        mycroft_skill = MycroftSkill()
        self.assertIsInstance(mycroft_skill, BaseSkill)
        self.assertIsInstance(mycroft_skill, MycroftSkill)
        self.assertNotIsInstance(mycroft_skill, OVOSSkill)
        self.assertNotIsInstance(mycroft_skill, OVOSAbstractApplication)

        fallback = FallbackSkill("test")
        self.assertIsInstance(fallback, BaseSkill)
        self.assertIsInstance(fallback, OVOSSkill)
        self.assertIsInstance(fallback, MycroftSkill)
        self.assertIsInstance(fallback, FallbackSkill)
        self.assertNotIsInstance(fallback, OVOSAbstractApplication)
