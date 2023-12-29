from abc import ABC

from ovos_config import Configuration
from ovos_plugin_manager.language import OVOSLangDetectionFactory, OVOSLangTranslationFactory
from ovos_utils.events import get_handler_name
from ovos_utils.log import LOG

from ovos_workshop.resource_files import SkillResources
from ovos_workshop.skills.common_query_skill import CommonQuerySkill
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.skills.fallback import FallbackSkillV2


class UniversalSkill(OVOSSkill):
    """
    Skill that auto translates input/output from any language

    intent handlers are ensured to receive utterances in self.internal_language
    intent handlers are expected to produce utterances in self.internal_language

    self.speak will always translate utterances from
    self.internal_lang to self.lang

    NOTE: self.lang reflects the original query language
          but received utterances are always in self.internal_language
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # the skill internally only works in this language
        self.internal_language = None
        # __tags__ private value will be translated (adapt entities)
        self.translate_tags = True
        # keys added here will have values translated in message.data
        self.translate_keys = ["utterance", "utterances"]

        # autodetect will detect the lang of the utterance regardless of what
        # has been reported to test just type in the cli in another language
        # and watch answers still coming
        self.autodetect = False  # TODO from mycroft.conf
        if self.internal_language is None:
            lang = Configuration().get("lang", "en-us")
            LOG.warning(f"UniversalSkill are expected to specify their "
                        f"internal_language, casting to {lang}")
            self.internal_language = lang

    def _load_lang(self, root_directory=None, lang=None):
        """
        unlike base skill class all resources are in self.internal_language by
        default instead of self.lang (which comes from message)
        this ensures things like self.dialog_render reflect self.internal_lang
        """
        lang = lang or self.internal_language  # self.lang in base class
        root_directory = root_directory or self.res_dir
        if lang not in self._lang_resources:
            self._lang_resources[lang] = SkillResources(root_directory, lang,
                                                        skill_id=self.skill_id)
        return self._lang_resources[lang]

    def detect_language(self, utterance):
        try:
            return self.lang_detector.detect(utterance)
        except Exception as e:
            LOG.error(e)
            # self.lang to account for lang defined in message
            return self.lang.split("-")[0]

    def translate_utterance(self, text, target_lang, sauce_lang=None):
        if self.autodetect:
            sauce_lang = self.detect_language(text)
        else:
            sauce_lang = sauce_lang or self.detect_language(text)
        if sauce_lang.split("-")[0] != target_lang:
            translated = self.translator.translate(text, source=sauce_lang,
                                                   target=target_lang)
            LOG.info("translated " + text + " to " + translated)
            return translated
        return text

    def _translate_message(self, message):
        # translate speech from input lang to internal lang
        sauce_lang = self.lang  # from message or config
        out_lang = self.internal_language  # skill wants input is in this language,

        if sauce_lang == out_lang and not self.autodetect:
            # do nothing
            return message

        translation_data = {"original": {}, "translated": {},
                            "source_lang": sauce_lang,
                            "internal_lang": self.internal_language}

        def _do_tx(thing):
            if isinstance(thing, str):
                thing = self.translate_utterance(thing, target_lang=out_lang,
                                                 sauce_lang=sauce_lang)
            elif isinstance(thing, list):
                thing = [_do_tx(t) for t in thing]
            elif isinstance(thing, dict):
                thing = {k: _do_tx(v) for k, v in thing.items()}
            return thing

        for key in self.translate_keys:
            if key in message.data:
                translation_data["original"][key] = message.data[key]
                translation_data["translated"][key] = message.data[key] = \
                    _do_tx(message.data[key])

        # special case
        if self.translate_tags:
            translation_data["original"]["__tags__"] = message.data["__tags__"]
            for idx, token in enumerate(message.data["__tags__"]):
                message.data["__tags__"][idx] = \
                    self.translate_utterance(token.get("key", ""),
                                             target_lang=out_lang,
                                             sauce_lang=sauce_lang)
            translation_data["translated"]["__tags__"] = \
                message.data["__tags__"]

        message.context["translation_data"] = translation_data
        return message

    def create_universal_handler(self, handler):

        def universal_intent_handler(message):
            message = self._translate_message(message)
            LOG.info(get_handler_name(handler))
            handler(message)

        return universal_intent_handler

    def register_intent(self, intent_parser, handler):
        handler = self.create_universal_handler(handler)
        super().register_intent(intent_parser, handler)

    def register_intent_file(self, intent_file, handler):
        handler = self.create_universal_handler(handler)
        super().register_intent_file(intent_file, handler)

    def speak(self, utterance, *args, **kwargs):
        # translate speech from input lang to output lang
        out_lang = self.lang  # from message or config
        sauce_lang = self.internal_language  # skill output is in this language
        if out_lang != sauce_lang or self.autodetect:
            meta = kwargs.get("meta") or {}
            meta["translation_data"] = {
                "original": utterance,
                "internal_lang": self.internal_language,
                "target_lang": out_lang
            }
            utterance = self.translate_utterance(utterance, sauce_lang, out_lang)
            meta["translation_data"]["translated"] = utterance
            kwargs["meta"] = meta
        super().speak(utterance, *args, **kwargs)


class UniversalFallback(UniversalSkill, FallbackSkillV2):
    """
    Fallback Skill that auto translates input/output from any language

    fallback handlers are ensured to receive utterances and expected to produce
    responses in self.internal_language

    self.speak will always translate utterances from
    self.internal_lang to self.lang

    NOTE: self.lang reflects the original query language
          but received utterances are always in self.internal_language

    """

    def create_universal_fallback_handler(self, handler):
        def universal_fallback_handler(message):
            # auto_Translate input
            message = self._translate_message(message)
            LOG.info(get_handler_name(handler))
            success = handler(self, message)
            if success:
                self.make_active()
            return success

        return universal_fallback_handler

    def register_fallback(self, handler, priority):
        handler = self.create_universal_fallback_handler(handler)
        FallbackSkillV2.register_fallback(self, handler, priority)


class UniversalCommonQuerySkill(UniversalSkill, CommonQuerySkill, ABC):
    """
    CommonQuerySkill that auto translates input/output from any language

    CQS_match_query_phrase and CQS_action are ensured to received phrase in
    self.internal_language

    CQS_match_query_phrase is assumed to return a response in self.internal_lang
    it will be translated back before speaking

    self.speak will always translate utterances from
    self.internal_lang to self.lang

    NOTE: self.lang reflects the original query language
          but received utterances are always in self.internal_language
     """

    def __handle_query_action(self, message):
        """Message handler for question:action.

        Extracts phrase and data from message forward this to the skills
        CQS_action method.
        """
        if message.data["skill_id"] != self.skill_id:
            # Not for this skill!
            return
        if self.lang != self.internal_language or self.autodetect:
            message.data["phrase"] = self.translate_utterance(message.data["phrase"],
                                                              sauce_lang=self.lang,
                                                              target_lang=self.internal_language)

        super().__handle_query_action(message)

    def __get_cq(self, search_phrase):
        if self.lang == self.internal_language and not self.autodetect:
            return super().__get_cq(search_phrase)

        # convert input into internal lang
        search_phrase = self.translate_utterance(search_phrase, self.internal_language, self.lang)
        result = super().__get_cq(search_phrase)
        if not result:
            return None
        answer = result[2]
        # convert response back into source lang
        answer = self.translate_utterance(answer, self.lang, self.internal_language)
        if len(result) > 3:
            # optional callback_data
            result = (result[0], result[1], answer, result[3])
        else:
            result = (result[0], result[1], answer)
        return result

    def remove_noise(self, phrase, lang=None):
        """remove noise to produce essence of question"""
        return super().remove_noise(phrase, self.internal_language)
