import abc
from typing import Optional, Dict, Iterable

from ovos_bus_client.message import Message
from ovos_bus_client.util import get_message_lang
from ovos_utils.ocp import MediaType, MediaEntry, PlaybackType, Playlist
from ovos_utils.parse import match_one, MatchStrategy

from ovos_workshop.decorators import ocp_featured_media, ocp_search
from ovos_workshop.skills.common_play import OVOSCommonPlaybackSkill


class OVOSGameSkill(OVOSCommonPlaybackSkill):
    """ To integrate with the OpenVoiceOS Common Playback framework

    "play" intent is shared with media and managed by OCP pipeline

    The class makes the skill available to queries from OCP
        - "skill_voc_filename" keyword argument is mandatory
          it defines the .voc file containing the keywords to match the game name

    bus events emitted to trigger this skill:
    - 'ovos.common_play.{self.skill_id}.play'
    - 'ovos.common_play.{self.skill_id}.pause'
    - 'ovos.common_play.{self.skill_id}.resume'
    - 'ovos.common_play.{self.skill_id}.stop'
    - 'ovos.common_play.{self.skill_id}.save' - TODO add intent to ocp_pipeline exclusive to MediaType.GAME
    - 'ovos.common_play.{self.skill_id}.load' - TODO add intent to ocp_pipeline exclusive to MediaType.GAME

    """

    def __init__(self, skill_voc_filename: str,
                 *args,
                 skill_icon: str = "",
                 game_image: str = "",
                 **kwargs):
        """IMPORTANT: contents of skill_voc_filename are crucial for intent matching
        without that ocp_pipeline might not recognize the skill as a game"""
        self.game_image = game_image
        super().__init__(skill_icon=skill_icon, skill_voc_filename=skill_voc_filename,
                         supported_media=[MediaType.GAME], *args, **kwargs)
        # in regular OCP skills these can be set via decorators
        # here we make them mandatory implementations via abc.abstractmethod
        self.__playback_handler = self.on_play_game
        self.__pause_handler = self.on_pause_game
        self.__resume_handler = self.on_resume_game

    @ocp_featured_media()
    def _ocp_featured(self) -> Playlist:
        """ensure skill shows up in OCP GUI menu
        report the game as the only featured_track"""
        entry = MediaEntry(
            uri=f"skill:{self.skill_id}",
            title=self.skill_aliases[0],
            image=self.game_image,
            playback=PlaybackType.SKILL,
            media_type=MediaType.GAME,
            match_confidence=100,
            skill_icon=self.skill_icon
        )
        pl = Playlist(
            title=self.skill_aliases[0],
            image=self.game_image,
            playback=PlaybackType.SKILL,
            media_type=MediaType.GAME,
            match_confidence=100,
            skill_icon=self.skill_icon)
        pl.add_entry(entry)
        return pl

    @ocp_search()
    def _ocp_search(self, phrase: str, media_type: MediaType) -> Iterable[MediaEntry]:
        """match the game name when OCP is searching"""
        if media_type != MediaType.GAME:
            # only match if ocp_pipeline determined a game was wanted
            return

        _, score = match_one(phrase, self.skill_aliases,
                             strategy=MatchStrategy.DAMERAU_LEVENSHTEIN_SIMILARITY)
        conf = int(score * 100)
        if conf >= 50:
            entry = self._ocp_featured()[0]
            entry.match_confidence = conf
            yield entry

    @property
    def is_playing(self) -> bool:
        return self._playing.is_set()

    @abc.abstractmethod
    def on_play_game(self):
        """called by ocp_pipeline when 'play XXX' matches the game"""

    @abc.abstractmethod
    def on_pause_game(self):
        """called by ocp_pipeline on 'pause' if game is being played"""

    @abc.abstractmethod
    def on_resume_game(self):
        """called by ocp_pipeline on 'resume/unpause' if game is being played and paused"""

    @abc.abstractmethod
    def on_stop_game(self):
        """called when game is stopped for any reason
        auto-save may be implemented here"""

    @abc.abstractmethod
    def on_save_game(self):
        """if your game has no save/load functionality you should
        speak a error dialog here"""

    @abc.abstractmethod
    def on_load_game(self):
        """if your game has no save/load functionality you should
        speak a error dialog here"""

    def stop(self) -> bool:
        if self.is_playing:
            self.on_stop_game()
            return True
        return False

    def calc_intent(self, utterance: str, lang: str) -> Optional[Dict[str, str]]:
        """helper to check what intent would be selected by ovos-core"""
        # let's see what intent ovos-core will assign to the utterance
        # NOTE: converse, common_query and fallbacks are not included in this check
        response = self.bus.wait_for_response(Message("intent.service.intent.get",
                                                      {"utterance": utterance, "lang": lang}),
                                              "intent.service.intent.reply",
                                              timeout=1.0)
        if not response:
            return None
        return response.data["intent"]


class ConversationalGameSkill(OVOSGameSkill):
    @abc.abstractmethod
    def on_play_game(self):
        """called by ocp_pipeline when 'play XXX' matches the game"""

    @abc.abstractmethod
    def on_pause_game(self):
        """called by ocp_pipeline on 'pause' if game is being played"""

    @abc.abstractmethod
    def on_resume_game(self):
        """called by ocp_pipeline on 'resume/unpause' if game is being played and paused"""

    @abc.abstractmethod
    def on_stop_game(self):
        """called when game is stopped for any reason
        auto-save may be implemented here"""

    @abc.abstractmethod
    def on_save_game(self):
        """if your game has no save/load functionality you should
        speak a error dialog here"""

    @abc.abstractmethod
    def on_load_game(self):
        """if your game has no save/load functionality you should
        speak a error dialog here"""

    # converse
    @abc.abstractmethod
    def on_game_command(self, utterance: str, lang: str):
        """pipe user input that wasnt caught by intents to the game
        do any intent matching or normalization here
        don't forget to self.speak the game output too!
        """

    @abc.abstractmethod
    def on_abandon_game(self):
        """user abandoned game mid interaction, good place to auto-save

        on_game_stop will be called after this handler"""

    def skill_will_trigger(self, utterance: str, lang: str, skill_id: Optional[str] = None) -> bool:
        """helper to check if this skill would be selected by ovos-core with the given utterance

        useful in converse method
            eg. return not self.will_trigger

        this example allows the utterance to be consumed via converse of using ovos-core intent parser
        ensuring it is always handled by the game skill regardless
        """
        # determine if an intent from this skill
        # will be selected by ovos-core
        id_to_check = skill_id or self.skill_id
        intent = self.calc_intent(utterance, lang)
        skill_id = intent["skill_id"] if intent else ""
        return skill_id == id_to_check

    def converse(self, message: Message):
        try:
            utterance = message.data["utterances"][0]
            lang = get_message_lang(message)
            # let the user implemented intents do the job if they can handle the utterance
            if self.is_playing and not self.skill_will_trigger(utterance, lang):
                # otherwise pipe utterance to the game handler
                self.on_game_command(utterance, lang)
                return True
            return False
        except (KeyError, IndexError) as e:
            self.log.error(f"Error processing converse message: {e}")
            return False
        except Exception as e:
            self.log.exception(f"Unexpected error in converse: {e}")
            return False

    def handle_deactivate(self, message: Message):
        """
        Called when this skill is no longer considered active by the intent service;
        means the user didn't interact with the game for a long time and intent parser will be released
        """
        try:
            if self.is_playing:
                self.log.info("Game abandoned due to inactivity")
                self.on_abandon_game()
                self.on_stop_game()
        except Exception as e:
            self.log.exception(f"Error during game deactivation: {e}")
