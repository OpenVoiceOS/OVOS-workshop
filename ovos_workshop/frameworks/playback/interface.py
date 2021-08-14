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
                 min_score=50):
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
                             disambiguation GUI page
        """
        self.bus = bus or get_mycroft_bus()
        self.audio_service = audio_service or AudioServiceInterface(self.bus)
        self.gui = gui or GUIInterface("ovos.common_play", bus=self.bus)

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
                    self.handle_cps_response)
        self.bus.on("ovos.common_play.status.update",
                    self.handle_cps_status_change)
        self.bus.on("ovos.common_play.playback_time",
                    self.handle_sync_seekbar)
        self.bus.on("mycroft.audio.queue_end",
                    self.handle_playback_ended)

        self.register_gui_handlers()

    def shutdown(self):
        self.bus.remove("ovos.common_play.query.response",
                        self.handle_cps_response)
        self.bus.remove("ovos.common_play.status.update",
                        self.handle_cps_status_change)
        self.gui.shutdown()

    def handle_playback_ended(self, message):
        self.update_status({"status": CommonPlayStatus.END_OF_MEDIA})

        search_qml = "Disambiguation.qml"
        player_qml = "AudioPlayer.qml"
        video_player_qml = "VideoPlayer.qml"
        playlist_qml = "Playlist.qml"
        # remove previous pages
        pages = [player_qml, playlist_qml, video_player_qml]
        self.gui.remove_pages(pages)
        # show search results, release screen after 15 seconds
        self.gui.show_pages([search_qml], 0, override_idle=15)

    def handle_cps_response(self, message):
        search_phrase = message.data["phrase"]
        timeout = message.data.get("timeout")
        LOG.debug(f"OVOSCommonPlay received results:"
                  f" {message.data['skill_id']}")

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

    def search(self, phrase, media_type=CommonPlayMediaType.GENERIC):
        self.query_replies[phrase] = []
        self.query_timeouts[phrase] = self.min_timeout
        self.search_start = time.time()
        self.waiting = True
        self.bus.emit(Message('ovos.common_play.query',
                              {"phrase": phrase,
                               "question_type": media_type}))

        # old common play will send the messages expected by the official
        # mycroft stack, but skills are know to over match, dont support
        # match type, and the GUI is different for every skill, it may also
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
        # type is consider Skill, better cps will not handle the playback
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
        self._update_current_media(track)
        if disambiguation:
            self.disambiguation_playlist = Playlist(disambiguation)
        if playlist:
            self.playlist = Playlist(playlist)
        self.play()

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
    def _update_current_media(self, track):
        """ Currently playing media """
        if isinstance(track, dict):
            track = MediaEntry.from_dict(track)
        assert isinstance(track, MediaEntry)
        self.now_playing = track

    def _update_playlist(self, data):
        """ List of queued media """
        index = data.get('playlist_position') or -1
        if data not in self.playlist:
            self.playlist.add_entry(data, index)
        else:
            pass # TODO re-order track aleady in playlist ?

    def handle_cps_status_change(self, message):
        # message.data contains the media entry from search results and in
        # addition a "status" for that entry, this can be used to control
        # the playlist or simply communicate changes from the "playback
        # backend"
        status = message.data["status"]

        if status == CommonPlayStatus.PLAYING:
            # skill is handling playback internally
            self._update_current_media(message.data)
            self.playback_status = status
            self.active_backend = status
        elif status == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            # audio service is handling playback
            self._update_current_media(message.data)
            self.playback_status = status
            self.active_backend = status
        elif status == CommonPlayStatus.PLAYING_GUI:
            # gui is handling playback
            self._update_current_media(message.data)
            self.playback_status = status
            self.active_backend = status

        elif status == CommonPlayStatus.DISAMBIGUATION:
            # alternative results # TODO its this 1 track or a list ?
            if message.data not in self.disambiguation_playlist:
                self.disambiguation_playlist.add_entry(message.data)
        elif status == CommonPlayStatus.QUEUED:
            # skill is handling playback and this is in playlist
            self._update_playlist(message.data)
        elif status == CommonPlayStatus.QUEUED_GUI:
            # gui is handling playback and this is in playlist
            self._update_playlist(message.data)
        elif status == CommonPlayStatus.QUEUED_AUDIOSERVICE:
            # audio service is handling playback and this is in playlist
            self._update_playlist(message.data)

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

    # playback control
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
        self.gui["media"]["length"] = message.data["length"]
        self.gui["media"]["position"] = message.data["position"]

    def play(self):
        assert isinstance(self.now_playing, MediaEntry)
        self.active_skill = self.now_playing.skill_id

        self.stop()

        if self.now_playing.playback == CommonPlayPlaybackType.AUDIO:
            self.now_playing.status = CommonPlayStatus.PLAYING_AUDIOSERVICE
            real_url = self.get_stream(self.now_playing.uri)
            self.audio_service.play(real_url)
            # TODO - live update from audio service
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
        elif self.now_playing.playback == CommonPlayPlaybackType.GUI:
            self.now_playing.status = CommonPlayStatus.PLAYING_GUI
        else:
            raise ValueError("invalid playback request")

        self.gui["media"] = self.now_playing.info
        self.gui["media"]["status"] = "Playing"
        self.gui["title"] = self.now_playing.title
        self.gui["bg_image"] = self.now_playing.bg_image
        self.gui["stream"] = self.get_stream(self.now_playing.uri,
                                             video=True)

        # TODO proper playlist support
        self.playlist = Playlist([self.now_playing])

        self.update_screen()

    def play_next(self):
        # TODO playlist handling
        if self.active_backend == CommonPlayStatus.PLAYING_GUI:
            pass
        elif self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.next()
        elif self.active_backend is not None:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.next'))

    def play_prev(self):
        # TODO playlist handling
        if self.active_backend == CommonPlayStatus.PLAYING_GUI:
            pass
        elif self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.prev()
        elif self.active_backend is not None:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.prev'))

    def pause(self):
        self.update_status({"status": CommonPlayStatus.PAUSED})
        if self.active_backend == CommonPlayStatus.PLAYING_GUI:
            self.gui.pause_video()
        elif self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.pause()
        elif self.active_backend is not None:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.pause'))

    def resume(self):
        if self.active_backend == CommonPlayStatus.PLAYING_GUI:
            self.gui.resume_video()
        elif self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.resume()
        elif self.active_backend is not None:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.resume'))
        self.update_status({"status": self.active_backend})

    def stop(self):
        if self.active_backend == CommonPlayStatus.PLAYING_GUI:
            self.gui.stop_video()
        elif self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.stop()
        elif self.active_backend is not None:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.stop'))
        self.update_status({"status": CommonPlayStatus.END_OF_MEDIA})
        stopped = self.active_backend is not None
        self.active_backend = None
        self.active_skill = None
        return stopped

    # ######### GUI integration ###############
    def register_gui_handlers(self):
        self.gui.register_handler('ovos.common_play.gui.play',
                                  self.handle_click_resume)
        self.gui.register_handler('ovos.common_play.gui.pause',
                                  self.handle_click_pause)
        self.gui.register_handler('ovos.common_play.gui.next',
                                  self.handle_click_next)
        self.gui.register_handler('ovos.common_play.gui.previous',
                                  self.handle_click_previous)
        self.gui.register_handler('ovos.common_play.gui.seek',
                                  self.handle_click_seek)
        self.gui.register_handler(
            'ovos.common_play.video.media.playback.ended',
            self.handle_playback_ended)

        self.gui.register_handler('ovos.common_play.gui.playlist.play',
                                  self.handle_play_from_playlist)
        self.gui.register_handler('ovos.common_play.gui.search.play',
                                  self.handle_play_from_search)

    def update_screen(self, search=None, media=None, playlist=None, page=0):
        search_qml = "Disambiguation.qml"
        player_qml = "AudioPlayer.qml"
        video_player_qml = "VideoPlayer.qml"
        playlist_qml = "Playlist.qml"

        # remove previous pages
        pages = [player_qml, search_qml, playlist_qml, video_player_qml]
        self.gui.remove_pages(pages)

        if self.now_playing.playback == CommonPlayPlaybackType.GUI:
            self.gui["playStatus"] = "play"
            pages = [video_player_qml, search_qml, playlist_qml]
        # display "now playing" music page
        else:
            pages = [player_qml, search_qml, playlist_qml]

        search_results = [e.info for e in
                          sorted(self.disambiguation_playlist.entries,
                                 key=lambda k: k.match_confidence)
                          if e.match_confidence >= self.min_score]
        self.gui["searchModel"] = {
            "data": search_results
        }
        self.gui["playlistModel"] = {
            "data": [e.info for e in self.playlist.entries]
        }
        self.gui.show_pages(pages, page, override_idle=True)

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

    def handle_play_from_playlist(self, message):
        # TODO playlist handling
        media = message.data["playlistData"]
        self._update_current_media(media)
        self.play()

    def handle_play_from_search(self, message):
        media = message.data["playlistData"]
        self._update_current_media(media)
        self.play()


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
