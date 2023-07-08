from unittest import TestCase
from unittest.mock import patch

from ovos_utils.messagebus import FakeBus
from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.base import BaseSkill
from ovos_workshop.skills.fallback import FallbackSkillV1, FallbackSkillV2, \
    FallbackSkill


class SimpleFallback(FallbackSkillV1):
    """Simple fallback skill used for test."""
    def initialize(self):
        self.register_fallback(self.fallback_handler, 42)

    def fallback_handler(self, _):
        pass


class V2FallbackSkill(FallbackSkillV2):
    def __init__(self):
        FallbackSkillV2.__init__(self, FakeBus(), "fallback_v2")

    @fallback_handler
    def handle_fallback(self, message):
        pass

    @fallback_handler(10)
    def high_prio_fallback(self, message):
        pass


class TestFallbackSkill(TestCase):
    # TODO: Test `__new__` logic
    pass

    def test_class_inheritance(self):
        from ovos_workshop.skills.ovos import OVOSSkill
        from ovos_workshop.skills.mycroft_skill import MycroftSkill
        fallback = FallbackSkill("test")
        self.assertIsInstance(fallback, BaseSkill)
        self.assertIsInstance(fallback, OVOSSkill)
        self.assertIsInstance(fallback, MycroftSkill)
        self.assertIsInstance(fallback, FallbackSkillV1)
        self.assertIsInstance(fallback, FallbackSkillV2)
        self.assertIsInstance(fallback, FallbackSkill)


class TestFallbackSkillV1(TestCase):
    @staticmethod
    def setup_fallback(fb_class):
        fb_skill = fb_class()
        fb_skill.bind(FakeBus())
        fb_skill.initialize()
        return fb_skill

    def test_inheritance(self):
        from ovos_workshop.skills.ovos import OVOSSkill
        from ovos_workshop.skills.mycroft_skill import MycroftSkill
        fallback = FallbackSkillV1("test")
        self.assertIsInstance(fallback, BaseSkill)
        self.assertIsInstance(fallback, OVOSSkill)
        self.assertIsInstance(fallback, MycroftSkill)
        self.assertIsInstance(fallback, FallbackSkillV1)
        self.assertIsInstance(fallback, FallbackSkillV2)
        self.assertIsInstance(fallback, FallbackSkill)

    def test_make_intent_failure_handler(self):
        # TODO
        pass

    def test_report_timing(self):
        # TODO
        pass

    def test__register_fallback(self):
        # TODO
        pass

    def test_register_fallback(self):
        # TODO
        pass

    def test_remove_registered_handler(self):
        # TODO
        pass

    @patch("ovos_workshop.skills.fallback.FallbackSkillV1."
           "_remove_registered_handler")
    def test_remove_fallback(self, remove_handler):
        def wrapper(handler):
            def wrapped():
                if handler():
                    return True
                return False
            return wrapped

        def _mock_1():
            pass

        def _mock_2():
            pass

        FallbackSkillV1.wrapper_map.append((_mock_1, wrapper(_mock_1)))
        self.assertEqual(len(FallbackSkillV1.wrapper_map), 1)

        FallbackSkillV1.wrapper_map.append((_mock_2, wrapper(_mock_2)))
        self.assertEqual(len(FallbackSkillV1.wrapper_map), 2)

        # Successful remove existing wrapper
        remove_handler.return_value = True
        self.assertTrue(FallbackSkillV1.remove_fallback(_mock_1))
        self.assertEqual(len(FallbackSkillV1.wrapper_map), 1)
        self.assertFalse(FallbackSkillV1.remove_fallback(_mock_1))
        self.assertEqual(len(FallbackSkillV1.wrapper_map), 1)

        # Failed remove existing wrapper
        remove_handler.return_value = False
        self.assertFalse(FallbackSkillV1.remove_fallback(
            FallbackSkillV1.wrapper_map[0][1]))
        self.assertEqual(FallbackSkillV1.wrapper_map, [])

    def test_remove_instance_handlers(self):
        # TODO
        pass

    def test_default_shutdown(self):
        # TODO
        pass

    def test_register_decorated(self):
        # TODO
        pass

    def test_life_cycle(self):
        """
        Test startup and shutdown of a fallback skill.
        Ensure that an added handler is removed as part of default shutdown.
        """
        self.assertEqual(len(FallbackSkillV1.fallback_handlers), 0)
        fb_skill = self.setup_fallback(SimpleFallback)
        self.assertEqual(len(FallbackSkillV1.fallback_handlers), 1)
        self.assertEqual(FallbackSkillV1.wrapper_map[0][0],
                         fb_skill.fallback_handler)
        self.assertEqual(len(FallbackSkillV1.wrapper_map), 1)

        fb_skill.default_shutdown()
        self.assertEqual(len(FallbackSkillV1.fallback_handlers), 0)
        self.assertEqual(len(FallbackSkillV1.wrapper_map), 0)

    def test_manual_removal(self):
        """
        Test that the call to remove_fallback() removes the handler
        """
        self.assertEqual(len(FallbackSkillV1.fallback_handlers), 0)

        # Create skill adding a single handler
        fb_skill = self.setup_fallback(SimpleFallback)
        self.assertEqual(len(FallbackSkillV1.fallback_handlers), 1)

        self.assertTrue(fb_skill.remove_fallback(fb_skill.fallback_handler))
        # Both internal trackers of handlers should be cleared now
        self.assertEqual(len(FallbackSkillV1.fallback_handlers), 0)
        self.assertEqual(len(FallbackSkillV1.wrapper_map), 0)

        # Removing after it's already been removed should fail
        self.assertFalse(fb_skill.remove_fallback(fb_skill.fallback_handler))


class TestFallbackSkillV2(TestCase):
    fallback_skill = FallbackSkillV2(FakeBus(), "test_fallback_v2")

    def test_class_inheritance(self):
        from ovos_workshop.skills.ovos import OVOSSkill
        from ovos_workshop.skills.mycroft_skill import MycroftSkill
        self.assertIsInstance(self.fallback_skill, BaseSkill)
        self.assertIsInstance(self.fallback_skill, OVOSSkill)
        self.assertIsInstance(self.fallback_skill, MycroftSkill)
        self.assertIsInstance(self.fallback_skill, FallbackSkillV1)
        self.assertIsInstance(self.fallback_skill, FallbackSkillV2)
        self.assertIsInstance(self.fallback_skill, FallbackSkill)

    def test_00_init(self):
        self.assertIsInstance(self.fallback_skill, FallbackSkillV2)
        self.assertIsInstance(self.fallback_skill, FallbackSkill)
        self.assertIsInstance(self.fallback_skill, BaseSkill)

    def test_priority(self):
        FallbackSkillV2.fallback_config = {}

        # No config or handlers
        self.assertEqual(self.fallback_skill.priority, 101)
        # Config override
        FallbackSkillV2.fallback_config = \
            {"fallback_priorities": {"test_fallback_v2": 10}}
        self.assertEqual(self.fallback_skill.priority, 10,
                         self.fallback_skill.fallback_config)

        fallback_skill = V2FallbackSkill()

        # Minimum handler
        self.assertEqual(fallback_skill.priority, 10)
        # Config override
        FallbackSkillV2.fallback_config['fallback_priorities'][
            fallback_skill.skill_id] = 80
        self.assertEqual(fallback_skill.priority, 80)

    def test_can_answer(self):
        self.assertFalse(self.fallback_skill.can_answer([""], "en-us"))
        # TODO

    def test_register_system_event_handlers(self):
        # TODO
        pass

    def test_handle_fallback_ack(self):
        # TODO
        pass

    def test_handle_fallback_request(self):
        # TODO
        pass

    def test_register_fallback(self):
        # TODO
        pass

    def test_default_shutdown(self):
        # TODO
        pass

    def test_register_decorated(self):
        # TODO
        pass
