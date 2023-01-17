import json
import unittest
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.skills.mycroft_skill import MycroftSkill
from mycroft.skills import MycroftSkill as CoreSkill
from ovos_utils.messagebus import FakeBus
from os.path import dirname
from mycroft.skills.skill_loader import SkillLoader

from ovos_workshop.util import is_ovos


class TestSkill(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            msg = json.loads(msg)
            self.bus.emitted_msgs.append(msg)

        self.bus.on("message", get_msg)

        self.skill = SkillLoader(self.bus, f"{dirname(__file__)}/ovos_tskill_abort")
        self.skill.skill_id = "abort.test"
        self.bus.emitted_msgs = []

        self.skill.load()

    def test_skill_id(self):
        self.assertTrue(isinstance(self.skill.instance, OVOSSkill))
        self.assertTrue(isinstance(self.skill.instance, MycroftSkill))

        self.assertEqual(self.skill.skill_id, "abort.test")

        if is_ovos():
            # the metaclass ensures this returns True under ovos-core
            # but we have no control over mycroft-core so can not patch isinstance checks there
            self.assertTrue(isinstance(self.skill.instance, CoreSkill))

            # if running in ovos-core every message will have the skill_id in context
            for msg in self.bus.emitted_msgs:
                if msg["type"] == 'mycroft.skills.loaded': # emitted by SkillLoader, not by skill
                    continue
                self.assertEqual(msg["context"]["skill_id"], "abort.test")

    def test_intent_register(self):
        padatious_intents = ["abort.test:test.intent",
                             "abort.test:test2.intent",
                             "abort.test:test3.intent"]
        for msg in self.bus.emitted_msgs:
            if msg["type"] == "padatious:register_intent":
                self.assertTrue(msg["data"]["name"] in padatious_intents)

    def test_registered_events(self):
        registered_events = [e[0] for e in self.skill.instance.events]

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
                         "mycroft.skills.settings.changed"]
        for event in default_skill:
            self.assertTrue(event in registered_events)

        # base skill class events exclusive to ovos-core
        if is_ovos():
            default_ovos = ["skill.converse.ping",
                            "skill.converse.request",
                            "intent.service.skills.activated",
                            "intent.service.skills.deactivated",
                            f"{self.skill.skill_id}.activate",
                            f"{self.skill.skill_id}.deactivate"]
            for event in default_ovos:
                self.assertTrue(event in registered_events)

    def tearDown(self) -> None:
        self.skill.unload()
