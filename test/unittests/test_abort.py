import json
import unittest
from ovos_utils.messagebus import FakeBus, Message
from ovos_tskill_abort import TestAbortSkill
from time import sleep


class TestKillableIntents(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            self.bus.emitted_msgs.append(json.loads(msg))

        self.bus.on("message", get_msg)

        self.skill = TestAbortSkill()
        self.skill._startup(self.bus, "abort.test")

    def test_skills_abort_event(self):
        self.bus.emitted_msgs = []
        # skill will enter a infinite loop unless aborted
        self.assertTrue(self.skill.my_special_var == "default")
        self.bus.emit(Message(f"{self.skill.skill_id}:test.intent"))
        sleep(2)
        # check that intent triggered
        start_msg = {'type': 'mycroft.skill.handler.start',
                     'data': {'name': 'KillableSkill.handle_test_abort_intent'},
                     'context': {'skill_id': 'abort.test'}}
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'still here', 'expect_response': False, 'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'},
                     'context': {'skill_id': 'abort.test'}}
        self.assertIn(start_msg, self.bus.emitted_msgs)
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.my_special_var == "changed")

        # check that intent reacts to mycroft.skills.abort_execution
        # eg, gui can emit this event if some option was selected
        # on screen to abort the current voice interaction
        self.bus.emitted_msgs = []
        self.bus.emit(Message(f"mycroft.skills.abort_execution"))
        sleep(2)

        # check that stop method was called
        self.assertTrue(self.skill.stop_called)

        # check that TTS stop message was emmited
        tts_stop = {'type': 'mycroft.audio.speech.stop', 'data': {}, 'context': {}}
        self.assertIn(tts_stop, self.bus.emitted_msgs)

        # check that cleanup callback was called
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'I am dead', 'expect_response': False, 'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'},
                     'context': {'skill_id': 'abort.test'}}
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.my_special_var == "default")

        # check that we are not getting speak messages anymore
        self.bus.emitted_msgs = []
        sleep(2)
        self.assertTrue(self.bus.emitted_msgs == [])

    def test_skill_stop(self):
        self.bus.emitted_msgs = []
        # skill will enter a infinite loop unless aborted
        self.assertTrue(self.skill.my_special_var == "default")
        self.bus.emit(Message(f"{self.skill.skill_id}:test.intent"))
        sleep(2)
        # check that intent triggered
        start_msg = {'type': 'mycroft.skill.handler.start',
                     'data': {'name': 'KillableSkill.handle_test_abort_intent'},
                     'context': {'skill_id': 'abort.test'}}
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'still here', 'expect_response': False, 'meta': {'skill': 'abort.test'}, 'lang': 'en-us'},
                     'context': {'skill_id': 'abort.test'}}
        self.assertIn(start_msg, self.bus.emitted_msgs)
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.my_special_var == "changed")

        # check that intent reacts to skill specific stop message
        # this is also emitted on mycroft.stop if using OvosSkill class
        self.bus.emitted_msgs = []
        self.bus.emit(Message(f"{self.skill.skill_id}.stop"))
        sleep(2)

        # check that stop method was called
        self.assertTrue(self.skill.stop_called)

        # check that TTS stop message was emmited
        tts_stop = {'type': 'mycroft.audio.speech.stop', 'data': {}, 'context': {}}
        self.assertIn(tts_stop, self.bus.emitted_msgs)

        # check that cleanup callback was called
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'I am dead', 'expect_response': False, 'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'},
                     'context': {'skill_id': 'abort.test'}}
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.my_special_var == "default")

        # check that we are not getting speak messages anymore
        self.bus.emitted_msgs = []
        sleep(2)
        self.assertTrue(self.bus.emitted_msgs == [])

    def test_get_response(self):
        """ TODO send "mycroft.skills.abort_question" and
        confirm only get_response is aborted, speech after is still spoken"""

    def test_developer_stop_msg(self):
        """ TODO send "my.own.abort.msg" and confirm intent3 is aborted
        send "mycroft.skills.abort_execution" and confirm intent3 ignores it"""