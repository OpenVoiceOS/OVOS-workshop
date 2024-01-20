import os
from inspect import signature
from threading import Event
from typing import List

from ovos_utils import camel_case_split
from ovos_utils.log import LOG

from ovos_bus_client import Message
from ovos_classifiers.skovos.features import KeywordFeatures
from ovos_config.locations import get_xdg_cache_save_path
from ovos_workshop.skills.ovos import OVOSSkill

# backwards compat imports, do not delete, skills import from here
from ovos_workshop.decorators.ocp import ocp_play, ocp_next, ocp_pause, ocp_resume, ocp_search, \
    ocp_previous, ocp_featured_media
from ovos_utils.ocp import MediaType, MediaState, MatchConfidence, \
    PlaybackType, PlaybackMode, PlayerState, LoopState, TrackState


def get_non_properties(obj):
    """Get attibutes that are not properties from object.

    Will return members of object class along with bases down to MycroftSkill.

    Args:
        obj: object to scan

    Returns:
        Set of attributes that are not a property.
    """

    def check_class(cls):
        """Find all non-properties in a class."""
        # Current class
        d = cls.__dict__
        np = [k for k in d if not isinstance(d[k], property)]
        # Recurse through base classes excluding MycroftSkill and object
        for b in [b for b in cls.__bases__ if b not in (object, OVOSSkill)]:
            np += check_class(b)
        return np

    return set(check_class(obj.__class__))


class OVOSCommonPlaybackSkill(OVOSSkill):
    """ To integrate with the OpenVoiceOS Common Playback framework
    skills should use this base class and the companion decorators

    @ocp_search
    def ...

    @ocp_play
    def ...

    The class makes the skill available to queries from OCP and no special
    vocab for starting playback is needed.
    """

    def __init__(self, *args, **kwargs):
        # NOTE: derived skills will likely want to override this list
        self.supported_media = [MediaType.GENERIC]
        skill_name = camel_case_split(self.__class__.__name__)
        alt = skill_name.replace(" skill", "").replace(" Skill", "")
        self.skill_aliases = [skill_name, alt]

        self._search_handlers = []  # added via decorators
        self._featured_handlers = []  # added via decorators
        self._current_query = None
        self.__playback_handler = None
        self.__pause_handler = None
        self.__next_handler = None
        self.__prev_handler = None
        self.__resume_handler = None
        self._stop_event = Event()
        self._playing = Event()
        # TODO replace with new default
        self.skill_icon = \
            "https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/" \
            "ovos_plugin_common_play/ocp/res/ui/images/ocp.png"

        self.ocp_matchers = {}
        super().__init__(*args, **kwargs)

    @property
    def ocp_cache_dir(self):
        """path to cached .csv file with ocp entities data
        this file needs to be available in ovos-core

        NB: ovos-docker needs a shared volume
        """
        os.makedirs(f"{get_xdg_cache_save_path()}/OCP", exist_ok=True)
        return f"{get_xdg_cache_save_path()}/OCP"

    def bind(self, bus):
        """Overrides the normal bind method.

        Adds handlers for play:query and play:start messages allowing
        interaction with the playback control skill.

        This is called automatically during setup, and
        need not otherwise be used.
        """
        if bus:
            super().bind(bus)
            self.add_event('ovos.common_play.query',
                           self.__handle_ocp_query)
            self.add_event('ovos.common_play.featured_tracks.play',
                           self.__handle_ocp_featured)
            self.add_event('ovos.common_play.skills.get',
                           self.__handle_ocp_skills_get)
            self.add_event(f'ovos.common_play.{self.skill_id}.play',
                           self.__handle_ocp_play)
            self.add_event(f'ovos.common_play.{self.skill_id}.pause',
                           self.__handle_ocp_pause)
            self.add_event(f'ovos.common_play.{self.skill_id}.resume',
                           self.__handle_ocp_resume)
            self.add_event(f'ovos.common_play.{self.skill_id}.next',
                           self.__handle_ocp_next)
            self.add_event(f'ovos.common_play.{self.skill_id}.previous',
                           self.__handle_ocp_prev)
            self.add_event(f'ovos.common_play.{self.skill_id}.stop',
                           self.__handle_ocp_stop)
            self.add_event("ovos.common_play.search.stop",
                           self.__handle_stop_search)
            self.add_event("mycroft.stop",
                           self.__handle_stop_search)

    def register_media_type(self, media_type: MediaType):
        """ helper instead of editing self.supported_media directly
        will auto-sync changes via bus"""
        if media_type not in self.supported_media:
            self.supported_media.append(media_type)
            LOG.info(f"{self.skill_id} registered type {media_type}")
            self.__handle_ocp_skills_get()

    def __handle_ocp_skills_get(self, message=None):
        """ report skill OCP info

        thumbnail and featured tracks inform the OCP homescreen

        media_type and skill_name help the classifier disambiguate between media_types
            eg, if OCP finds the name of a movie skill in user utterance
                it will search netflix instead of spotify
         """
        message = message or Message("")
        self.bus.emit(
            message.reply('ovos.common_play.announce',
                          {"skill_id": self.skill_id,
                           "skill_name": self.skill_name,
                           "aliases": self.skill_aliases,
                           "thumbnail": self.skill_icon,
                           "media_type": self.supported_media,
                           "featured_tracks": len(self._featured_handlers) >= 1}))

    def ocp_voc_match(self, utterance, lang=None):
        """uses Aho–Corasick algorithm to match OCP keywords
        this efficiently matches many keywords against an utterance

        OCP keywords are registered via self.register_ocp_keyword

        example usages
            print(self.ocp_voc_match("play metallica"))
            # {'album_name': 'Metallica', 'artist_name': 'Metallica'}

            print(self.ocp_voc_match("play the beatles"))
            # {'album_name': 'The Beatles', 'series_name': 'The Beatles',
            # 'artist_name': 'The Beatles', 'movie_name': 'The Beatles'}

            print(self.ocp_voc_match("play rob zombie"))
            # {'artist_name': 'Rob Zombie', 'album_name': 'Zombie',
            # 'book_name': 'Zombie', 'game_name': 'Zombie', 'movie_name': 'Zombie'}

            print(self.ocp_voc_match("play horror movie"))
            # {'film_genre': 'Horror', 'cartoon_genre': 'Horror', 'anime_genre': 'Horror',
            # 'radio_drama_genre': 'horror', 'video_genre': 'horror',
            # 'book_genre': 'Horror', 'movie_name': 'Horror Movie'}

            print(self.ocp_voc_match("play science fiction"))
            #  {'film_genre': 'Science Fiction', 'cartoon_genre': 'Science Fiction',
            #  'podcast_genre': 'Fiction', 'anime_genre': 'Science Fiction',
            #  'documentary_genre': 'Science', 'book_genre': 'Science Fiction',
            #  'artist_name': 'Fiction', 'tv_channel': 'Science',
            #  'album_name': 'Science Fiction', 'short_film_name': 'Science',
            #  'book_name': 'Science Fiction', 'movie_name': 'Science Fiction'}
        """
        lang = lang or self.lang
        if lang not in self.ocp_matchers:
            return {}
        matches = {}
        for k, v in self.ocp_matchers[lang].match(utterance):
            if k not in matches or len(v) > len(matches[k]):
                matches[k] = v
        return matches

    def load_ocp_keyword_from_csv(self, csv_path: str, lang: str = None):
        """ load entities from a .csv file for usage with self.ocp_voc_match
        see the ocp_entities.csv datatsets for example files built from wikidata SPARQL queries

        examples contents of csv file

            label,entity
            film_genre,swashbuckler film
            film_genre,neo-noir
            film_genre,actual play film
            film_genre,alternate history film
            film_genre,spy film
            ...
        """
        if lang is None:
            for lang in self.native_langs:
                if lang not in self.ocp_matchers:
                    self.ocp_matchers[lang] = KeywordFeatures()
                self.ocp_matchers[lang].load_entities(csv_path)
        else:
            if lang not in self.ocp_matchers:
                self.ocp_matchers[lang] = KeywordFeatures()
            self.ocp_matchers[lang].load_entities(csv_path)

    def export_ocp_keywords_csv(self, csv_path: str = None, lang: str = None,
                                label: str = None):
        """ export entities to a .csv file """
        lang = lang or self.lang
        if lang not in self.ocp_matchers:
            raise RuntimeError(f"no entities registered for lang: {lang}")

        csv_path = csv_path or f"{self.ocp_cache_dir}/{self.skill_id}_{lang}.csv"
        with open(csv_path, "w") as f:
            f.write("label,sample")
            for ent, samples in self.ocp_matchers[lang].entities.items():
                if label is not None and label != ent:
                    continue
                for s in set(samples):
                    f.write(f"\n{ent},{s}")
        LOG.info(f"{self.skill_id} OCP {lang} entities exported to {csv_path}")
        return csv_path

    def register_ocp_keyword(self, media_type: MediaType, label: str,
                             samples: List, langs: List[str] = None):
        """ register strings as native OCP keywords (eg, movie_name, artist_name ...)

        ocp keywords can be efficiently matched with self.ocp_match helper method
        that uses Aho–Corasick algorithm
        """
        samples = list(set(samples))
        langs = langs or self.native_langs
        for l in langs:
            if l not in self.ocp_matchers:
                self.ocp_matchers[l] = KeywordFeatures()
            self.ocp_matchers[l].register_entity(label, samples)

        #  if the label is a valid OCP entity known by the classifier it will help
        #  the classifier disambiguate between media_types
        #  eg, if OCP finds a movie name in user utterances it will
        #      prefer to search netflix instead of spotify

        # NB: we send a file path, bus messages with thousands of entities dont work well
        if len(samples) >= 20:
            csv = f"{self.ocp_cache_dir}/{self.skill_id}_{label}.csv"
            self.export_ocp_keywords_csv(csv, label=label)
            self.bus.emit(
                Message('ovos.common_play.register_keyword',
                        {"skill_id": self.skill_id,
                         "label": label,  # if in OCP_ENTITIES it influences classifier
                         "csv": csv,
                         "media_type": media_type}))
        else:
            self.bus.emit(
                Message('ovos.common_play.register_keyword',
                        {"skill_id": self.skill_id,
                         "label": label,  # if in OCP_ENTITIES it influences classifier
                         "samples": samples,
                         "media_type": media_type}))

    def deregister_ocp_keyword(self, media_type: MediaType, label: str,
                               langs: List[str] = None):
        langs = langs or self.native_langs
        for l in langs:
            if l in self.ocp_matchers:
                self.ocp_matchers[l].deregister_entity(label)

        self.bus.emit(
            Message('ovos.common_play.deregister_keyword',
                    {"skill_id": self.skill_id,
                     "label": label,
                     "media_type": media_type}))

    def _register_decorated(self):
        # register search handlers
        for attr_name in get_non_properties(self):
            method = getattr(self, attr_name)
            if hasattr(method, 'is_ocp_search_handler'):
                if method.is_ocp_search_handler:
                    # TODO this wont accept methods with killable_event
                    #  decorators
                    self._search_handlers.append(method)
            if hasattr(method, 'is_ocp_featured_handler'):
                if method.is_ocp_featured_handler:
                    # TODO this wont accept methods with killable_event
                    #  decorators
                    self._featured_handlers.append(method)
            if hasattr(method, 'is_ocp_playback_handler'):
                if method.is_ocp_playback_handler:
                    # TODO how to handle multiple ??
                    if self.__playback_handler:
                        LOG.warning("multiple declarations of playback "
                                    "handler, replacing previous handler")
                    self.__playback_handler = method
            if hasattr(method, 'is_ocp_pause_handler'):
                if method.is_ocp_pause_handler:
                    # TODO how to handle multiple ??
                    if self.__pause_handler:
                        LOG.warning("multiple declarations of pause "
                                    "handler, replacing previous handler")
                    self.__pause_handler = method
            if hasattr(method, 'is_ocp_next_handler'):
                if method.is_ocp_next_handler:
                    # TODO how to handle multiple ??
                    if self.__next_handler:
                        LOG.warning("multiple declarations of play next "
                                    "handler, replacing previous handler")
                    self.__next_handler = method
            if hasattr(method, 'is_ocp_prev_handler'):
                if method.is_ocp_prev_handler:
                    # TODO how to handle multiple ??
                    if self.__prev_handler:
                        LOG.warning("multiple declarations of play previous "
                                    "handler, replacing previous handler")
                    self.__prev_handler = method
            if hasattr(method, 'is_ocp_resume_handler'):
                if method.is_ocp_resume_handler:
                    # TODO how to handle multiple ??
                    if self.__resume_handler:
                        LOG.warning("multiple declarations of resume playback"
                                    "handler, replacing previous handler")
                    self.__resume_handler = method

        super()._register_decorated()

        # volunteer info to OCP
        self.bus.emit(
            Message('ovos.common_play.announce',
                    {"skill_id": self.skill_id,
                     "skill_name": self.skill_aliases[0],
                     "thumbnail": self.skill_icon,
                     "media_types": self.supported_media,
                     "featured_tracks": len(self._featured_handlers) >= 1}))

    def extend_timeout(self, timeout=0.5):
        """ request more time for searching, limits are defined by
        better-common-play framework, by default max total time is 5 seconds
        per query """
        if self._current_query:
            self.bus.emit(Message("ovos.common_play.query.response",
                                  {"phrase": self._current_query,
                                   "skill_id": self.skill_id,
                                   "skill_name": self.skill_aliases[0],
                                   "thumbnail": self.skill_icon,
                                   "timeout": timeout,
                                   "searching": True}))

    def play_media(self, media, disambiguation=None, playlist=None):
        disambiguation = disambiguation or [media]
        playlist = playlist or [media]
        self.bus.emit(Message("ovos.common_play.play",
                              {"media": media,
                               "disambiguation": disambiguation,
                               "playlist": playlist}))

    # @killable_event("ovos.common_play.stop", react_to_stop=True)
    def __handle_ocp_play(self, message):
        if self.__playback_handler:
            self.__playback_handler(message)
            self.bus.emit(Message("ovos.common_play.player.state",
                                  {"state": PlayerState.PLAYING}))
            self._playing.set()
        else:
            LOG.error(f"Playback requested but {self.skill_id} handler not "
                      "implemented")

    def __handle_ocp_pause(self, message):
        if self.__pause_handler:
            if self.__pause_handler(message):
                self.bus.emit(Message("ovos.common_play.player.state",
                                      {"state": PlayerState.PAUSED}))
        else:
            LOG.error(f"Pause requested but {self.skill_id} handler not "
                      "implemented")

    def __handle_ocp_resume(self, message):
        if self.__resume_handler:
            if self.__resume_handler(message):
                self.bus.emit(Message("ovos.common_play.player.state",
                                      {"state": PlayerState.PLAYING}))
        else:
            LOG.error(f"Resume requested but {self.skill_id} handler not "
                      "implemented")

    def __handle_ocp_next(self, message):
        if self.__next_handler:
            self.__next_handler(message)
        else:
            LOG.error(f"Play Next requested but {self.skill_id} handler not "
                      "implemented")

    def __handle_ocp_prev(self, message):
        if self.__prev_handler:
            self.__prev_handler(message)
        else:
            LOG.error(f"Play Next requested but {self.skill_id} handler not "
                      "implemented")

    def __handle_ocp_stop(self, message):
        # for skills managing their own playback
        if self._playing.is_set():
            self.stop()
            self.gui.release()
            self.bus.emit(Message("ovos.common_play.player.state",
                                  {"state": PlayerState.STOPPED}))
            self._playing.clear()

    def __handle_stop_search(self, message):
        self._stop_event.set()

    # @killable_event("ovos.common_play.search.stop", react_to_stop=True)
    def __handle_ocp_query(self, message):
        """Query skill if it can start playback from given phrase."""
        self._stop_event.clear()
        search_phrase = message.data["phrase"]
        self._current_query = search_phrase
        media_type = message.data.get("question_type",
                                      MediaType.GENERIC)

        if media_type not in self.supported_media:
            return

        self.bus.emit(message.reply("ovos.common_play.skill.search_start",
                                    {"skill_id": self.skill_id,
                                     "skill_name": self.skill_aliases[0],
                                     "thumbnail": self.skill_icon, }))

        # invoke the media search handlesr to let the skill perform its search
        found = False
        for handler in self._search_handlers:
            if self._stop_event.is_set():
                break
            # @ocp_search
            # def handle_search(...):
            if len(signature(handler).parameters) == 1:
                # no optional media_type argument
                results = handler(search_phrase) or []
            else:
                results = handler(search_phrase, media_type) or []

            # handler might return a generator or a list
            if isinstance(results, list):
                # inject skill id in individual results, will be needed later
                # for proper playback handling
                for idx, r in enumerate(results):
                    results[idx]["skill_id"] = self.skill_id
                self.bus.emit(message.response({"phrase": search_phrase,
                                                "skill_id": self.skill_id,
                                                "skill_name": self.skill_aliases[0],
                                                "thumbnail": self.skill_icon,
                                                "results": results,
                                                "searching": False}))
                found = True
            else:  # generator, keeps returning results
                for r in results:
                    # inject skill id in individual results, will be needed later
                    # for proper playback handling
                    r["skill_id"] = self.skill_id
                    self.bus.emit(message.response({"phrase": search_phrase,
                                                    "skill_id": self.skill_id,
                                                    "skill_name": self.skill_aliases[0],
                                                    "thumbnail": self.skill_icon,
                                                    "results": [r],
                                                    "searching": False}))
                    found = True
                    if self._stop_event.is_set():
                        break

        if not found:
            # Signal we are done (can't handle it)
            self.bus.emit(message.response({"phrase": search_phrase,
                                            "skill_id": self.skill_id,
                                            "skill_name": self.skill_aliases[0],
                                            "thumbnail": self.skill_icon,
                                            "searching": False}))
        self.bus.emit(message.reply("ovos.common_play.skill.search_end",
                                    {"skill_id": self.skill_id}))

    def __handle_ocp_featured(self, message):
        skill_id = message.data["skill_id"]
        if skill_id != self.skill_id:
            return

        results = []
        for handler in self._featured_handlers:
            try:
                results += list(handler())  # handler might return a generator or a list
            except Exception as e:
                LOG.error(e)

        if not results:
            self.speak_dialog("no.media.available")
        else:
            # inject skill id in individual results
            for idx, r in enumerate(results):
                results[idx]["skill_id"] = self.skill_id
            self.bus.emit(Message("ovos.common_play.skill.play",
                                  {"skill_id": self.skill_id,
                                   "skill_name": self.skill_aliases[0],
                                   "thumbnail": self.skill_icon,
                                   "playlist": results}))

    def default_shutdown(self):
        self.bus.emit(
            Message('ovos.common_play.skills.detach',
                    {"skill_id": self.skill_id}))
        super().default_shutdown()
