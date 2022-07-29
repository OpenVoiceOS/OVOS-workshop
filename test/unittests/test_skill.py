import json
import unittest
from ovos_workshop.skills.ovos import OVOSSkill
from mycroft.skills import MycroftSkill
from ovos_utils.messagebus import FakeBus
from ovos_tskill_abort import TestAbortSkill


class TestSkill(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            self.bus.emitted_msgs.append(json.loads(msg))

        self.bus.on("message", get_msg)

        self.skill = TestAbortSkill()
        self.skill._startup(self.bus, "abort.test")

    def test_skill_id(self):
        self.assertTrue(isinstance(self.skill, OVOSSkill))
        self.assertTrue(isinstance(self.skill, MycroftSkill))

        self.assertEqual(self.skill.skill_id, "abort.test")
        # if running in ovos-core every message will have the skill_id in context
        for msg in self.bus.emitted_msgs:
            self.assertEqual(msg["context"]["skill_id"], "abort.test")

    def test_intent_register(self):
        padatious_intents = ["abort.test:test.intent",
                             "abort.test:test2.intent",
                             "abort.test:test3.intent"
                             ]
        for msg in self.bus.emitted_msgs:
            if msg["type"] == "padatious:register_intent":
                self.assertTrue(msg["data"]["name"] in padatious_intents)

    def test_registered_events(self):
        registered_events = [e[0] for e in self.skill.events]

        # intent events
        intent_triggers = [f"{self.skill.skill_id}:test.intent",
                           f"{self.skill.skill_id}:test2.intent",
                           f"{self.skill.skill_id}:test3.intent"
                           ]
        for event in intent_triggers:
            self.assertTrue(event in registered_events)

        # base skill class events shared with mycroft-core
        default_skill = ["mycroft.skill.enable_intent",
                         "mycroft.skill.disable_intent",
                         "mycroft.skill.set_cross_context",
                         "mycroft.skill.remove_cross_context",
                         "intent.service.skills.deactivated",
                         "intent.service.skills.activated",
                         "mycroft.skills.settings.changed"]
        for event in default_skill:
            self.assertTrue(event in registered_events)

        # base skill class events exclusive to ovos-core
        default_ovos = ["skill.converse.ping",
                        "skill.converse.request",
                        f"{self.skill.skill_id}.activate",
                        f"{self.skill.skill_id}.deactivate"]
        for event in default_ovos:
            self.assertTrue(event in registered_events)
