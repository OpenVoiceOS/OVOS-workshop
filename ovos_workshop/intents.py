from os.path import exists
from threading import RLock
from typing import List, Tuple, Optional

from ovos_utils.log import LOG, log_deprecation
from ovos_utils.messagebus import get_mycroft_bus
from ovos_bus_client.message import Message, dig_for_message

try:
    from adapt.intent import IntentBuilder, Intent
except ImportError:
    # adapt is optional

    class Intent:
        def __init__(self, name, requires, at_least_one, optional):
            """Create Intent object
            Args:
                name(str): Name for Intent
                requires(list): Entities that are required
                at_least_one(list): One of these Entities are required
                optional(list): Optional Entities used by the intent
            """
            self.name = name
            self.requires = requires
            self.at_least_one = at_least_one
            self.optional = optional

        def validate(self, tags, confidence):
            """Using this method removes tags from the result of validate_with_tags
            Returns:
                intent(intent): Results from validate_with_tags
            """
            raise NotImplementedError("please install adapt-parser")

        def validate_with_tags(self, tags, confidence):
            """Validate whether tags has required entites for this intent to fire
            Args:
                tags(list): Tags and Entities used for validation
                confidence(float): The weight associate to the parse result,
                    as indicated by the parser. This is influenced by a parser
                    that uses edit distance or context.
            Returns:
                intent, tags: Returns intent and tags used by the intent on
                    failure to meat required entities then returns intent with
                    confidence
                    of 0.0 and an empty list for tags.
            """
            raise NotImplementedError("please install adapt-parser")


    class IntentBuilder:
        """
        IntentBuilder, used to construct intent parsers.
        Attributes:
            at_least_one(list): A list of Entities where one is required.
                These are separated into lists so you can have one of (A or B) and
                then require one of (D or F).
            requires(list): A list of Required Entities
            optional(list): A list of optional Entities
            name(str): Name of intent
        Notes:
            This is designed to allow construction of intents in one line.
        Example:
            IntentBuilder("Intent")\
                .requires("A")\
                .one_of("C","D")\
                .optional("G").build()
        """

        def __init__(self, intent_name):
            """
            Constructor
            Args:
                intent_name(str): the name of the intents that this parser
                parses/validates
            """
            self.at_least_one = []
            self.requires = []
            self.optional = []
            self.name = intent_name

        def one_of(self, *args):
            """
            The intent parser should require one of the provided entity types to
            validate this clause.
            Args:
                args(args): *args notation list of entity names
            Returns:
                self: to continue modifications.
            """
            self.at_least_one.append(args)
            return self

        def require(self, entity_type, attribute_name=None):
            """
            The intent parser should require an entity of the provided type.
            Args:
                entity_type(str): an entity type
                attribute_name(str): the name of the attribute on the parsed intent.
                Defaults to match entity_type.
            Returns:
                self: to continue modifications.
            """
            if not attribute_name:
                attribute_name = entity_type
            self.requires += [(entity_type, attribute_name)]
            return self

        def optionally(self, entity_type, attribute_name=None):
            """
            Parsed intents from this parser can optionally include an entity of the
             provided type.
            Args:
                entity_type(str): an entity type
                attribute_name(str): the name of the attribute on the parsed intent.
                Defaults to match entity_type.
            Returns:
                self: to continue modifications.
            """
            if not attribute_name:
                attribute_name = entity_type
            self.optional += [(entity_type, attribute_name)]
            return self

        def build(self):
            """
            Constructs an intent from the builder's specifications.
            :return: an Intent instance.
            """
            return Intent(self.name, self.requires,
                          self.at_least_one, self.optional)


def to_alnum(skill_id: str) -> str:
    """
    Convert a skill id to only alphanumeric characters
     Non-alphanumeric characters are converted to "_"

    Args:
        skill_id (str): identifier to be converted
    Returns:
        (str) String of letters
    """
    return ''.join(c if c.isalnum() else '_' for c in str(skill_id))


def munge_regex(regex: str, skill_id: str) -> str:
    """
    Insert skill id as letters into match groups.

    Args:
        regex (str): regex string
        skill_id (str): skill identifier
    Returns:
        (str) munged regex
    """
    base = '(?P<' + to_alnum(skill_id)
    return base.join(regex.split('(?P<'))


def munge_intent_parser(intent_parser, name, skill_id):
    """
    Rename intent keywords to make them skill exclusive
    This gives the intent parser an exclusive name in the
    format <skill_id>:<name>.  The keywords are given unique
    names in the format <Skill id as letters><Intent name>.

    The function will not munge instances that's already been
    munged

    Args:
        intent_parser: (IntentParser) object to update
        name: (str) Skill name
        skill_id: (int) skill identifier
    """
    # Munge parser name
    if not name.startswith(str(skill_id) + ':'):
        intent_parser.name = str(skill_id) + ':' + name
    else:
        intent_parser.name = name

    # Munge keywords
    skill_id = to_alnum(skill_id)
    # Munge required keyword
    reqs = []
    for i in intent_parser.requires:
        if not i[0].startswith(skill_id):
            kw = (skill_id + i[0], skill_id + i[0])
            reqs.append(kw)
        else:
            reqs.append(i)
    intent_parser.requires = reqs

    # Munge optional keywords
    opts = []
    for i in intent_parser.optional:
        if not i[0].startswith(skill_id):
            kw = (skill_id + i[0], skill_id + i[0])
            opts.append(kw)
        else:
            opts.append(i)
    intent_parser.optional = opts

    # Munge at_least_one keywords
    at_least_one = []
    for i in intent_parser.at_least_one:
        element = [skill_id + e.replace(skill_id, '') for e in i]
        at_least_one.append(tuple(element))
    intent_parser.at_least_one = at_least_one


class IntentServiceInterface:
    """
    Interface to communicate with the Mycroft intent service.

    This class wraps the messagebus interface of the intent service allowing
    for easier interaction with the service. It wraps both the Adapt and
    Padatious parts of the intent services.
    """

    def __init__(self, bus=None):
        self._bus = bus
        self.skill_id = self.__class__.__name__
        # TODO: Consider using properties with setters to prevent duplicates
        self.registered_intents: List[Tuple[str, object]] = []
        self.detached_intents: List[Tuple[str, object]] = []
        self._iterator_lock = RLock()

    @property
    def intent_names(self) -> List[str]:
        """
        Get a list of intent names (both registered and disabled).
        """
        return [a[0] for a in self.registered_intents + self.detached_intents]

    @property
    def bus(self):
        if not self._bus:
            raise RuntimeError("bus not set. call `set_bus()` before trying to"
                               "interact with the Messagebus")
        return self._bus

    @bus.setter
    def bus(self, val):
        self.set_bus(val)

    def set_bus(self, bus=None):
        self._bus = bus or get_mycroft_bus()

    def set_id(self, skill_id: str):
        self.skill_id = skill_id

    def register_adapt_keyword(self, vocab_type: str, entity: str,
                               aliases: Optional[List[str]] = None,
                               lang: str = None):
        """
        Send a message to the intent service to add an Adapt keyword.
        @param vocab_type: Keyword reference (file basename)
        @param entity: Primary keyword value
        @param aliases: List of alternative keyword values
        @param lang: BCP-47 language code of entity and aliases
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id

        # TODO 22.02: Remove compatibility data
        aliases = aliases or []
        entity_data = {'entity_value': entity,
                       'entity_type': vocab_type,
                       'lang': lang}
        compatibility_data = {'start': entity, 'end': vocab_type}

        self.bus.emit(msg.forward("register_vocab",
                                  {**entity_data, **compatibility_data}))
        for alias in aliases:
            alias_data = {
                'entity_value': alias,
                'entity_type': vocab_type,
                'alias_of': entity,
                'lang': lang}
            compatibility_data = {'start': alias, 'end': vocab_type}
            self.bus.emit(msg.forward("register_vocab",
                                      {**alias_data, **compatibility_data}))

    def register_adapt_regex(self, regex: str, lang: str = None):
        """
        Register a regex string with the intent service.
        @param regex: Regex to be registered; Adapt extracts keyword references
            from named match group.
        @param lang: BCP-47 language code of regex
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward("register_vocab",
                                  {'regex': regex, 'lang': lang}))

    def register_adapt_intent(self, name: str, intent_parser: object):
        """
        Register an Adapt intent parser object. Serializes the intent_parser
        and sends it over the messagebus to registered.
        @param name: string intent name (without skill_id prefix)
        @param intent_parser: Adapt Intent object
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward("register_intent", intent_parser.__dict__))
        self.registered_intents.append((name, intent_parser))
        self.detached_intents = [detached for detached in self.detached_intents
                                 if detached[0] != name]

    def detach_intent(self, intent_name: str):
        """
        DEPRECATED: Use `remove_intent` instead, all other methods from this
        class expect intent_name; this was the weird one expecting the internal
        munged intent_name with skill_id.
        """
        name = intent_name.split(':')[1]
        log_deprecation(f"Update to `self.remove_intent({name})",
                        "0.1.0")
        self.remove_intent(name)

    def remove_intent(self, intent_name: str):
        """
        Remove an intent from the intent service. The intent is saved in the
        list of detached intents for use when re-enabling an intent. A
        `detach_intent` Message is emitted for the intent service to handle.
        @param intent_name: Registered intent to remove/detach (no skill_id)
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        if intent_name in self.intent_names:
            # TODO: This will create duplicates of already detached intents
            LOG.info(f"Detaching intent: {intent_name}")
            self.detached_intents.append((intent_name,
                                          self.get_intent(intent_name)))
            self.registered_intents = [pair for pair in self.registered_intents
                                       if pair[0] != intent_name]
        self.bus.emit(msg.forward("detach_intent",
                                  {"intent_name":
                                       f"{self.skill_id}:{intent_name}"}))

    def intent_is_detached(self, intent_name: str) -> bool:
        """
        Determine if an intent is detached.
        @param intent_name: String intent reference to check (without skill_id)
        @return: True if intent is in detached_intents, else False.
        """
        is_detached = False
        with self._iterator_lock:
            for (name, _) in self.detached_intents:
                if name == intent_name:
                    is_detached = True
                    break
        return is_detached

    def set_adapt_context(self, context: str, word: str, origin: str):
        """
        Set an Adapt context.
        @param context: context keyword name to add/update
        @param word: word to register (context keyword value)
        @param origin: original origin of the context (for cross context)
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward('add_context',
                                  {'context': context, 'word': word,
                                   'origin': origin}))

    def remove_adapt_context(self, context: str):
        """
        Remove an Adapt context.
        @param context: context keyword name to remove
        """
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward('remove_context', {'context': context}))

    def register_padatious_intent(self, intent_name: str, filename: str,
                                  lang: str):
        """
        Register a Padatious intent file with the intent service.
        @param intent_name: Unique intent identifier
            (usually `skill_id`:`filename`)
        @param filename: Absolute file path to entity file
        @param lang: BCP-47 language code of registered intent
        """
        if not isinstance(filename, str):
            raise ValueError('Filename path must be a string')
        if not exists(filename):
            raise FileNotFoundError(f'Unable to find "{filename}"')
        with open(filename) as f:
            samples = [_ for _ in f.read().split("\n") if _
                       and not _.startswith("#")]
        data = {'file_name': filename,
                "samples": samples,
                'name': intent_name,
                'lang': lang}
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward("padatious:register_intent", data))
        self.registered_intents.append((intent_name.split(':')[-1], data))

    def register_padatious_entity(self, entity_name: str, filename: str,
                                  lang: str):
        """
        Register a Padatious entity file with the intent service.
        @param entity_name: Unique entity identifier
            (usually `skill_id`:`filename`)
        @param filename: Absolute file path to entity file
        @param lang: BCP-47 language code of registered intent
        """
        if not isinstance(filename, str):
            raise ValueError('Filename path must be a string')
        if not exists(filename):
            raise FileNotFoundError('Unable to find "{}"'.format(filename))
        with open(filename) as f:
            samples = [_ for _ in f.read().split("\n") if _
                       and not _.startswith("#")]
        msg = dig_for_message() or Message("")
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg.forward('padatious:register_entity',
                                  {'file_name': filename,
                                   "samples": samples,
                                   'name': entity_name,
                                   'lang': lang}))

    def get_intent_names(self):
        log_deprecation("Reference `intent_names` directly", "0.1.0")
        return self.intent_names

    def detach_all(self):
        """
        Detach all intents associated with this interface and remove all
        internal references to intents and handlers.
        """
        for name in self.intent_names:
            self.remove_intent(name)
        if self.registered_intents:
            LOG.error(f"Expected an empty list; got: {self.registered_intents}")
            self.registered_intents = []
        self.detached_intents = []  # Explicitly remove all intent references

    def get_intent(self, intent_name: str) -> Optional[object]:
        """
        Get an intent object by name. This will find both enabled and disabled
        intents.
        @param intent_name: name of intent to find (without skill_id)
        @return: intent object if found, else None
        """
        to_return = None
        with self._iterator_lock:
            for name, intent in self.registered_intents:
                if name == intent_name:
                    to_return = intent
                    break
        if to_return is None:
            with self._iterator_lock:
                for name, intent in self.detached_intents:
                    if name == intent_name:
                        to_return = intent
                        break
        return to_return

    def __iter__(self):
        """Iterator over the registered intents.

        Returns an iterator returning name-handler pairs of the registered
        intent handlers.
        """
        return iter(self.registered_intents)

    def __contains__(self, val):
        """
        Checks if an intent name has been registered.
        """
        return val in [i[0] for i in self.registered_intents]


def open_intent_envelope(message):
    """
    Convert dictionary received over messagebus to Intent.
    """
    # TODO can this method be fully removed from ovos_utils ?
    from adapt.intent import Intent

    intent_dict = message.data
    return Intent(intent_dict.get('name'),
                  intent_dict.get('requires'),
                  intent_dict.get('at_least_one'),
                  intent_dict.get('optional'))
