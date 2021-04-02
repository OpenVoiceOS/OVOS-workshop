import re
from os.path import join, exists
import os
from itertools import chain
from ovos_utils.lang import get_language_dir
from ovos_utils.intents import ConverseTracker
from ovos_utils.log import LOG

# ensure mycroft can be imported
from ovos_utils import ensure_mycroft_import
ensure_mycroft_import()

from mycroft.skills.mycroft_skill import MycroftSkill as _MycroftSkill
from mycroft.skills.fallback_skill import FallbackSkill as _FallbackSkill
from mycroft.skills.skill_data import read_vocab_file, load_vocabulary, \
    load_regex
from mycroft.dialog import load_dialogs
from mycroft.util import resolve_resource_file
from ovos_workshop.patches.skill_gui import SkillGUI
from ovos_workshop.utils import resolve_ovos_resource_file


def get_non_properties(obj):
    """Get attibutes that are not properties from object.

    Will return members of object class along with bases down to MycroftSkill.

    Arguments:
        obj:    object to scan

    Returns:
        Set of attributes that are not a property.
    """

    def check_class(cls):
        """Find all non-properties in a class."""
        # Current class
        d = cls.__dict__
        np = [k for k in d if not isinstance(d[k], property)]
        # Recurse through base classes excluding MycroftSkill and object
        for b in [b for b in cls.__bases__ if b not in (object, MycroftSkill)]:
            np += check_class(b)
        return np

    return set(check_class(obj.__class__))


class MycroftSkill(_MycroftSkill):
    monkey_patched = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gui = SkillGUI(self)  # pull/2683

    # https://github.com/MycroftAI/mycroft-core/pull/1335
    def init_dialog(self, root_directory):
        # If "<skill>/dialog/<lang>" exists, load from there.  Otherwise
        # load dialog from "<skill>/locale/<lang>"
        dialog_dir = get_language_dir(join(root_directory, 'dialog'),
                                      self.lang)
        locale_dir = get_language_dir(join(root_directory, 'locale'),
                                      self.lang)
        if exists(dialog_dir):
            self.dialog_renderer = load_dialogs(dialog_dir)
        elif exists(locale_dir):
            self.dialog_renderer = load_dialogs(locale_dir)
        else:
            LOG.debug('No dialog loaded')

    def load_vocab_files(self, root_directory):
        """ Load vocab files found under root_directory.

        Arguments:
            root_directory (str): root folder to use when loading files
        """
        keywords = []
        vocab_dir = get_language_dir(join(root_directory, 'vocab'),
                                     self.lang)
        locale_dir = get_language_dir(join(root_directory, 'locale'),
                                      self.lang)
        if exists(vocab_dir):
            keywords = load_vocabulary(vocab_dir, self.skill_id)
        elif exists(locale_dir):
            keywords = load_vocabulary(locale_dir, self.skill_id)
        else:
            LOG.debug('No vocab loaded')

        # For each found intent register the default along with any aliases
        for vocab_type in keywords:
            for line in keywords[vocab_type]:
                entity = line[0]
                aliases = line[1:]
                self.intent_service.register_adapt_keyword(vocab_type,
                                                           entity,
                                                           aliases)

    def load_regex_files(self, root_directory):
        """ Load regex files found under the skill directory.

        Arguments:
            root_directory (str): root folder to use when loading files
        """
        regexes = []
        regex_dir = get_language_dir(join(root_directory, 'regex'),
                                     self.lang)
        locale_dir = get_language_dir(join(root_directory, 'locale'),
                                      self.lang)
        if exists(regex_dir):
            regexes = load_regex(regex_dir, self.skill_id)
        elif exists(locale_dir):
            regexes = load_regex(locale_dir, self.skill_id)

        for regex in regexes:
            self.intent_service.register_adapt_regex(regex)

    def _find_resource(self, res_name, lang, res_dirname=None):
        """Finds a resource by name, lang and dir
        """
        if res_dirname:
            # Try the old directory (dialog/vocab/regex)
            root_path = get_language_dir(join(self.root_dir, res_dirname),
                                         lang)
            path = join(root_path, res_name)
            if exists(path):
                return path

            # Try old-style non-translated resource
            path = join(self.root_dir, res_dirname, res_name)
            if exists(path):
                return path

        # New scheme:  search for res_name under the 'locale' folder
        root_path = get_language_dir(join(self.root_dir, 'locale'), lang)
        for path, _, files in os.walk(root_path):
            if res_name in files:
                return join(path, res_name)

        # Not found
        return None

    # https://github.com/MycroftAI/mycroft-core/pull/1468
    def _deactivate_skill(self, message):
        skill_id = message.data.get("skill_id")
        if skill_id == self.skill_id:
            self.handle_skill_deactivated(message)

    def handle_skill_deactivated(self, message=None):
        """
        Invoked when the skill is removed from active skill list
        """
        pass

    # https://github.com/MycroftAI/mycroft-core/pull/1468
    def bind(self, bus):
        if bus and not isinstance(self.gui, SkillGUI):
            # needs to be available before call to self.bind, if a skill is
            # initialized with the bus argument it will miss the monkey-patch
            # AFAIK this never happens in mycroft-core but i want the patch
            # to work in non standard use cases
            self.gui = SkillGUI(self)  # pull/2683
        super().bind(bus)
        if bus:
            ConverseTracker.connect_bus(self.bus)  # pull/1468
            self.add_event("converse.skill.deactivated",
                           self._deactivate_skill)

    # TODO PR not yet made
    def remove_voc(self, utt, voc_filename, lang=None):
        """ removes any entry in .voc file from the utterance """
        lang = lang or self.lang
        cache_key = lang + voc_filename

        if cache_key not in self.voc_match_cache:
            self.voc_match(utt, voc_filename, lang)

        if utt:
            # Check for matches against complete words
            for i in self.voc_match_cache.get(cache_key) or []:
                # Substitute only whole words matching the token
                utt = re.sub(r'\b' + i + r"\b", "", utt)

        return utt


class FallbackSkill(MycroftSkill, _FallbackSkill):
    """ """
