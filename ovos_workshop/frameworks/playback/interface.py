import random
import random
import time

from ovos_utils.log import LOG
from ovos_utils.messagebus import Message, wait_for_reply
from ovos_utils.skills.audioservice import AudioServiceInterface
from ovos_workshop.frameworks.playback.playlists import Playlist, MediaEntry
from ovos_workshop.frameworks.playback.status import *
from ovos_workshop.frameworks.playback.youtube import is_youtube, \
    get_youtube_audio_stream, get_youtube_video_stream
import enum


class VideoPlayerType(enum.Enum):
    SIMPLE = enum.auto()
    MYCROFT = enum.auto()


class AudioPlayerType(enum.Enum):
    SIMPLE = enum.auto()
    MYCROFT = enum.auto()


class MycroftCommonPlayInterface:
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

    def send_query(self, phrase, media_type=CommonPlayMediaType.GENERIC):
        self.query_replies[phrase] = []
        self.query_extensions[phrase] = []
        self.bus.emit(Message('play:query', {"phrase": phrase,
                                             "question_type": media_type}))

    def get_results(self, phrase):
        if self.query_replies.get(phrase):
            return self.query_replies[phrase]
        return []

    def search(self, phrase, media_type=CommonPlayMediaType.GENERIC,
               timeout=5):
        self.send_query(phrase, media_type)
        self.waiting = True
        start_ts = time.time()
        while self.waiting and time.time() - start_ts <= timeout:
            time.sleep(0.2)
        self.waiting = False
        res = self.get_results(phrase)
        if res:
            return res
        if media_type != CommonPlayMediaType.GENERIC:
            return self.search(phrase, media_type=CommonPlayMediaType.GENERIC,
                               timeout=timeout)
        return []

    def search_best(self, phrase, media_type=CommonPlayMediaType.GENERIC,
                    timeout=5):
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

            # will_resume = self.playback_status == CommonPlayStatus.PAUSED \
            #              and not bool(phrase.strip())
            will_resume = False
            return {"skill_id": selected["skill_id"],
                    "phrase": phrase,
                    "question_type": media_type,
                    "trigger_stop": not will_resume,
                    "callback_data": selected.get("callback_data")}

        return {}


class OVOSCommonPlaybackInterface:
    """ interface for OVOS Common Playback Service """

    def __init__(self, bus=None, min_timeout=1, max_timeout=5,
                 allow_extensions=True, audio_service=None, gui=None,
                 backwards_compatibility=True, media_fallback=True,
                 early_stop_conf=90, early_stop_grace_period=1.0,
                 min_score=30, video_player=VideoPlayerType.SIMPLE,
                 audio_player=AudioPlayerType.SIMPLE):
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
                                   with CommonPlayMediaType.GENERIC
            early_stop_conf (int): stop collecting results if we get a
                                   match with confidence >= early_stop_conf
            early_stop_grace_period (float): sleep this ammount before early stop,
                                   allows skills that "just miss" to also be
                                   taken into account
            min_score (int): only display results above this confidence in
                             disambiguation VIDEO page
        """
        self.bus = bus or get_mycroft_bus()
        self.audio_service = audio_service or AudioServiceInterface(self.bus)
        self.gui = gui or GUIInterface("ovos.common_play", bus=self.bus)

        self.video_player = video_player
        self.audio_player = audio_player
        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
        self.min_score = min_score
        self.allow_extensions = allow_extensions
        self.media_fallback = media_fallback
        self.early_stop_thresh = early_stop_conf
        self.early_stop_grace_period = early_stop_grace_period
        if backwards_compatibility:
            self.old_cps = MycroftCommonPlayInterface(self.bus)
        else:
            self.old_cps = None

        self.query_replies = {}
        self.query_timeouts = {}
        self.waiting = False
        self.search_start = 0
        self._search_results = []

        self.playback_status = CommonPlayStatus.END_OF_MEDIA
        self.active_backend = None  # re-uses CommonPlayStatus.PLAYING_XXX
        self.active_skill = None  # skill_id currently handling playback

        self.playback_data = {"playing": None,
                              "playlist": [],
                              "disambiguation": []}

        self.disambiguation_playlist = Playlist()
        self.playlist = Playlist()
        self.now_playing = None

        self.bus.on("ovos.common_play.query.response",
                    self.handle_skill_response)
        self.bus.on("ovos.common_play.status.update",
                    self.handle_status_change)
        self.bus.on("ovos.common_play.playback_time",
                    self.handle_sync_seekbar)
        self.bus.on("mycroft.audio.queue_end",
                    self.handle_playback_ended)

        self.register_gui_handlers()

        # audio service GUI player plugin
        # (mycroft version lives in playback control skill)
        self.bus.on('playback.display.video.type',
                       self.handle_adapter_video_request)
        self.bus.on('playback.display.audio.type',
                       self.handle_adapter_audio_request)
        self.bus.on('playback.display.remove',
                       self.handle_playback_ended)

    def shutdown(self):
        self.bus.remove("ovos.common_play.query.response",
                        self.handle_skill_response)
        self.bus.remove("ovos.common_play.status.update",
                        self.handle_status_change)
        self.gui.shutdown()

    # audio service plugin adapter
    def handle_adapter_video_request(self, message):
        search_qml = "Disambiguation.qml"
        media_player_qml = "MycroftVideoPlayer.qml"
        playlist_qml = "Playlist.qml"

        pages = [media_player_qml, search_qml, playlist_qml]
        self.gui.show_pages(pages, override_idle=True)

    def handle_adapter_audio_request(self, message):
        search_qml = "Disambiguation.qml"
        audiomedia_player_qml = "MycroftAudioPlayer.qml"
        playlist_qml = "Playlist.qml"
        pages = [audiomedia_player_qml, search_qml, playlist_qml]
        self._show_pages(pages)

    # searching
    def search(self, phrase, media_type=CommonPlayMediaType.GENERIC):
        self.disambiguation_playlist = Playlist()  # reset
        self.query_replies[phrase] = []
        self.query_timeouts[phrase] = self.min_timeout
        self.search_start = time.time()
        self.waiting = True
        self.bus.emit(Message('ovos.common_play.query',
                              {"phrase": phrase,
                               "question_type": media_type}))

        # old common play will send the messages expected by the official
        # mycroft stack, but skills are know to over match, dont support
        # match type, and the VIDEO is different for every skill, it may also
        # cause issues with status tracking and mess up playlists
        if self.old_cps:
            self.old_cps.send_query(phrase, media_type)

        # if there is no match type defined, lets increase timeout a bit
        # since all skills need to search
        if media_type == CommonPlayMediaType.GENERIC:
            bonus = 3  # timeout bonus
        else:
            bonus = 0

        while self.waiting and \
                time.time() - self.search_start <= self.max_timeout + bonus:
            time.sleep(0.1)

        self.waiting = False

        # convert the returned data to the expected new format, playback
        # type is consider Skill, better common_play will not handle the playback
        # life cycle but instead delegate to the skill
        if self.old_cps:
            old_style = self.old_cps.get_results(phrase)
            self.query_replies[phrase] += self._convert_to_new_style(old_style,
                                                                     media_type)

        if self.query_replies.get(phrase):
            return [s for s in self.query_replies[phrase] if s.get("results")]

        # fallback to generic media type
        if self.media_fallback and media_type != CommonPlayMediaType.GENERIC:
            LOG.debug(
                "OVOSCommonPlay falling back to CommonPlayMediaType.GENERIC")
            return self.search(phrase, media_type=CommonPlayMediaType.GENERIC)
        return []

    def search_skill(self, skill_id, phrase,
                     media_type=CommonPlayMediaType.GENERIC):
        res = [r for r in self.search(phrase, media_type)
               if r["skill_id"] == skill_id]
        if not len(res):
            return None
        return res[0]

    def play_media(self, track, disambiguation=None, playlist=None):
        self.set_now_playing(track)
        if disambiguation:
            self.disambiguation_playlist = Playlist(disambiguation)
        if playlist:
            self.playlist = Playlist(playlist)
        self.play()
        self.update_screen()

    def handle_skill_response(self, message):
        search_phrase = message.data["phrase"]
        timeout = message.data.get("timeout")
        LOG.debug(f"OVOSCommonPlay result:"
                  f" {message.data['skill_id']}")
        if not self.waiting:
            LOG.debug("  too late!! ignored in track selection process")
            LOG.warning(f"{message.data['skill_id']} is not answering fast "
                      "enough!")

        if message.data.get("searching"):
            # extend the timeout by N seconds
            if timeout and self.allow_extensions and \
                    search_phrase in self.query_timeouts:
                self.query_timeouts[search_phrase] += timeout
            # else -> expired search

        elif search_phrase in self.query_replies:
            # Collect replies until the timeout
            self.query_replies[search_phrase].append(message.data)
            for res in message.data.get("results", []):
                if res not in self.disambiguation_playlist:
                    self.disambiguation_playlist.add_entry(res)

            # abort waiting if we gathered enough results
            if time.time() - self.search_start > self.query_timeouts[
                search_phrase]:
                if self.waiting:
                    self.waiting = False
                    LOG.debug("common play query timeout, parsing results")
                return
        elif self.waiting:
            for res in message.data.get("results", []):
                if res.get("match_confidence", 0) >= self.early_stop_thresh:
                    # got a really good match, dont search further
                    LOG.info("Receiving very high confidence match, stopping "
                             "search early")
                    # allow other skills to "just miss"
                    if self.early_stop_grace_period:
                        LOG.debug(
                            f"    grace period: {self.early_stop_grace_period} seconds")
                        time.sleep(self.early_stop_grace_period)
                    self.waiting = False
                    return

    @staticmethod
    def _convert_to_new_style(results, media_type=CommonPlayMediaType.GENERIC):
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
            data["question_type"] = media_type
            data["playback"] = CommonPlayPlaybackType.SKILL
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
    def handle_status_change(self, message):
        # message.data contains the media entry from search results and in
        # addition a "status" for that entry, this can be used to control
        # the playlist or simply communicate changes from the "playback
        # backend"
        status = message.data["status"]

        if status == CommonPlayStatus.PLAYING:
            # skill is handling playback internally
            self.set_now_playing(message.data)
            self.playback_status = status
            self.active_backend = status
        elif status == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            # audio service is handling playback
            self.set_now_playing(message.data)
            self.playback_status = status
            self.active_backend = status
        elif status == CommonPlayStatus.PLAYING_OVOS:
            # ovos common play is handling playback in GUI
            self.set_now_playing(message.data)
            self.playback_status = status
            self.active_backend = status
        elif status == CommonPlayStatus.PLAYING_MYCROFTGUI:
            # mycroft gui media player is handling playback
            self.set_now_playing(message.data)
            self.playback_status = status
            self.active_backend = status


        elif status == CommonPlayStatus.DISAMBIGUATION:
            # alternative results # TODO its this 1 track or a list ?
            if message.data not in self.disambiguation_playlist:
                self.disambiguation_playlist.add_entry(message.data)
        elif status in [CommonPlayStatus.QUEUED,
                        CommonPlayStatus.QUEUED_GUI,
                        CommonPlayStatus.QUEUED_AUDIOSERVICE]:
            # audio service is handling playback and this is in playlist
            index = message.data.get('playlist_position') or -1
            if message.data not in self.playlist:
                self.playlist.add_entry(message.data, index)
            else:
                pass  # TODO re-order track aleady in playlist ?

        elif status == CommonPlayStatus.PAUSED:
            # media is not being played, but can be resumed anytime
            # a new PLAYING status should be sent once playback resumes
            self.playback_status = status
        elif status == CommonPlayStatus.BUFFERING:
            # media is buffering, might want to show in ui
            # a new PLAYING status should be sent once playback resumes
            self.playback_status = status
        elif status == CommonPlayStatus.STALLED:
            # media is stalled, might want to show in ui
            # a new PLAYING status should be sent once playback resumes
            self.playback_status = status
        elif status == CommonPlayStatus.END_OF_MEDIA:
            # if we add a repeat/loop flag this is the place to check for it
            self.playback_status = status

    def update_status(self, status):
        self.bus.emit(Message('ovos.common_play.status.update', status))

    # stream handling
    @staticmethod
    def get_stream(uri, video=False):
        real_url = None
        if is_youtube(uri):
            if not video:
                real_url = get_youtube_audio_stream(uri)
            if video or not real_url:
                real_url = get_youtube_video_stream(uri)
        return real_url or uri

    def _fake_seekbar(self):
        """ currently unused, send way too many bus messages
        TODO: remove this code chunk, keeping for reference until
        full ovos common play implementation is finished """
        track_lenth = self.audio_service.get_track_length()
        while not track_lenth:
            track_lenth = self.audio_service.get_track_length()
        self.gui["media"]["length"] = track_lenth
        while self.audio_service.is_playing:
            self.gui["media"][
                "position"] = self.audio_service.get_track_position()
            # self.update_screen()
            time.sleep(1)

    def handle_sync_seekbar(self, message):
        """ event sent by ovos audio backend plugins """
        if not self.gui.get("media"):
            self.gui["media"] = {"length": 0, "position": 0}
        self.gui["media"]["length"] = message.data["length"]
        self.gui["media"]["position"] = message.data["position"]

    # playback control
    def set_now_playing(self, track):
        """ Currently playing media """
        if isinstance(track, dict):
            track = MediaEntry.from_dict(track)
        assert isinstance(track, MediaEntry)
        self.now_playing = track
        if self.now_playing not in self.playlist:
            self.playlist.add_entry(self.now_playing)
            self.playlist.position = len(self.playlist) - 1

    def play(self):
        # fallback to playlists if there is nothing to play
        if not self.now_playing:
            if self.playlist.current_track:
                self.now_playing = self.playlist.current_track
            if self.disambiguation_playlist.current_track:
                self.now_playing = self.disambiguation_playlist.current_track
        assert isinstance(self.now_playing, MediaEntry)

        self.active_skill = self.now_playing.skill_id

        self.stop()

        # video playback configured to use mycroft media player
        if self.video_player == VideoPlayerType.MYCROFT and \
            self.now_playing.playback == CommonPlayPlaybackType.VIDEO:
            self.now_playing.playback = CommonPlayPlaybackType.GUI
        # audio playback configured to use mycroft media player
        if self.audio_player == AudioPlayerType.MYCROFT and \
                self.now_playing.playback == CommonPlayPlaybackType.AUDIO:
            self.now_playing.playback = CommonPlayPlaybackType.GUI

        if self.now_playing.playback == CommonPlayPlaybackType.GUI:
            self.now_playing.status = CommonPlayStatus.PLAYING_MYCROFTGUI
            real_url = self.get_stream(self.now_playing.uri)
            # TODO create a string Enum of supported backends, add an alias
            #  to utterance arg name.
            #  user utterance should be parsed, but that logic was
            #  never finished and it just checks
            #       if utterance(arg) in utterance(user play request)
            # send it to the mycroft gui media subsystem
            self.audio_service.play(real_url, utterance="mycroft_mediaplayer")
        elif self.now_playing.playback == CommonPlayPlaybackType.AUDIO:
            self.now_playing.status = CommonPlayStatus.PLAYING_AUDIOSERVICE
            real_url = self.get_stream(self.now_playing.uri)
            # we explicitly want to use vlc for audio only output in this case
            self.audio_service.play(real_url, utterance="vlc")
            # ovos_vlc sends a live update from audio service, not needed
            # create_daemon(self._fake_seekbar)
        elif self.now_playing.playback == CommonPlayPlaybackType.SKILL:
            self.now_playing.status = CommonPlayStatus.PLAYING
            if data.get("is_old_style"):
                self.bus.emit(Message('play:start',
                                      {"skill_id": self.now_playing.skill_id,
                                       "callback_data": self.now_playing.as_dict,
                                       "phrase": self.now_playing.phrase}))
            else:
                self.bus.emit(Message(
                    f'ovos.common_play.{self.now_playing.skill_id}.play',
                    self.now_playing.as_dict))
        elif self.now_playing.playback == CommonPlayPlaybackType.VIDEO:
            self.now_playing.status = CommonPlayStatus.PLAYING_OVOS
        else:
            raise ValueError("invalid playback request")

    def play_next(self):
        if len(self.playlist) > 1:
            self.playlist.next_track()
            self.set_now_playing(self.playlist.current_track)
            self.play()
        elif len(self.disambiguation_playlist) > 1:
            self.disambiguation_playlist.next_track()
            self.set_now_playing(self.disambiguation_playlist.current_track)
            self.play()
        else:
            LOG.debug("requested next, but there aren't any more tracks")

    def play_prev(self):
        if len(self.playlist) > 1:
            self.playlist.prev_track()
            self.set_now_playing(self.playlist.current_track)
            self.play()
        elif len(self.disambiguation_playlist) > 1:
            self.disambiguation_playlist.prev_track()
            self.set_now_playing(self.disambiguation_playlist.current_track)
            self.play()
        else:
            LOG.debug("requested previous, but already in 1st track")

    def pause(self):
        self.update_status({"status": CommonPlayStatus.PAUSED})
        if self.active_backend == CommonPlayStatus.PLAYING_OVOS:
            self.gui.pause_video()
        elif self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.pause()
        elif self.active_backend is not None:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.pause'))

    def resume(self):
        if self.active_backend == CommonPlayStatus.PLAYING_OVOS:
            self.gui.resume_video()
        elif self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.resume()
        elif self.active_backend is not None:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.resume'))
        self.update_status({"status": self.active_backend})

    def stop(self):
        # NOTE: these checks have been removed in case only the skills
        # service is restarted, in that case the active_backend can not be used
        #if self.active_backend == CommonPlayStatus.PLAYING_OVOS:
        self.gui.stop_video()
        #elif self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
        self.audio_service.stop()
        #elif self.active_backend is not None:
        self.bus.emit(Message(f'ovos.common_play.{self.active_skill}.stop'))

        self.update_status({"status": CommonPlayStatus.END_OF_MEDIA})
        stopped = self.active_backend is not None
        self.active_backend = None
        self.active_skill = None
        return stopped

    # ######### VIDEO integration ###############
    def register_gui_handlers(self):
        self.gui.register_handler('ovos.common_play.play',
                                  self.handle_click_resume)
        self.gui.register_handler('ovos.common_play.pause',
                                  self.handle_click_pause)
        self.gui.register_handler('ovos.common_play.next',
                                  self.handle_click_next)
        self.gui.register_handler('ovos.common_play.previous',
                                  self.handle_click_previous)
        self.gui.register_handler('ovos.common_play.seek',
                                  self.handle_click_seek)
        self.gui.register_handler(
            'ovos.common_play.video.media.playback.ended',
            self.handle_playback_ended)

        self.gui.register_handler('ovos.common_play.playlist.play',
                                  self.handle_play_from_playlist)
        self.gui.register_handler('ovos.common_play.search.play',
                                  self.handle_play_from_search)

    def _show_pages(self, pages):
        search_results = [e.info for e in
                          sorted(self.disambiguation_playlist.entries,
                                 key=lambda k: k.match_confidence,
                                 reverse=True)
                          if e.match_confidence >= self.min_score]
        self.gui["searchModel"] = {
            "data": search_results
        }
        self.gui["playlistModel"] = {
            "data": [e.info for e in self.playlist.entries]
        }
        self.gui.show_pages(pages, override_idle=True)

    def update_screen(self, search=None, media=None, playlist=None, page=0):
        search_qml = "Disambiguation.qml"
        player_qml = "AudioPlayer.qml"
        media_player_qml = "MycroftVideoPlayer.qml"
        audiomedia_player_qml = "MycroftAudioPlayer.qml"
        playlist_qml = "Playlist.qml"
        video_player_qml = "VideoPlayer.qml"


        # remove previous pages TODO is this needed? why?
        pages = [player_qml, search_qml, playlist_qml,
                 video_player_qml, audiomedia_player_qml]
        self.gui.remove_pages(pages)

        # gui data shared by audio/video
        self.gui["media"] = self.now_playing.info
        self.gui["media"]["status"] = "Playing"
        self.gui["title"] = self.now_playing.title
        self.gui["bg_image"] = self.now_playing.bg_image

        # TODO config options for different video players (?)
        #   simple player (current) vs mycroft media player
        # TODO deprecate VIDEO while in alpha (?) in favor of GUI (?)
        if self.now_playing.playback == CommonPlayPlaybackType.VIDEO:
            self.gui["stream"] = self.get_stream(self.now_playing.uri,
                                                 video=True)
            pages = [video_player_qml, search_qml, playlist_qml]
        elif self.now_playing.playback == CommonPlayPlaybackType.GUI:
            # handled by a seperate bus event sent by plugin
            return
        # display "now playing" music page
        # tries to keep in sync with audio service
        else:
            self.gui["media"]["status"] = "Stopped"
            self.gui["stream"] = None  # stop any previous VIDEO playback
            pages = [player_qml, search_qml, playlist_qml]

        self._show_pages(pages)

    #  gui <-> audio service
    def handle_click_pause(self, message):
        self.audio_service.pause()
        self.gui["media"]["status"] = "Paused"

    def handle_click_resume(self, message):
        self.audio_service.resume()
        self.gui["media"]["status"] = "Playing"

    def handle_click_next(self, message):
        self.play_next()

    def handle_click_previous(self, message):
        self.play_prev()

    def handle_click_seek(self, message):
        position = message.data.get("seekValue", "")
        if position:
            self.audio_service.set_track_position(position / 1000)
            self.gui["media"]["position"] = position
            # self.update_screen()

    def handle_playback_ended(self, message):
        search_qml = "Disambiguation.qml"
        self.gui.release()
        # show search results, release screen after 15 seconds
        self.gui.show_pages([search_qml], 0, override_idle=15)
        self.update_status({"status": CommonPlayStatus.END_OF_MEDIA})

    # gui <-> playlists
    def handle_play_from_playlist(self, message):
        # TODO playlist handling (index pointer)
        media = message.data["playlistData"]
        self.set_now_playing(media)
        self.play()
        self.update_screen()

    def handle_play_from_search(self, message):
        media = message.data["playlistData"]
        self.set_now_playing(media)
        self.play()
        self.update_screen()


if __name__ == "__main__":
    from pprint import pprint

    cps = OVOSCommonPlaybackInterface(max_timeout=10, min_timeout=2)

    # test lovecraft skills
    pprint(cps.search_skill("skill-omeleto", "movie",
                            CommonPlayMediaType.SHORT_FILM))

    exit()
    pprint(cps.search("the thing in the doorstep"))

    pprint(cps.search("dagon", CommonPlayMediaType.VIDEO))

    pprint(cps.search("dagon hp lovecraft"))
