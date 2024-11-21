import unittest
from unittest.mock import Mock

from ovos_utils.fakebus import FakeBus
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.skills.active import ActiveSkill


class ActiveSkillExample(ActiveSkill):
    active = Mock()

    def activate(self, *args):
        self.active()
        ActiveSkill.activate(self)


class TestActiveSkill(unittest.TestCase):
    def test_skill(self):
        skill = ActiveSkillExample()
        self.assertIsInstance(skill, OVOSSkill)
        skill.bind(FakeBus())
        skill.active.assert_called_once()
        self.assertTrue(skill.active)
        skill.deactivate()
        self.assertTrue(skill.active)
        skill.handle_skill_deactivated()
        self.assertTrue(skill.active)
        self.assertEqual(skill.active.call_count, 2)
