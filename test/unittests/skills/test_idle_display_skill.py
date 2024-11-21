import unittest

from ovos_utils.fakebus import FakeBus
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.skills.idle_display_skill import IdleDisplaySkill


class TestSkill(IdleDisplaySkill):

    def handle_idle(self):
        pass  # mandatory method


class TestIdleDisplaySkill(unittest.TestCase):
    skill = TestSkill(bus=FakeBus(), skill_id="test_idle_skill")

    def test_00_skill_init(self):
        self.assertIsInstance(self.skill, OVOSSkill)
        self.assertIsInstance(self.skill, IdleDisplaySkill)
        # TODO: Implement more tests
