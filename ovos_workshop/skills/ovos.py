import time
from copy import deepcopy
from os.path import join, dirname, isfile

from ovos_utils import camel_case_split, get_handler_name
# ensure mycroft can be imported
from ovos_utils import ensure_mycroft_import
from ovos_utils.log import LOG
from ovos_utils.messagebus import Message
from ovos_utils.parse import match_one
from ovos_utils.skills.settings import PrivateSettings
from ovos_utils import resolve_ovos_resource_file

ensure_mycroft_import()
from adapt.intent import Intent, IntentBuilder
from mycroft import dialog
from mycroft_bus_client.message import dig_for_message
from mycroft.skills.mycroft_skill.event_container import create_wrapper
from mycroft.skills.settings import save_settings
from mycroft.skills.mycroft_skill.mycroft_skill import get_non_properties
from ovos_workshop.patches.base_skill import MycroftSkill, FallbackSkill
from ovos_workshop.skills.decorators.killable import killable_event, \
    AbortEvent, AbortQuestion
from ovos_workshop.skills.layers import IntentLayers


class OVOSSkill(MycroftSkill):
    """
    New features:
        - all patches for MycroftSkill class
        - self.private_settings
        - killable intents
        - IntentLayers
    """

    def __init__(self, *args, **kwargs):
        super(OVOSSkill, self).__init__(*args, **kwargs)
        self.private_settings = None
        self._threads = []
        self._original_converse = self.converse
        self.intent_layers = IntentLayers()

    def _init_converse_intents(self):
        # conversational intents, executed instead of self.converse
        # only available if skill is active!

        # support both padatious and padaos
        # TODO pluginify intents
        try:
            from padatious import IntentContainer
            intent_cache = join(self.file_system.path, "intent_cache")
            self.intent_parser = IntentContainer(intent_cache)
        except:
            try:
                from padaos import IntentContainer
                self.intent_parser = IntentContainer()
            except:
                self.intent_parser = None
        if "min_intent_conf" not in self.settings:
            self.settings["min_intent_conf"] = 0.6
        self.converse_intents = {}

    def register_converse_intent(self, intent_file, handler):
        """ converse padatious intents """
        name = f'{self.skill_id}.converse:{intent_file}'
        filename = self.find_resource(intent_file, 'locale') or \
                   self.find_resource(intent_file, 'vocab') or \
                   self.find_resource(intent_file, 'dialog')
        if not filename:
            raise FileNotFoundError(f'Unable to find "{intent_file}"')
        with open(filename) as f:
            samples = [l.strip() for l in f.read().split("\n") if l]
        if self.intent_parser:
            self.intent_parser.add_intent(name, samples)
        self.converse_intents[name] = samples
        self.add_event(name, handler)

    def _train_converse_intents(self):
        """ train internal padatious/padaos parser """
        if self.intent_parser:
            if hasattr(self.intent_parser, "train"):
                self.intent_parser.train(single_thread=True)

    def _handle_converse_intents(self, message=None):
        """ called before converse method
        this gives active skills a chance to parse their own intents and
        consume the utterance, see conversational_intent decorator for usage
        """
        message = message or dig_for_message()
        best_score = 0
        for utt in message.data['utterances']:
            if self.intent_parser:
                match = self.intent_parser.calc_intent(utt)
                if match and match.conf > best_score:
                    best_match = match
                    best_score = match.conf
                    message = message.forward(best_match.name,
                                              best_match.matches)
            else:
                # fuzzy match
                for intent_name, samples in self.converse_intents.items():
                    _, score = match_one(utt, samples)
                    if score > best_score:
                        best_score = score
                        message = message.forward(intent_name)

        if not message or best_score < self.settings["min_intent_conf"]:
            return False

        # send intent event
        self.bus.emit(message)
        return True

    def converse(self, message=None):
        return self._handle_converse_intents(message)

    def bind(self, bus):
        super().bind(bus)
        if bus:
            # here to ensure self.skill_id is populated
            self.private_settings = PrivateSettings(self.skill_id)
            self.intent_layers.bind(self)
            self._init_converse_intents()

    def voc_match(self, *args, **kwargs):
        try:
            return super().voc_match(*args, **kwargs)
        except FileNotFoundError:
            return False

    def _register_decorated(self):
        """Register all intent handlers that are decorated with an intent.

        Looks for all functions that have been marked by a decorator
        and read the intent data from them.  The intent handlers aren't the
        only decorators used.  Skip properties as calling getattr on them
        executes the code which may have unintended side-effects
        """
        super()._register_decorated()
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'intent_layers'):
                for layer_name, intent_files in \
                        getattr(method, 'intent_layers').items():
                    self.register_intent_layer(layer_name, intent_files)

            # TODO support for multiple converse handlers (?)
            if hasattr(method, 'converse'):
                self.converse = method

            if hasattr(method, 'converse_intents'):
                for intent_file in getattr(method, 'converse_intents'):
                    self.register_converse_intent(intent_file, method)

    def register_intent_layer(self, layer_name, intent_list):
        for intent_file in intent_list:
            if isinstance(intent_file, IntentBuilder):
                intent = intent_file.build()
                name = intent.name
            elif isinstance(intent_file, Intent):
                name = intent_file.name
            else:
                name = intent_file
            self.intent_layers.update_layer(layer_name, [name])

    # this method can probably use a better refactor, we are only changing one
    # of the internal callbacks
    def add_event(self, name, handler, handler_info=None, once=False):
        """Create event handler for executing intent or other event.

        Arguments:
            name (string): IntentParser name
            handler (func): Method to call
            handler_info (string): Base message when reporting skill event
                                   handler status on messagebus.
            once (bool, optional): Event handler will be removed after it has
                                   been run once.
        """
        skill_data = {'name': get_handler_name(handler)}

        def on_error(e):
            """Speak and log the error."""
            if not isinstance(e, AbortEvent):
                # Convert "MyFancySkill" to "My Fancy Skill" for speaking
                handler_name = camel_case_split(self.name)
                msg_data = {'skill': handler_name}
                msg = dialog.get('skill.error', self.lang, msg_data)
                self.speak(msg)
                LOG.exception(msg)
            else:
                LOG.info("Skill execution aborted")
            # append exception information in message
            skill_data['exception'] = repr(e)

        def on_start(message):
            """Indicate that the skill handler is starting."""
            if handler_info:
                # Indicate that the skill handler is starting if requested
                msg_type = handler_info + '.start'
                message.context["skill_id"] = self.skill_id
                self.bus.emit(message.forward(msg_type, skill_data))

        def on_end(message):
            """Store settings and indicate that the skill handler has completed
            """
            if self.settings != self._initial_settings:
                try:  # ovos-core
                    self.settings.store()
                except:  # mycroft-core
                    save_settings(self.settings_write_path, self.settings)
                self._initial_settings = dict(self.settings)
            if handler_info:
                msg_type = handler_info + '.complete'
                message.context["skill_id"] = self.skill_id
                self.bus.emit(message.forward(msg_type, skill_data))

        wrapper = create_wrapper(handler, self.skill_id,
                                 on_start, on_end, on_error)
        return self.events.add(name, wrapper, once)

    def __handle_stop(self, _):
        self.bus.emit(Message(self.skill_id + ".stop",
                              context={"skill_id": self.skill_id}))
        super().__handle_stop(_)

    def _find_resource(self, res_name, lang, res_dirname=None):
        """Finds a resource by name, lang and dir
        """
        res = super()._find_resource(res_name, lang, res_dirname)
        if not res:
            # override to look for bundled pages
            res = resolve_ovos_resource_file(join('text', lang, res_name)) or \
                   resolve_ovos_resource_file(res_name)
        return res

    # abort get_response gracefully
    def _wait_response(self, is_cancel, validator, on_fail, num_retries):
        """Loop until a valid response is received from the user or the retry
        limit is reached.

        Arguments:
            is_cancel (callable): function checking cancel criteria
            validator (callbale): function checking for a valid response
            on_fail (callable): function handling retries

        """
        self._response = False
        self._real_wait_response(is_cancel, validator, on_fail, num_retries)
        while self._response is False:
            time.sleep(0.1)
        return self._response

    def __get_response(self):
        """Helper to get a reponse from the user

        Returns:
            str: user's response or None on a timeout
        """

        def converse(utterances, lang=None):
            converse.response = utterances[0] if utterances else None
            converse.finished = True
            return True

        # install a temporary conversation handler
        self.make_active()
        converse.finished = False
        converse.response = None
        self.converse = converse

        # 10 for listener, 5 for SST, then timeout
        # NOTE a threading event is not used otherwise we can't raise the
        # AbortEvent exception to kill the thread
        start = time.time()
        while time.time() - start <= 15 and not converse.finished:
            time.sleep(0.1)
            if self._response is not False:
                if self._response is None:
                    # aborted externally (if None)
                    self.log.debug("get_response aborted")
                converse.finished = True
                converse.response = self._response  # external override
        self.converse = self._original_converse
        return converse.response

    def _handle_killed_wait_response(self):
        self._response = None
        self.converse = self._original_converse

    @killable_event("mycroft.skills.abort_question", exc=AbortQuestion,
                    callback=_handle_killed_wait_response, react_to_stop=True)
    def _real_wait_response(self, is_cancel, validator, on_fail, num_retries):
        """Loop until a valid response is received from the user or the retry
        limit is reached.

        Arguments:
            is_cancel (callable): function checking cancel criteria
            validator (callbale): function checking for a valid response
            on_fail (callable): function handling retries

        """
        num_fails = 0
        while True:
            if self._response is not False:
                # usually None when aborted externally
                # also allows overriding returned result from other events
                return self._response

            response = self.__get_response()

            if response is None:
                # if nothing said, prompt one more time
                num_none_fails = 1 if num_retries < 0 else num_retries
                if num_fails >= num_none_fails:
                    self._response = None
                    return
            else:
                if validator(response):
                    self._response = response
                    return

                # catch user saying 'cancel'
                if is_cancel(response):
                    self._response = None
                    return

            num_fails += 1
            if 0 < num_retries < num_fails or self._response is not False:
                self._response = None
                return

            line = on_fail(response)
            if line:
                self.speak(line, expect_response=True)
            else:
                self.bus.emit(Message('mycroft.mic.listen',
                                      context={"skill_id": self.skill_id}))


class OVOSFallbackSkill(FallbackSkill, OVOSSkill):
    """ monkey patched mycroft fallback skill """

    def register_decorated(self):
        """Register all intent handlers that are decorated with an intent.

        Looks for all functions that have been marked by a decorator
        and read the intent data from them.  The intent handlers aren't the
        only decorators used.  Skip properties as calling getattr on them
        executes the code which may have unintended side-effects
        """
        super().register_decorated()
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'fallback_priority'):
                self.register_fallback(method, method.fallback_priority)
