import abc
import itertools
from os.path import exists
from threading import RLock
from typing import List, Tuple, Optional

from ovos_bus_client.message import Message, dig_for_message
from ovos_bus_client.util import get_mycroft_bus
from ovos_utils.log import LOG, log_deprecation


class _IntentMeta(abc.ABCMeta):
    def __instancecheck__(self, instance):
        check = super().__instancecheck__(instance)
        if not check:
            try:
                # backwards compat isinstancechecks
                from adapt.intent import Intent as _I
                check = isinstance(instance, _I)
            except ImportError:
                pass
        return check


class Intent(metaclass=_IntentMeta):
    def __init__(self, name="", requires=None, at_least_one=None, optional=None, excludes=None):
        """Create Intent object

        Args:
            name(str): Name for Intent
            requires(list): Entities that are required
            at_least_one(list): One of these Entities are required
            optional(list): Optional Entities used by the intent
        """
        self.name = name
        self.requires = requires or []
        self.at_least_one = at_least_one or []
        self.optional = optional or []
        self.excludes = excludes or []

    def validate(self, tags, confidence):
        """Using this method removes tags from the result of validate_with_tags

        Returns:
            intent(intent): Results from validate_with_tags
        """
        intent, tags = self.validate_with_tags(tags, confidence)
        return intent

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
        result = {'intent_type': self.name}
        intent_confidence = 0.0
        local_tags = tags[:]
        used_tags = []

        # Check excludes first
        for exclude_type in self.excludes:
            exclude_tag, _canonical_form, _tag_confidence = \
                self._find_first_tag(local_tags, exclude_type)
            if exclude_tag:
                result['confidence'] = 0.0
                return result, []

        for require_type, attribute_name in self.requires:
            required_tag, canonical_form, tag_confidence = \
                self._find_first_tag(local_tags, require_type)
            if not required_tag:
                result['confidence'] = 0.0
                return result, []

            result[attribute_name] = canonical_form
            if required_tag in local_tags:
                local_tags.remove(required_tag)
            used_tags.append(required_tag)
            intent_confidence += tag_confidence

        if len(self.at_least_one) > 0:
            best_resolution = self._resolve_one_of(local_tags, self.at_least_one)
            if not best_resolution:
                result['confidence'] = 0.0
                return result, []
            else:
                for key in best_resolution:
                    # TODO: at least one should support aliases
                    result[key] = best_resolution[key][0].get('key')
                    intent_confidence += 1.0 * best_resolution[key][0]['entities'][0].get('confidence', 1.0)
                used_tags.append(best_resolution[key][0])
                if best_resolution in local_tags:
                    local_tags.remove(best_resolution[key][0])

        for optional_type, attribute_name in self.optional:
            optional_tag, canonical_form, tag_confidence = \
                self._find_first_tag(local_tags, optional_type)
            if not optional_tag or attribute_name in result:
                continue
            result[attribute_name] = canonical_form
            if optional_tag in local_tags:
                local_tags.remove(optional_tag)
            used_tags.append(optional_tag)
            intent_confidence += tag_confidence

        total_confidence = (intent_confidence / len(tags) * confidence) \
            if tags else 0.0

        CLIENT_ENTITY_NAME = 'Client'  # TODO - ??? what is this magic string

        target_client, canonical_form, confidence = \
            self._find_first_tag(local_tags, CLIENT_ENTITY_NAME)

        result['target'] = target_client.get('key') if target_client else None
        result['confidence'] = total_confidence

        return result, used_tags

    @classmethod
    def _resolve_one_of(cls, tags, at_least_one):
        """Search through all combinations of at_least_one rules to find a
        combination that is covered by tags

        Args:
            tags(list): List of tags with Entities to search for Entities
            at_least_one(list): List of Entities to find in tags

        Returns:
            object:
            returns None if no match is found but returns any match as an object
        """
        for possible_resolution in itertools.product(*at_least_one):
            resolution = {}
            pr = possible_resolution[:]
            for entity_type in pr:
                last_end_index = -1
                if entity_type in resolution:
                    last_end_index = resolution[entity_type][-1].get('end_token')
                tag, value, c = cls._find_first_tag(tags, entity_type,
                                                    after_index=last_end_index)
                if not tag:
                    break
                else:
                    if entity_type not in resolution:
                        resolution[entity_type] = []
                    resolution[entity_type].append(tag)
            # Check if this is a valid resolution (all one_of rules matched)
            if len(resolution) == len(possible_resolution):
                return resolution

        return None

    @staticmethod
    def _find_first_tag(tags, entity_type, after_index=-1):
        """Searches tags for entity type after given index

        Args:
            tags(list): a list of tags with entity types to be compared to
             entity_type
            entity_type(str): This is he entity type to be looking for in tags
            after_index(int): the start token must be greater than this.

        Returns:
            ( tag, v, confidence ):
                tag(str): is the tag that matched
                v(str): ? the word that matched?
                confidence(float): is a measure of accuracy.  1 is full confidence
                    and 0 is none.
        """
        for tag in tags:
            for entity in tag.get('entities'):
                for v, t in entity.get('data'):
                    if t.lower() == entity_type.lower() and \
                            (tag.get('start_token', 0) > after_index or \
                             tag.get('from_context', False)):
                        return tag, v, entity.get('confidence')

        return None, None, None


class _IntentBuilderMeta(abc.ABCMeta):
    def __instancecheck__(self, instance):
        check = super().__instancecheck__(instance)
        if not check:
            try:
                # backwards compat isinstancechecks
                from adapt.intent import IntentBuilder as _IB
                check = isinstance(instance, _IB)
            except ImportError:
                pass
        return check


class IntentBuilder(metaclass=_IntentBuilderMeta):
    """
    IntentBuilder, used to construct intent parsers.

    Attributes:
        at_least_one(list): A list of Entities where one is required.
            These are separated into lists so you can have one of (A or B) and
            then require one of (D or F).
        requires(list): A list of Required Entities
        optional(list): A list of optional Entities
        excludes(list): A list of forbidden Entities
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
        self.excludes = []
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

    def exclude(self, entity_type):
        """
        The intent parser must not contain an entity of the provided type.

        Args:
            entity_type(str): an entity type

        Returns:
            self: to continue modifications.
        """
        self.excludes.append(entity_type)
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
                      self.at_least_one, self.optional,
                      self.excludes)


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
    intent_dict = message.data
    return Intent(intent_dict.get('name'),
                  intent_dict.get('requires'),
                  intent_dict.get('at_least_one'),
                  intent_dict.get('optional'),
                  intent_dict.get('excludes'))
