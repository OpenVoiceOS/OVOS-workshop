from abc import ABC

from ovos_config import Configuration

from ovos_bus_client import Message
from ovos_utils.events import get_handler_name
from ovos_utils.log import LOG
from ovos_workshop.resource_files import SkillResources
from ovos_workshop.skills.common_query_skill import CommonQuerySkill
from ovos_workshop.skills.fallback import FallbackSkillV2
from ovos_workshop.skills.ovos import OVOSSkill


class UniversalSkill(OVOSSkill):
    """
    Skill that auto translates input/output from any language

    This skill is designed to automatically translate input and output messages
    between different languages. The intent handlers are ensured to receive
    utterances in the skill's internal language, and they are expected to produce
    utterances in the same internal language.

    The `speak` method will always translate utterances from the internal language
    to the original query language (`self.lang`).

    NOTE: `self.lang` reflects the original query language, but received utterances
          are always in `self.internal_language`.
    """

    def __init__(self, internal_language: str = None,
                 translate_tags: bool = True,
                 autodetect: bool = False,
                 translate_keys: list = None,
                 *args, **kwargs):
        """
        Initialize the UniversalSkill.

        Parameters:
        - internal_language (str): The language in which the skill internally operates.
        - translate_tags (bool): Whether to translate the private __tags__ value (adapt entities).
        - autodetect (bool): If True, the skill will detect the language of the utterance
                            regardless of Session.lang.
        - translate_keys (list): default ["utterance", "utterances"]
                                Keys added here will have values translated in message.data.
        - *args, **kwargs: Additional arguments passed to the parent class constructor.

        Note:
        - If `internal_language` is not provided, it will be set to the language
          specified in the configuration.
        """
        super().__init__(*args, **kwargs)
        # the skill internally only works in this language
        self.internal_language = internal_language
        # __tags__ private value will be translated (adapt entities)
        self.translate_tags = translate_tags
        # keys added here will have values translated in message.data
        self.translate_keys = translate_keys or ["utterance", "utterances"]

        self.autodetect = autodetect
        if not self.internal_language:
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

    def detect_language(self, utterance: str):
        """
        Detect the language of the given utterance.

        Parameters:
        - utterance (str): The input text whose language needs to be detected.

        Returns:
        str: The detected language code.

        If an error occurs during language detection, it falls back to the language
        specified in `Session.lang`.

        Note:
        - The detected language is based on Session.lang if `self.autodetect` is False.
        - If `self.autodetect` is True, the language is detected regardless of Session.lang.
        - The detection is performed using the configured translator plugin.
        """
        try:
            return self.lang_detector.detect(utterance)
        except Exception as e:
            LOG.error(e)
            # self.lang to account for lang defined in message
            return self.lang.split("-")[0]

    def translate_utterance(self, text: str, target_lang: str, sauce_lang: str = None):
        """
        Translate the given text from the source language to the target language.

        Parameters:
        - text (str): The text to be translated.
        - target_lang (str): The target language code for translation.
        - sauce_lang (str, optional): The source language code. If not provided, it will be detected.

        Returns:
        str: The translated text.

        If the detected source language is the same as the target language, the input
        text is returned unchanged.

        Note:
        - If `self.autodetect` is True, the source language is automatically detected.
        - The translation is performed using the configured translator plugin.
        """
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

    def translate_message(self, message: Message):
        """
        Translate the content of the message to the skill's internal language.

        Parameters:
        - message (Message): The message object to be translated.

        Returns:
        - Message: The translated message.

        The translation process includes translating text, lists, and dictionaries
        based on the configured (per skill) translation keys.
        If enabled, it also translates tags (adapt keywords) in the message data.

        The original and translated data are stored in the `translation_data` attribute
        of the message context.
        """
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
        """
        Create a universal intent handler that translates the message before invoking
        the original handler.

        Parameters:
        - handler (callable): The original intent handler function.

        Returns:
        - callable: A new intent handler function with translation logic.

        The created intent handler takes a message as input, translates its content
        to the skill's internal language using the `translate_message` method, and
        then invokes the original handler with the translated message.

        Manual usage Example:
        ```python
        my_handler = self.create_universal_handler(original_handler_function)
        self.add_event("my_event", my_handler)
        ```

        NOTE: this method should not be used in skill intents,
          that is done automatically for self.register_intent!

          Use only with self.add_event

        """

        def universal_intent_handler(message):
            message = self.translate_message(message)
            LOG.info(get_handler_name(handler))
            handler(message)

        return universal_intent_handler

    def register_intent(self, intent_parser, handler):
        """
        Register an intent with a universal intent handler.

        Parameters:
        - intent_parser (str or IntentParser): The intent parser to register.
        - handler (callable): The original intent handler function.

        This method registers the intent with a universal intent handler, which
        translates the message before invoking the original handler.

        Example:
        ```python
        self.register_intent("my_intent", my_handler_function)
        ```

        See Also:
        - `create_universal_handler` method for creating universal intent handlers.
        """
        handler = self.create_universal_handler(handler)
        super().register_intent(intent_parser, handler)

    def register_intent_file(self, intent_file, handler):
        """
         Register intents from a file with a universal intent handler.

         Parameters:
         - intent_file (str): The path to the intent file.
         - handler (callable): The original intent handler function.

         This method registers intents from a file with a universal intent handler,
         which translates the message before invoking the original handler.

         Example:
         ```python
         self.register_intent_file("my_intents.intent", my_handler_function)
         ```

         See Also:
         - `create_universal_handler` method for creating universal intent handlers.
         """
        handler = self.create_universal_handler(handler)
        super().register_intent_file(intent_file, handler)

    def speak(self, utterance: str, *args, **kwargs):
        """
        Speak the given utterance, translating it if needed.

        Parameters:
        - utterance (str): The text to be spoken.
        - *args, **kwargs: Additional arguments passed to the parent class `speak` method.

        If the output language (`self.lang` / Session.lang) is different from the skill's internal
        language (`self.internal_language`), or autodetection is enabled, the utterance
        is translated before being spoken. The translation data is stored in the meta
        information.

        Example:
        ```python
        self.speak("Hello, how are you?")
        ```

        See Also:
        - `translate_utterance` method for translation logic.
        - `create_universal_handler` method for creating universal intent handlers.
        """
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
    Fallback Skill that auto translates input/output from any language.

    Fallback handlers are ensured to receive utterances and expected to produce
    responses in `self.internal_language`.

    `self.speak` will always translate utterances from
    `self.internal_lang` to `self.lang`.

    NOTE: `self.lang` reflects the original query language,
          but received utterances are always in `self.internal_language`.
    """

    def create_universal_fallback_handler(self, handler):
        """
        Create a universal fallback handler that translates the message before invoking
        the original fallback handler.

        Parameters:
        - handler (callable): The original fallback handler function.

        Returns:
        - callable: A new fallback handler function with translation logic.

        The created fallback handler takes a message as input, translates its content
        to the skill's internal language using the `translate_message` method, and
        then invokes the original handler with the translated message.
        If the fallback matched the skill is activated with the converse system
        """

        def universal_fallback_handler(message):
            # auto_Translate input
            message = self.translate_message(message)
            LOG.info(get_handler_name(handler))
            success = handler(self, message)
            if success:
                self.activate()
            return success

        return universal_fallback_handler

    def register_fallback(self, handler, priority: int):
        """
        Register a fallback handler with a specified priority.

        Parameters:
        - handler (callable): The original fallback handler function.
        - priority (int): The priority of the fallback handler.

        This method registers the fallback handler with a universal fallback handler,
        which translates the message before invoking the original handler.

        Example:
        ```python
        self.register_fallback(my_fallback_handler_function, priority=5)
        ```

        See Also:
        - `create_universal_fallback_handler` method for creating universal fallback handlers.
        """
        handler = self.create_universal_fallback_handler(handler)
        FallbackSkillV2.register_fallback(self, handler, priority)


class UniversalCommonQuerySkill(UniversalSkill, CommonQuerySkill, ABC):
    """
    CommonQuerySkill that auto translates input/output from any language.

    `CQS_match_query_phrase` and `CQS_action` are ensured to receive phrases in
    `self.internal_language`.

    `CQS_match_query_phrase` is assumed to return a response in `self.internal_language`,
    and it will be translated back before speaking.

    `self.speak` will always translate utterances from
    `self.internal_lang` to `self.lang`.

    NOTE: `self.lang` reflects the original query language,
          but received utterances are always in `self.internal_language`.
    """

    def __handle_query_action(self, message: Message):
        """
        Handle the common query action, translating the message if needed.

        Parameters:
        - message (Message): The message containing the query action.

        This method translates the query phrase to the internal language if the
        output language (`self.lang` / Session.lang) is different or autodetection is enabled.
        Then it invokes the parent method `__handle_query_action`.

        This method is internal and should not be called directly.
        """
        if message.data["skill_id"] != self.skill_id:
            # Not for this skill!
            return
        if self.lang != self.internal_language or self.autodetect:
            message.data["phrase"] = self.translate_utterance(message.data["phrase"],
                                                              sauce_lang=self.lang,
                                                              target_lang=self.internal_language)

        super().__handle_query_action(message)

    def __get_cq(self, search_phrase: str):
        """
         Get a common query result for the given search phrase.

         Parameters:
         - search_phrase (str): The search phrase.

         Returns:
         - tuple or None: A tuple representing the common query result, or None if not found.

         This method converts the input into the internal language if needed, gets
         the common query result, and converts the response back into the source language.

         This method is internal and should not be called directly.
         """
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

    def remove_noise(self, phrase: str, lang: str = None):
        """
        Remove noise to produce the essence of the question.

        Parameters:
        - phrase (str): The input phrase.
        - lang (str, optional): ignored, just for api compat

        Returns:
        - str: The cleaned phrase.

        This method removes noise from the input phrase to extract the essence of the question.
        The method uses the `self.internal_language` as the default language.
        """
        return super().remove_noise(phrase, self.internal_language)
