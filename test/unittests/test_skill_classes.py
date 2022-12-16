import unittest
from ovos_workshop.decorators import classproperty
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.skills.base import SkillNetworkRequirements


class OfflineSkill(OVOSSkill):
    @classproperty
    def network_requirements(self):
        return SkillNetworkRequirements(internet_before_load=False,
                                        network_before_load=False,
                                        requires_internet=False,
                                        requires_network=False,
                                        no_internet_fallback=True,
                                        no_network_fallback=True)


class LANSkill(OVOSSkill):
    @classproperty
    def network_requirements(self):
        scans_on_init = True
        return SkillNetworkRequirements(internet_before_load=False,
                                        network_before_load=scans_on_init,
                                        requires_internet=False,
                                        requires_network=True,
                                        no_internet_fallback=True,
                                        no_network_fallback=False)


class TestSkill(unittest.TestCase):

    def test_class_property(self):
        self.assertEqual(OfflineSkill.network_requirements,
                         SkillNetworkRequirements(internet_before_load=False,
                                                  network_before_load=False,
                                                  requires_internet=False,
                                                  requires_network=False,
                                                  no_internet_fallback=True,
                                                  no_network_fallback=True)
                         )
        self.assertEqual(LANSkill.network_requirements,
                         SkillNetworkRequirements(internet_before_load=False,
                                                  network_before_load=True,
                                                  requires_internet=False,
                                                  requires_network=True,
                                                  no_internet_fallback=True,
                                                  no_network_fallback=False)
                         )
        self.assertEqual(OVOSSkill.network_requirements,
                         SkillNetworkRequirements()
                         )
