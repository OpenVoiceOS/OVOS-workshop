import unittest


class TestImports(unittest.TestCase):
    """
    These tests are only valid if `mycroft` package is available
    """
    def test_skills(self):
        import ovos_workshop.skills
        self.assertIsNotNone(ovos_workshop.skills.MycroftSkill)
        self.assertIsNotNone(ovos_workshop.skills.OVOSSkill)
        self.assertIsNotNone(ovos_workshop.skills.OVOSFallbackSkill)
