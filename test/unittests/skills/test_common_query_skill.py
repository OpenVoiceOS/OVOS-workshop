from unittest import TestCase

from ovos_utils.messagebus import FakeBus
from ovos_workshop.skills.base import BaseSkill
from ovos_workshop.skills.common_query_skill import CommonQuerySkill, CQSMatchLevel


class TestQASkill(CommonQuerySkill):
    def CQS_match_query_phrase(self, phrase):
        pass

    def CQS_action(self, phrase, data):
        pass


class TestCommonQuerySkill(TestCase):
    skill = TestQASkill("test_common_query", FakeBus())

    def test_class_inheritance(self):
        from ovos_workshop.skills.ovos import OVOSSkill
        from ovos_workshop.skills.mycroft_skill import MycroftSkill
        self.assertIsInstance(self.skill, BaseSkill)
        self.assertIsInstance(self.skill, OVOSSkill)
        self.assertIsInstance(self.skill, MycroftSkill)
        self.assertIsInstance(self.skill, CommonQuerySkill)

    def test_00_skill_init(self):
        for conf in self.skill.level_confidence:
            self.assertIsInstance(conf, CQSMatchLevel)
            self.assertIsInstance(self.skill.level_confidence[conf], float)
        self.assertIsNotNone(self.skill.bus.ee.listeners("question:query"))
        self.assertIsNotNone(self.skill.bus.ee.listeners("question:action"))

    def test_handle_question_query(self):
        # TODO
        pass

    def test_get_cq(self):
        # TODO
        pass

    def test_remove_noise(self):
        # TODO
        pass

    def test_calc_confidence(self):
        # TODO
        pass

    def test_handle_query_action(self):
        # TODO
        pass
