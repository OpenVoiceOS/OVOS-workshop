import random
import time

from ovos_utils.messagebus import Message, wait_for_reply
from ovos_workshop.frameworks.playback.status import *


class MycroftCommonPlayInterface:
    """ interface for mycroft common play """

    def __init__(self, bus=None):
        self.bus = bus or get_mycroft_bus()
        self.bus.on("play:query.response", self.handle_cps_response)
        self.query_replies = {}
        self.query_extensions = {}
        self.waiting = False
        self.start_ts = 0

    @property
    def cps_status(self):
        return wait_for_reply('play:status.query',
                              reply_type="play:status.response",
                              bus=self.bus).data

    def handle_cps_response(self, message):
        search_phrase = message.data["phrase"]

        if ("searching" in message.data and
                search_phrase in self.query_extensions):
            # Manage requests for time to complete searches
            skill_id = message.data["skill_id"]
            if message.data["searching"]:
                # extend the timeout by N seconds
                # IGNORED HERE, used in mycroft-playback-control skill
                if skill_id not in self.query_extensions[search_phrase]:
                    self.query_extensions[search_phrase].append(skill_id)
            else:
                # Search complete, don't wait on this skill any longer
                if skill_id in self.query_extensions[search_phrase]:
                    self.query_extensions[search_phrase].remove(skill_id)

        elif search_phrase in self.query_replies:
            # Collect all replies until the timeout
            self.query_replies[message.data["phrase"]].append(message.data)

    def send_query(self, phrase, media_type=MediaType.GENERIC):
        self.query_replies[phrase] = []
        self.query_extensions[phrase] = []
        self.bus.emit(Message('play:query', {"phrase": phrase,
                                             "question_type": media_type}))

    def get_results(self, phrase):
        if self.query_replies.get(phrase):
            return self.query_replies[phrase]
        return []

    def search(self, phrase, media_type=MediaType.GENERIC,
               timeout=5):
        self.send_query(phrase, media_type)
        self.waiting = True
        start_ts = time.time()
        while self.waiting and time.time() - start_ts <= timeout:
            time.sleep(0.2)
        self.waiting = False
        res = self.get_results(phrase)
        if res:
            return res
        if media_type != MediaType.GENERIC:
            return self.search(phrase, media_type=MediaType.GENERIC,
                               timeout=timeout)
        return []

    def search_best(self, phrase, media_type=MediaType.GENERIC,
                    timeout=5):
        # check responses
        # Look at any replies that arrived before the timeout
        # Find response(s) with the highest confidence
        best = None
        ties = []
        for handler in self.search(phrase, media_type, timeout):
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

            # will_resume = self.track_status == TrackState.PAUSED \
            #              and not bool(phrase.strip())
            will_resume = False
            return {"skill_id": selected["skill_id"],
                    "phrase": phrase,
                    "question_type": media_type,
                    "trigger_stop": not will_resume,
                    "callback_data": selected.get("callback_data")}

        return {}
