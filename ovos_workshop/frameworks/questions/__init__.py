from threading import Thread, Event
import time
import enum
import random
from ovos_utils.messagebus import get_mycroft_bus, Message
from ovos_utils.json_helper import merge_dict, is_compatible_dict
from ovos_utils.log import LOG


class CommonQAType(enum.IntEnum):
    GENERIC = 0


class CommonQuestions(Thread):
    bus = None  # mycroft bus connection

    def __init__(self, bus=None, min_timeout=1, max_timeout=5,
                 allow_extensions=True, *args, **kwargs):
        super(CommonQuestions, self).__init__(*args, **kwargs)
        if bus:
            self.bind(bus)
        self.stop_event = Event()
        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
        self.allow_extensions = allow_extensions
        self.query_replies = {}
        self.query_timeouts = {}
        self.waiting = False
        self.search_start = 0
        self._search_results = []

    @classmethod
    def bind(cls, bus=None):
        cls.bus = bus or get_mycroft_bus()
        cls.bus.on("ovos.commonQA.register",
                   cls.handle_register_question_handler)
        cls.bus.on("ovos.commonQA.response",
                   cls.handle_receive_question_response)

    # event loop
    def run(self) -> None:
        self.stop_event.clear()
        while not self.stop_event.is_set():
            pass

    def stop(self):
        self.stop_event.set()

    # bus api
    def handle_register_question_handler(self, message):
        raise NotImplementedError

    def handle_receive_question_response(self, message):
        search_phrase = message.data["phrase"]
        timeout = message.data.get("timeout")
        ts = time.time()
        LOG.debug(f"commonQA received results: {message.data['skill_id']}")

        if message.data.get("searching"):
            # extend the timeout by N seconds
            if timeout and self.allow_extensions and \
                    search_phrase in self.query_timeouts:
                self.query_timeouts[search_phrase] += timeout
            # else -> expired search

        elif search_phrase in self.query_replies:
            # Collect replies until the timeout
            self.query_replies[search_phrase].append(message.data)

            # abort waiting if we gathered enough results
            if ts - self.search_start > self.query_timeouts[search_phrase]:
                self.waiting = False

    def search(self, phrase, question_type=CommonQAType.GENERIC):
        self.query_replies[phrase] = []
        self.query_timeouts[phrase] = self.min_timeout
        self.search_start = time.time()
        self.waiting = True
        self.bus.emit(Message('ovos.commonQA.query',
                              {"phrase": phrase,
                               "question_type": question_type}))

        # if there is no match type defined, lets increase timeout a bit
        # since all skills need to search
        if question_type == CommonQAType.GENERIC:
            bonus = 3  # timeout bonus
        else:
            bonus = 0

        while self.waiting and \
                time.time() - self.search_start <= self.max_timeout + bonus:
            time.sleep(0.1)

        self.waiting = False

        if self.query_replies.get(phrase):
            return [s for s in self.query_replies[phrase] if s.get("results")]

        # fallback to generic question type
        if question_type != CommonQAType.GENERIC:
            LOG.debug("CommonQA falling back to CommonQAType.GENERIC")
            return self.search(phrase, question_type=CommonQAType.GENERIC)
        return []

    def search_best(self, phrase, question_type=CommonQAType.GENERIC):
        # check responses
        # Look at any replies that arrived before the timeout
        # Find response(s) with the highest confidence
        best = None
        ties = []
        for handler in self.search(phrase, question_type):
            if not best or handler["conf"] > best["conf"]:
                best = handler
                ties = []
            elif handler["conf"] == best["conf"]:
                ties.append(handler)

        if best:
            if ties:
                # select randomly
                skills = ties + [best]
                selected = random.choice(skills)
                # TODO: Ask user to pick between ties or do it
                # automagically
            else:
                selected = best

            return {"skill_id": selected["skill_id"],
                    "phrase": phrase,
                    "question_type": question_type,
                    "callback_data": selected.get("callback_data")}

        return {}
