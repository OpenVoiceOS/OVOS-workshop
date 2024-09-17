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
        generic_q = "what is coca cola"
        specific_q = "how much caffeine is in coca cola"
        specific_q_2 = "what is the stock price for coca cola"
        cw_answer = ("The drink diet coke has 32 milligrams of caffeine in "
                     "250 milliliters.</speak> Provided by CaffeineWiz.")

        generic_conf = self.skill.calc_confidence("coca cola", generic_q,
                                                  CQSMatchLevel.GENERAL,
                                                  cw_answer)
        exact_conf = self.skill.calc_confidence("coca cola", specific_q,
                                                CQSMatchLevel.EXACT, cw_answer)
        low_conf = self.skill.calc_confidence("coca cola", specific_q_2,
                                              CQSMatchLevel.GENERAL, cw_answer)

        self.assertEqual(exact_conf, 1.0)
        self.assertLess(generic_conf, exact_conf)
        self.assertLess(low_conf, generic_conf)

    def test_handle_query_action(self):
        # TODO
        pass
