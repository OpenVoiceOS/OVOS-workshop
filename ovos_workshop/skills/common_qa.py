from abc import abstractmethod
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.frameworks.questions import CommonQAType
from ovos_utils.messagebus import Message


class CommonQASkill(OVOSSkill):
    """ To integrate with the common QA infrastructure of OVOS
    skills should use this base class and override
    `QA_search` (for searching the skill for answers to a question)

    The class makes the skill available to queries from the
    common QA skill and no special vocab is needed.
    """

    def __init__(self, name=None, bus=None):
        super().__init__(name, bus)
        self.supported_questions = [CommonQAType.GENERIC]
        self._current_query = None
        # NOTE: derived skills will likely want to override this list

    def bind(self, bus):
        """Overrides the normal bind method.

        Adds handlers for ovos.commonQA.query
        messages allowing interaction with the commonQA skill.

        This is called automatically during setup, and
        need not otherwise be used.
        """
        if bus:
            super().bind(bus)
            self.add_event('ovos.commonQA.query', self.__handle_QA_query)

    def __handle_QA_query(self, message):
        """Query skill if it can answer given phrase."""
        search_phrase = message.data["phrase"]
        self._current_query = search_phrase
        media_type = message.data.get("question_type", CommonQAType.GENERIC)

        if media_type not in self.supported_questions:
            return

        # invoke the QA handler to let the skill perform its search
        results = self.QA_search(search_phrase, media_type)

        if results:
            # inject skill id in individual results
            for idx, r in enumerate(results):
                results[idx]["skill_id"] = self.skill_id
            self.bus.emit(message.response({"phrase": search_phrase,
                                            "skill_id": self.skill_id,
                                            "results": results,
                                            "searching": False}))
        else:
            # Signal we are done (can't handle it)
            self.bus.emit(message.response({"phrase": search_phrase,
                                            "skill_id": self.skill_id,
                                            "searching": False}))

    def QA_extend_timeout(self, timeout=0.5):
        """ request more time for searching, limits are defined by
        common QA framework, by default max total time is 5 seconds
        per query """
        if self._current_query:
            self.bus.emit(Message("ovos.commonQA.query.response",
                                  {"phrase": self._current_query,
                                   "skill_id": self.skill_id,
                                   "timeout": timeout,
                                   "searching": True}))

    @abstractmethod
    def QA_search(self, phrase, question_type):
        """Analyze phrase to see if it is a answer-able phrase with this skill.

        Arguments:
            phrase (str): User phrase uttered after wh* question,
                e.g. "invented the telephone"
            question_type (CommonQAType): requested CommonQAType to search for,
                little_questions classifier will be used by default

        Returns:
            search_results (list): list of dictionaries with result entries
            {
                "match_confidence": QAMatchConfidence.HIGH,
                "question_type":  CommonQAType.GENERIC,
                "source": "https://wikipedia.or.something",
                "answer": "the answer to your question is 42",
                "image": "http://optional.audioservice.jpg",
                "bg_image": "http://optional.audioservice.background.jpg"
            }
        """
        return []

