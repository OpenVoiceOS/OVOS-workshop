# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from abc import abstractmethod
from enum import IntEnum
from os.path import dirname
from typing import List, Optional, Tuple

from ovos_bus_client import Message
from ovos_utils.file_utils import resolve_resource_file
from ovos_utils.log import LOG, log_deprecation

from ovos_workshop.decorators.compat import backwards_compat
from ovos_workshop.skills.ovos import OVOSSkill


class CQSMatchLevel(IntEnum):
    EXACT = 1  # Skill could find a specific answer for the question
    CATEGORY = 2  # Skill could find an answer from a category in the query
    GENERAL = 3  # The query could be processed as a general quer


# Copy of CQSMatchLevel to use if the skill returns visual media
CQSVisualMatchLevel = IntEnum('CQSVisualMatchLevel',
                              [e.name for e in CQSMatchLevel])

"""these are for the confidence calculation"""
# TODO: TOPIC_MATCH_RELEVANCE and RELEVANCE_MULTIPLIER stack on the same count of
#   "relevant" words. This adds too much artificial confidence (>100%)
# how much each topic word is worth
# when found in the answer
TOPIC_MATCH_RELEVANCE = 5

# elevate relevance above all else
RELEVANCE_MULTIPLIER = 2

# we like longer articles but only so much
MAX_ANSWER_LEN_FOR_CONFIDENCE = 50

# higher number - less bias for word length
WORD_COUNT_DIVISOR = 100


class CommonQuerySkill(OVOSSkill):
    """Question answering skills should be based on this class.

    The skill author needs to implement `CQS_match_query_phrase` returning an
    answer and can optionally implement `CQS_action` to perform additional
    actions if the skill's answer is selected.

    This class works in conjunction with skill-query which collects
    answers from several skills presenting the best one available.
    """

    def __init__(self, *args, **kwargs):
        # Confidence calculation numbers may be configured per-skill
        self.level_confidence = {
            CQSMatchLevel.EXACT: 0.9,
            CQSMatchLevel.CATEGORY: 0.6,
            CQSMatchLevel.GENERAL: 0.5
        }
        self.relevance_multiplier = TOPIC_MATCH_RELEVANCE * RELEVANCE_MULTIPLIER
        self.input_consumed_multiplier = 0.1
        # TODO: The below defaults of 0.1 add ~25% for a 2-sentence response which is too much
        self.response_sentences_multiplier = 0.1
        self.response_words_multiplier = 1 / WORD_COUNT_DIVISOR

        super().__init__(*args, **kwargs)

        noise_words_filepath = f"text/{self.lang}/noise_words.list"
        default_res = f"{dirname(dirname(__file__))}/res/text/{self.lang}" \
                      f"/noise_words.list"
        noise_words_filename = \
            resolve_resource_file(noise_words_filepath,
                                  config=self.config_core) or \
            resolve_resource_file(default_res, config=self.config_core)

        self._translated_noise_words = {}
        if noise_words_filename:
            with open(noise_words_filename) as f:
                translated_noise_words = f.read().strip()
            self._translated_noise_words[self.lang] = \
                translated_noise_words.split()

    @property
    def translated_noise_words(self) -> List[str]:
        """
        Get a list of "noise" words in the current language
        """
        log_deprecation("self.translated_noise_words will become a "
                        "private variable", "0.1.0")
        return self._translated_noise_words.get(self.lang, [])

    @translated_noise_words.setter
    def translated_noise_words(self, val: List[str]):
        log_deprecation("self.translated_noise_words will become a "
                        "private variable", "0.1.0")
        self._translated_noise_words[self.lang] = val

    def bind(self, bus):
        """Overrides the default bind method of MycroftSkill.

        This registers messagebus handlers for the skill during startup
        but is nothing the skill author needs to consider.
        """
        if bus:
            super().bind(bus)
            self.add_event('question:query', self.__handle_question_query,
                           speak_errors=False)
            self.add_event('question:action', self.__handle_query_action,
                           speak_errors=False)
            self.add_event("ovos.common_query.ping", self.__handle_common_query_ping,
                           speak_errors=False)
            self.__handle_common_query_ping(Message("ovos.common_query.ping"))

    # announce skill to ovos-core
    def __handle_common_query_ping(self, message):
        self.bus.emit(message.reply("ovos.common_query.pong",
                                    {"skill_id": self.skill_id},
                                    {"skill_id": self.skill_id}))

    def __handle_question_query(self, message: Message):
        """
        Handle an incoming user query. Get a result from this skill's
        `CQS_match_query_phrase` method and emit a response back to the intent
        service.
        @param message: Message with matched query 'phrase'
        """
        search_phrase = message.data["phrase"]
        message.context["skill_id"] = self.skill_id
        # First, notify the requestor that we are attempting to handle
        # (this extends a timeout while this skill looks for a match)
        self.bus.emit(message.response({"phrase": search_phrase,
                                        "skill_id": self.skill_id,
                                        "searching": True}))

        result = self.__get_cq(search_phrase)

        if result:
            match = result[0]
            level = result[1]
            answer = result[2]
            callback = result[3] if len(result) > 3 else {}
            confidence = self.calc_confidence(match, search_phrase, level, answer)
            if confidence > 1.0:
                LOG.warning(f"Calculated confidence {confidence} > 1.0")
                confidence = 1.0
            callback["answer"] = answer  # ensure we get it back in CQS_action
            self.bus.emit(message.response({"phrase": search_phrase,
                                            "skill_id": self.skill_id,
                                            "answer": answer,
                                            "handles_speech": True,  # signal we performed speech in the skill
                                            "callback_data": callback,
                                            "conf": confidence}))
        else:
            # Signal we are done (can't handle it)
            self.bus.emit(message.response({"phrase": search_phrase,
                                            "skill_id": self.skill_id,
                                            "searching": False}))

    def __get_cq(self, search_phrase: str) -> (str, CQSMatchLevel, str,
                                               Optional[dict]):
        """
        Invoke the CQS handler to let the skill perform its search
        @param search_phrase: parsed question to get an answer for
        @return: (matched substring from search_phrase,
            confidence level of match, speakable answer, optional callback data)
        """
        try:
            result = self.CQS_match_query_phrase(search_phrase)
        except:
            LOG.exception(f"error matching {search_phrase} with {self.skill_id}")
            result = None
        return result

    def remove_noise(self, phrase: str, lang: str = None) -> str:
        """
        Remove extra words from the query to produce essence of question
        @param phrase: raw phrase to parse (usually from the intent service)
        @param lang: language of `phrase`, else defaults to `self.lang`
        @return: cleaned `phrase` with extra words removed
        """
        lang = lang or self.lang
        phrase = ' ' + phrase + ' '
        for word in self._translated_noise_words.get(lang, []):
            mtch = ' ' + word + ' '
            if phrase.find(mtch) > -1:
                phrase = phrase.replace(mtch, " ")
        phrase = ' '.join(phrase.split())
        return phrase.strip()

    def calc_confidence(self, match: str, phrase: str, level: CQSMatchLevel,
                        answer: str) -> float:
        """
        Calculate a confidence level for the skill response. Skills may override
        this method to implement custom confidence calculation
        @param match: Matched portion of the input phrase
        @param phrase: User input phrase that was evaluated
        @param level: Skill-determined match level of the answer
        @param answer: Speakable response to the input phrase
        @return: Float (0.0-1.0) confidence level of the response
        """
        # Assume the more of the words that get consumed, the better the match
        consumed_pct = len(match.split()) / len(phrase.split())
        if consumed_pct > 1.0:
            consumed_pct = 1.0

        # Approximate the number of sentences in the answer. A trailing `.` will
        # split, so reduce length by 1. If no `.` is present, ensure we count
        # any response as at least 1 sentence
        num_sentences = min(len(answer.split(".")) - 1, 1)

        # Remove articles and question words to approximate the meaningful part
        # of what the skill extracted from the user input
        topic = self.remove_noise(match)

        # Determine how many relevant words from the input are present in the
        # answer
        # TODO: Strip SSML from the answer here
        answer = answer.lower()
        matches = 0
        for word in topic.split(' '):
            if answer.find(word) > -1:
                matches += 1
        LOG.debug(f"Answer matched {matches} words")
        answer_size = len(answer.split(" "))

        # Calculate relevance as the percentage of relevant input words divided
        # by the length of the response. This means that an answer that only
        # contains the input will have a relevance value of 1
        relevance = 0.0
        if answer_size > 0:
            relevance = float(float(matches) / float(answer_size))

        # extra credit for more words up to a point. By default, 50 words is
        # considered optimal
        answer_size = min(MAX_ANSWER_LEN_FOR_CONFIDENCE, answer_size)

        # Calculate bonuses based on calculated values and configured weights
        consumed_pct_bonus = consumed_pct * self.input_consumed_multiplier
        num_sentences_bonus = num_sentences * self.response_sentences_multiplier
        relevance_bonus = relevance * self.relevance_multiplier
        word_count_bonus = answer_size * self.response_words_multiplier

        LOG.debug(f"consumed_pct_bonus={consumed_pct_bonus}|num_sentence_bonus="
                  f"{num_sentences_bonus}|relevance_bonus={relevance_bonus}|"
                  f"word_count_bonus={word_count_bonus}")
        confidence = self.level_confidence[level] + \
                     consumed_pct_bonus + num_sentences_bonus + relevance_bonus + word_count_bonus
        if confidence > 1:
            LOG.warning(f"Calculated confidence > 1.0: {confidence}")
            return 1.0
        return confidence

    def __handle_query_classic(self, message):
        """
        does not perform self.speak, < 0.0.8 this is done by core itself
        """
        if message.data["skill_id"] != self.skill_id:
            # Not for this skill!
            return
        self.activate()
        phrase = message.data["phrase"]
        data = message.data.get("callback_data") or {}
        # Invoke derived class to provide playback data
        self.CQS_action(phrase, data)

    @backwards_compat(classic_core=__handle_query_classic,
                      pre_008=__handle_query_classic)
    def __handle_query_action(self, message: Message):
        """
        If this skill's response was spoken to the user, this method is called.
        Phrase and callback data from `CQS_match_query_phrase` will be passed
        to the `CQS_action` method.
        @param message: `question:action` message
        """
        if message.data["skill_id"] != self.skill_id:
            # Not for this skill!
            return
        self.activate()
        phrase = message.data["phrase"]
        data = message.data.get("callback_data") or {}
        if data.get("answer"):
            self.speak(data["answer"])
        # Invoke derived class to provide playback data
        self.CQS_action(phrase, data)
        self.bus.emit(message.forward("mycroft.skill.handler.complete",
                                      {"handler": "common_query"}))

    @abstractmethod
    def CQS_match_query_phrase(self, phrase: str) -> \
            Optional[Tuple[str, CQSMatchLevel, Optional[dict]]]:
        """
        Determine an answer to the input phrase and return match information, or
        `None` if no answer can be determined.
        @param phrase: User question, i.e. "What is an aardvark"
        @return: (matched portion of the phrase, match confidence level,
            optional callback data) if this skill can answer the question,
            else None.
        """
        return None

    def CQS_action(self, phrase: str, data: dict):
        """
        Take additional action IF the skill is selected.

        The speech is handled by the common query but if the chosen skill
        wants to display media, set a context or prepare for sending
        information info over e-mail this can be implemented here.
        @param phrase: User phrase, i.e. "What is an aardvark"
        @param data: Callback data specified in CQS_match_query_phrase
        """
        # Derived classes may implement this if they use additional media
        # or wish to set context after being called.
        return None
