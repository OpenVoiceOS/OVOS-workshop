from enum import IntEnum
import time
import random

from ovos_utils.messagebus import Message, get_mycroft_bus, wait_for_reply
from ovos_utils.skills.audioservice import AudioServiceInterface
from ovos_utils.gui import GUIInterface
from ovos_utils.log import LOG

from ovos_workshop.frameworks.cps.youtube import is_youtube, \
    get_youtube_audio_stream, get_youtube_video_stream


class CPSPlayback(IntEnum):
    SKILL = 0
    GUI = 1
    AUDIO = 2


class CPSMatchConfidence(IntEnum):
    EXACT = 95
    VERY_HIGH = 90
    HIGH = 80
    AVERAGE_HIGH = 70
    AVERAGE = 50
    AVERAGE_LOW = 30
    LOW = 15
    VERY_LOW = 1


class CPSTrackStatus(IntEnum):
    DISAMBIGUATION = 1  # not queued for playback, show in gui
    PLAYING = 20  # Skill is handling playback internally
    PLAYING_AUDIOSERVICE = 21  # Skill forwarded playback to audio service
    PLAYING_GUI = 22  # Skill forwarded playback to gui
    PLAYING_ENCLOSURE = 23  # Skill forwarded playback to enclosure
    QUEUED = 30  # Waiting playback to be handled inside skill
    QUEUED_AUDIOSERVICE = 31  # Waiting playback in audio service
    QUEUED_GUI = 32  # Waiting playback in gui
    QUEUED_ENCLOSURE = 33  # Waiting for playback in enclosure
    PAUSED = 40  # media paused but ready to resume
    STALLED = 60  # playback has stalled, reason may be unknown
    BUFFERING = 61  # media is buffering from an external source
    END_OF_MEDIA = 90  # playback finished, is the default state when CPS loads


class CPSMatchType(IntEnum):
    GENERIC = 0
    AUDIO = 1
    MUSIC = 2
    VIDEO = 3
    AUDIOBOOK = 4
    GAME = 5
    PODCAST = 6
    RADIO = 7
    NEWS = 8
    TV = 9
    MOVIE = 10
    TRAILER = 11
    ADULT = 12
    VISUAL_STORY = 13
    BEHIND_THE_SCENES = 14
    DOCUMENTARY = 15
    RADIO_THEATRE = 16
    SHORT_FILM = 17
    SILENT_MOVIE = 18
    BLACK_WHITE_MOVIE = 20


class CommonPlayInterface:
    """ interface for mycroft common play """

    def __init__(self, bus=None):
        self.bus = bus or get_mycroft_bus()
        self.bus.on("play:query.response", self.handle_cps_response)
        self.query_replies = {}
        self.query_extensions = {}
        self.waiting = False
        self.start_ts = 0

    @property
    def cps_status(self):
        return wait_for_reply('play:status.query',
                              reply_type="play:status.response",
                              bus=self.bus).data

    def handle_cps_response(self, message):
        search_phrase = message.data["phrase"]

        if ("searching" in message.data and
                search_phrase in self.query_extensions):
            # Manage requests for time to complete searches
            skill_id = message.data["skill_id"]
            if message.data["searching"]:
                # extend the timeout by N seconds
                # IGNORED HERE, used in mycroft-playback-control skill
                if skill_id not in self.query_extensions[search_phrase]:
                    self.query_extensions[search_phrase].append(skill_id)
            else:
                # Search complete, don't wait on this skill any longer
                if skill_id in self.query_extensions[search_phrase]:
                    self.query_extensions[search_phrase].remove(skill_id)

        elif search_phrase in self.query_replies:
            # Collect all replies until the timeout
            self.query_replies[message.data["phrase"]].append(message.data)

    def send_query(self, phrase, media_type=CPSMatchType.GENERIC):
        self.query_replies[phrase] = []
        self.query_extensions[phrase] = []
        self.bus.emit(Message('play:query', {"phrase": phrase,
                                             "media_type": media_type}))

    def get_results(self, phrase):
        if self.query_replies.get(phrase):
            return self.query_replies[phrase]
        return []

    def search(self, phrase, media_type=CPSMatchType.GENERIC, timeout=5):
        self.send_query(phrase, media_type)
        self.waiting = True
        start_ts = time.time()
        while self.waiting and time.time() - start_ts <= timeout:
            time.sleep(0.2)
        self.waiting = False
        res = self.get_results(phrase)
        if res:
            return res
        if media_type != CPSMatchType.GENERIC:
            return self.search(phrase, media_type=CPSMatchType.GENERIC,
                               timeout=timeout)
        return []

    def search_best(self, phrase, media_type=CPSMatchType.GENERIC, timeout=5):
        # check responses
        # Look at any replies that arrived before the timeout
        # Find response(s) with the highest confidence
        best = None
        ties = []
        for handler in self.search(phrase, media_type, timeout):
            if not best or handler["conf"] > best["conf"]:
                best = handler
                ties = []
            elif handler["conf"] == best["conf"]:
                ties.append(handler)

        if best:
            if ties:
                # select randomly
                skills = ties + [best]
                selected = random.choice(skills)
                # TODO: Ask user to pick between ties or do it
                # automagically
            else:
                selected = best

            # will_resume = self.playback_status == CPSTrackStatus.PAUSED \
            #              and not bool(phrase.strip())
            will_resume = False
            return {"skill_id": selected["skill_id"],
                    "phrase": phrase,
                    "media_type": media_type,
                    "trigger_stop": not will_resume,
                    "callback_data": selected.get("callback_data")}

        return {}


class BetterCommonPlayInterface:
    """ interface for better common play """

    def __init__(self, bus=None, min_timeout=1, max_timeout=5,
                 allow_extensions=True, audio_service=None, gui=None,
                 backwards_compatibility=True, media_fallback=True):
        """
        Arguments:
            bus (MessageBus): mycroft messagebus connection
            min_timeout (float): minimum time to wait for skill replies,
                                 after this time, if at least 1 result was
                                 found, selection is triggered
            max_timeout (float): maximum time to wait for skill replies,
                                 after this time, regardless of number of
                                 results, selection is triggered
            allow_extensions (bool): if True, allow skills to request more
                                     time, extend min_timeout for specific
                                     queries up to max_timeout
            backwards_compatibility (bool): if True emits the regular
                                            mycroft-core bus messages to get
                                            results from "old style" skills
            media_fallback (bool): if no results, perform a second query
                                   with CPSMatchType.GENERIC
        """
        self.bus = bus or get_mycroft_bus()
        self.audio_service = audio_service or AudioServiceInterface(self.bus)
        self.gui = gui or GUIInterface("better-cps", bus=self.bus)

        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
        self.allow_extensions = allow_extensions
        self.media_fallback = media_fallback
        if backwards_compatibility:
            self.old_cps = CommonPlayInterface(self.bus)
        else:
            self.old_cps = None

        self.query_replies = {}
        self.query_timeouts = {}
        self.waiting = False
        self.search_start = 0
        self._search_results = []

        self.playback_status = CPSTrackStatus.END_OF_MEDIA
        self.active_backend = None  # re-uses CPSTrackStatus.PLAYING_XXX
        self.active_skill = None  # skill_id currently handling playback

        self.playback_data = {"playing": None,
                              "playlist": [],
                              "disambiguation": []}

        self.bus.on("better_cps.query.response", self.handle_cps_response)
        self.bus.on("better_cps.status.update", self.handle_cps_status_change)
        self.register_gui_handlers()

    def shutdown(self):
        self.bus.remove("better_cps.query.response", self.handle_cps_response)
        self.bus.remove("better_cps.status.update",
                        self.handle_cps_status_change)
        self.gui.shutdown()

    def handle_cps_response(self, message):
        search_phrase = message.data["phrase"]
        timeout = message.data.get("timeout")
        LOG.debug(f"BetterCPS received results: {message.data['skill_id']}")

        if message.data.get("searching"):
            # extend the timeout by N seconds
            if timeout and self.allow_extensions and \
                    search_phrase in self.query_timeouts:
                self.query_timeouts[search_phrase] += timeout
            # else -> expired search

        elif search_phrase in self.query_replies:
            # Collect replies until the timeout
            self.query_replies[search_phrase].append(message.data)

            # abort waiting if we gathered enough results
            if time.time() - self.search_start > self.query_timeouts[
                search_phrase]:
                self.waiting = False

    def search(self, phrase, media_type=CPSMatchType.GENERIC):
        self.query_replies[phrase] = []
        self.query_timeouts[phrase] = self.min_timeout
        self.search_start = time.time()
        self.waiting = True
        self.bus.emit(Message('better_cps.query',
                              {"phrase": phrase,
                               "media_type": media_type}))

        # old common play will send the messages expected by the official
        # mycroft stack, but skills are know to over match, dont support
        # match type, and the GUI is different for every skill, it may also
        # cause issues with status tracking and mess up playlists
        if self.old_cps:
            self.old_cps.send_query(phrase, media_type)

        # if there is no match type defined, lets increase timeout a bit
        # since all skills need to search
        if media_type == CPSMatchType.GENERIC:
            bonus = 3  # timeout bonus
        else:
            bonus = 0

        while self.waiting and \
                time.time() - self.search_start <= self.max_timeout + bonus:
            time.sleep(0.1)

        self.waiting = False

        # convert the returned data to the expected new format, playback
        # type is consider Skill, better cps will not handle the playback
        # life cycle but instead delegate to the skill
        if self.old_cps:
            old_style = self.old_cps.get_results(phrase)
            self.query_replies[phrase] += self._convert_to_new_style(old_style,
                                                                     media_type)

        if self.query_replies.get(phrase):
            return [s for s in self.query_replies[phrase] if s.get("results")]

        # fallback to generic media type
        if self.media_fallback and media_type != CPSMatchType.GENERIC:
            LOG.debug("BetterCPS falling back to CPSMatchType.GENERIC")
            return self.search(phrase, media_type=CPSMatchType.GENERIC)
        return []

    def search_skill(self, skill_id, phrase, media_type=CPSMatchType.GENERIC):
        res = [r for r in self.search(phrase, media_type)
               if r["skill_id"] == skill_id]
        if not len(res):
            return None
        return res[0]

    def process_search(self, selected, results):
        # TODO playlist
        self._update_current_media(selected)
        self._update_disambiguation(results)
        self._set_search_results(results, best=selected)
        self._set_now_playing(selected)
        self.play()

    @staticmethod
    def _convert_to_new_style(results, media_type=CPSMatchType.GENERIC):
        new_style = []
        for res in results:
            data = res['callback_data']
            data["skill_id"] = res["skill_id"]
            data["phrase"] = res["phrase"]
            data["is_old_style"] = True  # internal flag for playback handling
            data['match_confidence'] = res["conf"] * 100
            data["uri"] = data.get("stream") or \
                          data.get("url") or \
                          data.get("uri")

            # Essentially a random guess....
            data["media_type"] = media_type
            data["playback"] = CPSPlayback.SKILL
            if not data.get("image"):
                data["image"] = data.get("logo") or \
                                data.get("picture")
            if not data.get("bg_image"):
                data["bg_image"] = data.get("background") or \
                                   data.get("bg_picture") or \
                                   data.get("logo") or \
                                   data.get("picture")

            new_style.append({'phrase': res["phrase"],
                              "is_old_style": True,
                              'results': [data],
                              'searching': False,
                              'skill_id': res["skill_id"]})
        return new_style

    # status tracking
    def _update_current_media(self, data):
        """ Currently playing media """
        self.playback_data["playing"] = data

    def _update_playlist(self, data):
        """ List of queued media """
        self.playback_data["playlist"].append(data)
        # sort playlist by requested order
        self.playback_data["playlist"] = sorted(
            self.playback_data["playlist"],
            key=lambda i: int(i['playlist_position']) or 0)

    def _update_disambiguation(self, data):
        """ List of unused search results """
        self.playback_data["disambiguation"].append(data)

    def handle_cps_status_change(self, message):
        # message.data contains the media entry from search results and in
        # addition a "status" for that entry, this can be used to control
        # the playlist or simply communicate changes from the "playback
        # backend"
        status = message.data["status"]

        if status == CPSTrackStatus.PLAYING:
            # skill is handling playback internally
            self._update_current_media(message.data)
            self.playback_status = status
            self.active_backend = status
        elif status == CPSTrackStatus.PLAYING_AUDIOSERVICE:
            # audio service is handling playback
            self._update_current_media(message.data)
            self.playback_status = status
            self.active_backend = status
        elif status == CPSTrackStatus.PLAYING_GUI:
            # gui is handling playback
            self._update_current_media(message.data)
            self.playback_status = status
            self.active_backend = status

        elif status == CPSTrackStatus.DISAMBIGUATION:
            # alternative results
            self._update_disambiguation(message.data)
        elif status == CPSTrackStatus.QUEUED:
            # skill is handling playback and this is in playlist
            self._update_playlist(message.data)
        elif status == CPSTrackStatus.QUEUED_GUI:
            # gui is handling playback and this is in playlist
            self._update_playlist(message.data)
        elif status == CPSTrackStatus.QUEUED_AUDIOSERVICE:
            # audio service is handling playback and this is in playlist
            self._update_playlist(message.data)

        elif status == CPSTrackStatus.PAUSED:
            # media is not being played, but can be resumed anytime
            # a new PLAYING status should be sent once playback resumes
            self.playback_status = status
        elif status == CPSTrackStatus.BUFFERING:
            # media is buffering, might want to show in ui
            # a new PLAYING status should be sent once playback resumes
            self.playback_status = status
        elif status == CPSTrackStatus.STALLED:
            # media is stalled, might want to show in ui
            # a new PLAYING status should be sent once playback resumes
            self.playback_status = status
        elif status == CPSTrackStatus.END_OF_MEDIA:
            # if we add a repeat/loop flag this is the place to check for it
            self.playback_status = status

    def update_status(self, status):
        self.bus.emit(Message('better_cps.status.update', status))

    # playback control
    def play(self):

        data = self.playback_data.get("playing") or {}
        uri = data.get("stream") or data.get("uri") or data.get("url")
        skill_id = self.active_skill = data["skill_id"]

        self.stop()

        if data["playback"] == CPSPlayback.AUDIO:
            data["status"] = CPSTrackStatus.PLAYING_AUDIOSERVICE
            real_url = self.get_stream(uri)
            self.audio_service.play(real_url)

        elif data["playback"] == CPSPlayback.SKILL:
            data["status"] = CPSTrackStatus.PLAYING
            if data.get("is_old_style"):
                self.bus.emit(Message('play:start',
                                      {"skill_id": skill_id,
                                       "callback_data": data,
                                       "phrase": data["phrase"]}))
            else:
                self.bus.emit(Message(f'better_cps.{skill_id}.play', data))
        elif data["playback"] == CPSPlayback.GUI:
            pass  # plays in display_ui
        else:
            raise ValueError("invalid playback request")
        self.update_status(data)
        self._set_now_playing(data)
        self.display_ui()
        self.update_player_status("Playing")

    @staticmethod
    def get_stream(uri, video=False):
        real_url = None
        if is_youtube(uri):
            if not video:
                real_url = get_youtube_audio_stream(uri)
            if video or not real_url:
                real_url = get_youtube_video_stream(uri)
        return real_url or uri

    def play_next(self):
        # TODO playlist handling
        if self.active_backend == CPSTrackStatus.PLAYING_GUI:
            pass
        elif self.active_backend == CPSTrackStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.next()
        elif self.active_backend is not None:
            self.bus.emit(Message(f'better_cps.{self.active_skill}.next'))

    def play_prev(self):
        # TODO playlist handling
        if self.active_backend == CPSTrackStatus.PLAYING_GUI:
            pass
        elif self.active_backend == CPSTrackStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.prev()
        elif self.active_backend is not None:
            self.bus.emit(Message(f'better_cps.{self.active_skill}.prev'))

    def pause(self):
        self.update_status({"status": CPSTrackStatus.PAUSED})
        if self.active_backend == CPSTrackStatus.PLAYING_GUI:
            self.gui.pause_video()
        elif self.active_backend == CPSTrackStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.pause()
        elif self.active_backend is not None:
            self.bus.emit(Message(f'better_cps.{self.active_skill}.pause'))

    def resume(self):
        if self.active_backend == CPSTrackStatus.PLAYING_GUI:
            self.gui.resume_video()
        elif self.active_backend == CPSTrackStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.resume()
        elif self.active_backend is not None:
            self.bus.emit(Message(f'better_cps.{self.active_skill}.resume'))
        self.update_status({"status": self.active_backend})

    def stop(self):
        if self.active_backend == CPSTrackStatus.PLAYING_GUI:
            self.gui.stop_video()
        elif self.active_backend == CPSTrackStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.stop()
        elif self.active_backend is not None:
            self.bus.emit(Message(f'better_cps.{self.active_skill}.stop'))
        self.update_status({"status": CPSTrackStatus.END_OF_MEDIA})
        stopped = self.active_backend is not None
        self.active_backend = None
        self.active_skill = None
        return stopped

    # ######### GUI integration ###############
    def register_gui_handlers(self):
        self.gui.register_handler('better-cps.gui.play',
                                  self.handle_click_resume)
        self.gui.register_handler('better-cps.gui.pause',
                                  self.handle_click_pause)
        self.gui.register_handler('better-cps.gui.next',
                                  self.handle_click_next)
        self.gui.register_handler('better-cps.gui.previous',
                                  self.handle_click_previous)
        self.gui.register_handler('better-cps.gui.seek',
                                  self.handle_click_seek)

        self.gui.register_handler('better-cps.gui.playlist.play',
                                  self.handle_play_from_playlist)
        self.gui.register_handler('better-cps.gui.search.play',
                                  self.handle_play_from_search)

    def update_player_status(self, status, page=0):
        self.gui["media"]["status"] = status
        self.display_ui(page=page)

    def display_ui(self, search=None, media=None, playlist=None, page=0):
        search_qml = "Disambiguation.qml"
        player_qml = "AudioPlayer.qml"
        video_player_qml = "VideoPlayer.qml"
        playlist_qml = "Playlist.qml"

        media = media or self.gui.get("media") or {}
        media["status"] = media.get("status", "Paused")
        media["position"] = media.get("position", 0)
        media["length"] = media.get("length") or -1
        search = search or self.gui.get("searchModel", {}).get("data") or {}
        playlist = playlist or self.gui.get("playlistModel", {}).get("data") or {}

        # remove previous pages
        pages = [player_qml, search_qml, playlist_qml, video_player_qml]
        self.gui.remove_pages(pages)

        # display "now playing" video page
        if media.get("playback", -1) == CPSPlayback.GUI:
            uri = media.get("stream") or \
                  media.get("url") or \
                  media.get("uri")
            self.gui["stream"] = self.get_stream(uri, video=True)
            self.gui["title"] = media.get("title", "")
            self.gui["playStatus"] = "play"
            pages = [video_player_qml, search_qml, playlist_qml]

        # display "now playing" music page
        else:
            pages = [player_qml, search_qml, playlist_qml]

        self.gui["searchModel"] = {"data": search}
        self.gui["playlistModel"] = {"data": playlist}
        self.gui.show_pages(pages, page, override_idle=True)

    def _set_search_results(self, results, best=None):
        best = best or results[0]
        for idx, data in enumerate(results):
            results[idx]["length"] = data.get("length") or \
                                     data.get("track_length") or \
                                     data.get("duration")
        self._search_results = results
        # send all results for disambiguation
        # this can be used in GUI or any other use facing interface to
        # override the final selection
        for r in self._search_results:
            status = dict(r)
            status["status"] = CPSTrackStatus.DISAMBIGUATION
            self.bus.emit(Message('better_cps.status.update', status))
        results = sorted(results, key=lambda k: k.get("match_confidence"),
                         reverse=True)[:100]
        results = self._res2playlist(results)
        playlist = self._res2playlist([best])  # TODO cps playlist
        self.display_ui(media=best, playlist=playlist, search=results)

    @staticmethod
    def _res2playlist(res):
        playlist_data = []
        for r in res:
            playlist_data.append({
                "album": r.get('skill_id'),
                "duration": r.get('length'),
                "image": r.get('image'),
                "source": r.get('skill_icon') or r.get('skill_logo'),
                "track": r.get("title")
            })
        return playlist_data

    def _set_now_playing(self, data):
        if data.get("bg_image", "").startswith("/"):
            data["bg_image"] = "file:/" + data["bg_image"]
        data["skill"] = data.get("skill_id", "better-cps")
        data["position"] = data.get("position", 0)

        data["length"] = data.get("length") or data.get("track_length") or \
                         data.get("duration")  # or get_duration_from_url(url)

        self.gui["media"] = data
        self.gui["bg_image"] = data.get("bg_image",
                                        "https://source.unsplash.com/weekly?music")

    # gui events
    def handle_click_pause(self, message):
        self.audio_service.pause()
        self.update_player_status("Paused")

    def handle_click_resume(self, message):
        self.audio_service.resume()
        self.update_player_status("Playing")

    def handle_click_next(self, message):
        pass

    def handle_click_previous(self, message):
        pass

    def handle_click_seek(self, message):
        position = message.data.get("seekValue", "")
        print("seek:", position)
        if position:
            self.audio_service.set_track_position(position / 1000)
            self.gui["media"]["position"] = position
            self.display_ui()

    def handle_play_from_playlist(self, message):
        playlist_data = message.data["playlistData"]
        self.__play(playlist_data)

    def handle_play_from_search(self, message):
        res = self._res2playlist(self._search_results)
        playlist_data = message.data["playlistData"]
        idx = res.index(playlist_data)
        self.__play(self._search_results[idx])

    def __play(self, media):
        playlist = self._res2playlist([media])  # TODO cps playlist
        self.gui["playlistModel"] = {"data": playlist}
        self._update_current_media(media)
        self.play()


class CPSTracker:
    def __init__(self, bus=None, gui=None):
        self.bus = bus or get_mycroft_bus()
        self.bus.on("better_cps.query.response", self.handle_cps_response)
        self.bus.on("better_cps.status.update", self.handle_cps_status_change)

        self.gui = gui or GUIInterface("better-cps", bus=self.bus)
        self.register_gui_handlers()

    def register_gui_handlers(self):
        self.gui.register_handler('better-cps.gui.play',
                                  self.handle_click_resume)
        self.gui.register_handler('better-cps.gui.pause',
                                  self.handle_click_pause)
        self.gui.register_handler('better-cps.gui.next',
                                  self.handle_click_next)
        self.gui.register_handler('better-cps.gui.previous',
                                  self.handle_click_previous)
        self.gui.register_handler('better-cps.gui.seek',
                                  self.handle_click_seek)

        self.gui.register_handler('better-cps.gui.playlist.play',
                                  self.handle_play_from_playlist)
        self.gui.register_handler('better-cps.gui.search.play',
                                  self.handle_play_from_search)

    def shutdown(self):
        self.bus.remove("better_cps.query.response", self.handle_cps_response)
        self.bus.remove("better_cps.status.update",
                        self.handle_cps_status_change)
        self.gui.shutdown()

    def handle_cps_response(self, message):
        search_phrase = message.data["phrase"]
        skill = message.data['skill_id']
        timeout = message.data.get("timeout")

        if message.data.get("searching"):
            if timeout:
                self.on_extend_timeout(search_phrase, skill, timeout)
        else:
            self.on_skill_results(search_phrase, skill, message.data)

    def handle_cps_status_change(self, message):
        status = message.data["status"]
        print("New status:", status)

    def handle_click_resume(self, message):
        print(message.data)

    def handle_click_pause(self, message):
        print(message.data)

    def handle_click_next(self, message):
        print(message.data)

    def handle_click_previous(self, message):
        print(message.data)

    def handle_click_seek(self, message):
        print(message.data)

    def handle_play_from_playlist(self, message):
        print(message.data)

    def handle_play_from_search(self, message):
        print(message.data)

    # users can subclass these
    def on_query(self, message):
        pass

    def on_skill_results(self, phrase, skill_id, results):
        pass

    def on_query_response(self, message):
        pass

    def on_status_change(self, message):
        pass

    def on_extend_timeout(self, phrase, timeout, skill_id):
        print("extending timeout:", timeout, "\n",
              "phrase:", phrase, "\n",
              "skill:", skill_id, "\n")

    def on_skill_play(self, message):
        pass

    def on_audio_play(self, message):
        pass

    def on_gui_play(self, message):
        pass


if __name__ == "__main__":
    from pprint import pprint

    cps = BetterCommonPlayInterface(max_timeout=10, min_timeout=2)

    # test lovecraft skills
    pprint(cps.search_skill("skill-omeleto", "movie", CPSMatchType.SHORT_FILM))

    exit()
    pprint(cps.search("the thing in the doorstep"))

    pprint(cps.search("dagon", CPSMatchType.VIDEO))

    pprint(cps.search("dagon hp lovecraft"))
