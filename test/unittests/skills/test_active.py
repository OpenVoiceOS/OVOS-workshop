import unittest
from unittest.mock import Mock

from ovos_utils.messagebus import FakeBus
from ovos_workshop.skills.active import ActiveSkill
from ovos_workshop.skills.base import BaseSkill


class ActiveSkillExample(ActiveSkill):
    active = Mock()

    def make_active(self):
        self.active()
        ActiveSkill.make_active(self)


class TestActiveSkill(unittest.TestCase):
    def test_skill(self):
        skill = ActiveSkillExample()
        self.assertIsInstance(skill, BaseSkill)
        skill.bind(FakeBus())
        skill.active.assert_called_once()
        self.assertTrue(skill.active)
        skill.deactivate()
        self.assertTrue(skill.active)
        skill.handle_skill_deactivated()
        self.assertTrue(skill.active)
        self.assertEqual(skill.active.call_count, 2)
