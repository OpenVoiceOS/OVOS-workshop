from ovos_config import Configuration
from ovos_plugin_manager.language import OVOSLangDetectionFactory, OVOSLangTranslationFactory
from ovos_utils import get_handler_name
from ovos_utils.log import LOG
from ovos_workshop.resource_files import SkillResources
from ovos_workshop.skills.ovos import OVOSSkill, OVOSFallbackSkill


class UniversalSkill(OVOSSkill):
    ''' Skill that auto translates input/output from any language '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lang_detector = OVOSLangDetectionFactory.create()
        self.translator = OVOSLangTranslationFactory.create()

        self.internal_language = None  # the skill internally only works in this language
        self.translate_tags = True  # __tags__ private value will be translated (adapt entities)
        self.translate_keys = []  # any keys added here will have values translated in message.data
        if self.internal_language is None:
            lang = Configuration().get("lang", "en-us")
            LOG.warning(f"UniversalSkill are expected to specify their internal_language, casting to {lang}")
            self.internal_language = lang

    def _load_lang(self, root_directory=None, lang=None):
        """unlike base skill class all resources are in self.internal_language by default
        instead of self.lang (which comes from message)
        this ensures things like self.dialog_render reflect self.internal_lang
        """
        lang = lang or self.internal_language  # self.lang in base class
        root_directory = root_directory or self.res_dir
        if lang not in self._lang_resources:
            self._lang_resources[lang] = SkillResources(root_directory, lang, skill_id=self.skill_id)
        return self._lang_resources[lang]

    def detect_language(self, utterance):
        try:
            return self.lang_detector.detect(utterance)
        except:
            # self.lang to account for lang defined in message
            return self.lang.split("-")[0]

    def translate_utterance(self, text, target_lang, sauce_lang=None):
        sauce_lang = sauce_lang or self.detect_language(text)
        if sauce_lang.split("-")[0] != target_lang:
            translated = self.translator.translate(text, source=sauce_lang, target=target_lang)
            LOG.info("translated " + text + " to " + translated)
            return translated
        return text

    def _translate_message(self, message):
        # translate speech from input lang to internal lang
        sauce_lang = self.lang  # from message or config
        out_lang = self.internal_language  # skill wants input is in this language,

        ut = message.data.get("utterance")
        if ut:
            message.data["utterance"] = self.translate_utterance(ut, target_lang=out_lang, sauce_lang=sauce_lang)
        if "utterances" in message.data:
            message.data["utterances"] = [self.translate_utterance(ut, target_lang=out_lang, sauce_lang=sauce_lang)
                                          for ut in message.data["utterances"]]
        for key in self.translate_keys:
            if key in message.data:
                ut = message.data[key]
                message.data[key] = self.translate_utterance(ut, target_lang=out_lang, sauce_lang=sauce_lang)
        if self.translate_tags:
            for idx, token in enumerate(message.data["__tags__"]):
                message.data["__tags__"][idx] = self.translate_utterance(token.get("key", ""),
                                                                         target_lang=out_lang,
                                                                         sauce_lang=sauce_lang)
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
        utterance = self.translate_utterance(utterance, sauce_lang, out_lang)
        super().speak(utterance, *args, **kwargs)


class UniversalFallback(UniversalSkill, OVOSFallbackSkill):
    ''' Fallback Skill that auto translates input/output from any language '''

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
        super().register_fallback(handler, priority)
