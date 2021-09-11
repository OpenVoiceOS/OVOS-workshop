import random
import time

from ovos_utils.gui import is_gui_connected, is_gui_running
from ovos_utils.log import LOG
from ovos_utils.messagebus import Message, wait_for_reply
from ovos_utils.skills.audioservice import AudioServiceInterface
from ovos_workshop.frameworks.playback.playlists import Playlist, MediaEntry
from ovos_workshop.frameworks.playback.status import *
from ovos_workshop.frameworks.playback.stream_handlers import is_youtube, \
    get_youtube_audio_stream, get_youtube_video_stream, \
    get_deezer_audio_stream, get_rss_first_stream, \
    get_youtube_live_from_channel, find_mime


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
    # media types that can be safely cast to audio only streams when GUI is
    # not available
    cast2audio = [
        CommonPlayMediaType.MUSIC,
        CommonPlayMediaType.PODCAST,
        CommonPlayMediaType.AUDIOBOOK,
        CommonPlayMediaType.RADIO,
        CommonPlayMediaType.RADIO_THEATRE,
        CommonPlayMediaType.VISUAL_STORY,
        CommonPlayMediaType.NEWS
    ]

    def __init__(self, bus=None, min_timeout=1, max_timeout=5,
                 allow_extensions=True, audio_service=None, gui=None,
                 backwards_compatibility=True, media_fallback=True,
                 early_stop_conf=90, early_stop_grace_period=1.0,
                 autoplay=True):
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
        """
        self.bus = bus or get_mycroft_bus()
        self.audio_service = audio_service or AudioServiceInterface(self.bus)
        self.gui = gui or GUIInterface("ovos.common_play", bus=self.bus)

        self.autoplay = autoplay
        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
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
        self.active_searching = []

        self.playback_status = CommonPlayStatus.END_OF_MEDIA
        self.active_backend = None  # re-uses CommonPlayStatus.PLAYING_XXX
        self.active_skill = None  # skill_id currently handling playback

        self.playback_data = {"playing": None,
                              "playlist": [],
                              "disambiguation": []}

        self.search_playlist = Playlist()
        self.playlist = Playlist()
        self.now_playing = None

        self.bus.on("ovos.common_play.query.response",
                    self.handle_skill_response)
        self.bus.on("ovos.common_play.status.update",
                    self.handle_status_change)
        self.bus.on("ovos.common_play.playback_time",
                    self.handle_sync_seekbar)
        self.bus.on("ovos.common_play.skill.search_start",
                    self.handle_skill_search_start)
        self.bus.on("ovos.common_play.skill.search_end",
                    self.handle_skill_search_end)
        self.bus.on("mycroft.audio.queue_end",
                    self.handle_playback_ended)

        self.register_gui_handlers()

        # audio ducking
        self.bus.on('recognizer_loop:record_begin', self.handle_record_begin)
        self.bus.on('recognizer_loop:record_end', self.handle_record_end)

        # audio service GUI player plugin
        self.bus.on('gui.player.media.service.get.meta',
                    self.handle_guiplayer_metadata_request)
        self.bus.on('gui.player.media.service.sync.status',
                    self.handle_guiplayer_status_update)
        self.bus.on("gui.player.media.service.get.next",
                    self.handle_click_next)
        self.bus.on("gui.player.media.service.get.previous",
                    self.handle_click_previous)
        # TODO shuffle/repeat
        # self.bus.on("gui.player.media.service.get.repeat")
        # self.bus.on("gui.player.media.service.get.shuffle")

    def shutdown(self):
        # self.stop()
        # audio ducking
        self.bus.remove('recognizer_loop:record_begin',
                        self.handle_record_begin)
        self.bus.remove('recognizer_loop:record_end', self.handle_record_end)
        self.bus.remove('gui.player.media.service.get.meta',
                        self.handle_guiplayer_metadata_request)
        self.bus.remove('gui.player.media.service.sync.status',
                        self.handle_guiplayer_status_update)

        self.bus.remove("ovos.common_play.query.response",
                        self.handle_skill_response)
        self.bus.remove("ovos.common_play.status.update",
                        self.handle_status_change)
        self.gui.shutdown()

    # GUI media service player integration
    def handle_guiplayer_metadata_request(self, message):
        if self.now_playing:
            self.bus.emit(message.reply("gui.player.media.service.set.meta",
                                        {"title": self.now_playing.title,
                                         "image": self.now_playing.image,
                                         "artist": self.now_playing.artist}))

    def handle_guiplayer_status_update(self, message):
        current_state = message.data.get("state")
        if current_state == 1:
            self.update_status({"status": CommonPlayStatus.PLAYING_AUDIO})
        if current_state == 2:
            self.update_status({"status": CommonPlayStatus.PAUSED})
        if current_state == 0:
            pass
            # self.update_status({"status": CommonPlayStatus.END_OF_MEDIA})

    # audio ducking
    def handle_record_begin(self, message):
        if self.playback_status in [CommonPlayStatus.PLAYING,
                                    CommonPlayStatus.PLAYING_AUDIOSERVICE,
                                    CommonPlayStatus.PLAYING_VIDEO,
                                    CommonPlayStatus.PLAYING_AUDIO]:
            self.pause()

    def handle_record_end(self, message):
        if self.playback_status == CommonPlayStatus.PAUSED:
            self.resume()

    # searching
    def handle_skill_search_start(self, message):
        skill_id = message.data["skill_id"]
        LOG.debug(f"{message.data['skill_id']} is searching")
        if skill_id not in self.active_searching:
            self.active_searching.append(skill_id)

    def handle_skill_search_end(self, message):
        skill_id = message.data["skill_id"]
        LOG.debug(f"{message.data['skill_id']} finished search")
        if skill_id in self.active_searching:
            self.active_searching.remove(skill_id)

        # if this was the last skill end waiting period
        time.sleep(0.5)  # TODO this is hacky, but avoids a race condition in
        # case some skill just decides to respond before the others even
        # acknowledge search is starting, this gives more than enough time
        # for self.active_seaching to be populated, a better approach should
        # be employed but this works fine for now
        if not self.active_searching:
            LOG.info("Received search responses from all skills!")
            self.waiting = False

    def search(self, phrase, media_type=CommonPlayMediaType.GENERIC):
        self.gui.clear()
        self.gui["footer_text"] = "Searching Media"
        self.gui.show_page("BusyPage.qml", override_idle=True)

        self.search_playlist = Playlist()  # reset
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
            # TODO dont query skills that found results for non-generic
            #  query again
            LOG.debug(
                "OVOSCommonPlay falling back to CommonPlayMediaType.GENERIC")
            return self.search(phrase, media_type=CommonPlayMediaType.GENERIC)
        self.gui.remove_page("BusyPage.qml")
        return []

    def search_skill(self, skill_id, phrase,
                     media_type=CommonPlayMediaType.GENERIC):
        res = [r for r in self.search(phrase, media_type)
               if r["skill_id"] == skill_id]
        if not len(res):
            return None
        return res[0]

    def play_media(self, track, disambiguation=None, playlist=None):
        if self.now_playing:
            self.pause()  # make it more responsive
        if disambiguation:
            self.search_playlist = Playlist(disambiguation)
            self.search_playlist.sort_by_conf()
        if playlist:
            self.playlist = Playlist(playlist)
        self.set_now_playing(track)
        self.play()

    def handle_skill_response(self, message):
        search_phrase = message.data["phrase"]
        timeout = message.data.get("timeout")
        skill_id = message.data['skill_id']
        # LOG.debug(f"OVOSCommonPlay result: {skill_id}")

        if message.data.get("searching"):
            # extend the timeout by N seconds
            if timeout and self.allow_extensions and \
                    search_phrase in self.query_timeouts:
                self.query_timeouts[search_phrase] += timeout
            # else -> expired search

        elif search_phrase in self.query_replies:
            # Collect replies until the timeout
            if not self.waiting and not len(self.query_replies[search_phrase]):
                LOG.debug("  too late!! ignored in track selection process")
                LOG.warning(
                    f"{message.data['skill_id']} is not answering fast "
                    "enough!")

            has_gui = is_gui_running() or is_gui_connected(self.bus)
            for idx, res in enumerate(message.data.get("results", [])):
                # filter video results if GUI not connected
                if not has_gui:
                    # force allowed stream types to be played audio only
                    if res.get("media_type", "") in self.cast2audio:
                        LOG.debug("unable to use GUI, forcing result to play audio only")
                        res["playback"] = CommonPlayPlaybackType.AUDIO
                        res["match_confidence"] -= 10
                        message.data["results"][idx] = res

                if res not in self.search_playlist:
                    self.search_playlist.add_entry(res)
                    # update search UI
                    if self.waiting and res["match_confidence"] >= 30:
                        self.gui["footer_text"] = \
                            f"skill - {skill_id}\n" \
                            f"match - {res['title']}\n" \
                            f"confidence - {res['match_confidence']} "

            self.query_replies[search_phrase].append(message.data)

            # abort waiting if we gathered enough results
            # TODO ensure we have a decent confidence match, if all matches
            #  are < 50% conf extend timeout instead
            if time.time() - self.search_start > self.query_timeouts[search_phrase]:
                if self.waiting:
                    self.waiting = False
                    LOG.debug("common play query timeout, parsing results")
                    self.gui["footer_text"] = "search timeout - selecting " \
                                              "best result"
                return
        elif self.waiting:
            for res in message.data.get("results", []):
                if res.get("match_confidence", 0) >= self.early_stop_thresh:
                    # got a really good match, dont search further
                    LOG.info("Receiving very high confidence match, stopping "
                             "search early")
                    self.gui["footer_text"] = f"High confidence match! - " \
                                              f"{res['title']}"
                    # allow other skills to "just miss"
                    if self.early_stop_grace_period:
                        LOG.debug(
                            f"  - grace period: {self.early_stop_grace_period} seconds")
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
        elif status == CommonPlayStatus.PLAYING_VIDEO:
            # ovos common play is handling playback in GUI
            self.set_now_playing(message.data)
            self.playback_status = status
            self.active_backend = status
        elif status == CommonPlayStatus.PLAYING_AUDIO:
            # mycroft gui media player is handling playback
            self.set_now_playing(message.data)
            self.playback_status = status
            self.active_backend = status

        elif status == CommonPlayStatus.DISAMBIGUATION:
            # alternative results # TODO its this 1 track or a list ?
            if message.data not in self.search_playlist:
                self.search_playlist.add_entry(message.data)
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
    def _prepare_stream(self):
        uri = self.now_playing.uri
        if self.now_playing.playback == CommonPlayPlaybackType.VIDEO:
            video = True
        else:
            video = False
        meta = {}
        if uri.startswith("rss//"):
            uri = uri.replace("rss//", "")
            meta = get_rss_first_stream(uri)
            if not meta:
                LOG.error("RSS feed stream extraction failed!!!")

        if uri.startswith("deezer//"):
            uri = uri.replace("deezer//", "")
            meta = get_deezer_audio_stream(uri)
            if not meta:
                LOG.error("deezer stream extraction failed!!!")
            else:
                LOG.debug(f"deezer cache: {meta['uri']}")

        if uri.startswith("youtube.channel.live//"):
            uri = uri.replace("youtube.channel.live//", "")
            uri = get_youtube_live_from_channel(uri)
            if not uri:
                LOG.error("youtube channel live stream extraction failed!!!")
            else:
                uri = "youtube//" + uri

        if uri.startswith("youtube//") or is_youtube(uri):
            uri = uri.replace("youtube//", "")
            if not video:
                meta = get_youtube_audio_stream(uri)
            if video or not meta:
                meta = get_youtube_video_stream(uri)
            if not meta:
                LOG.error("youtube stream extraction failed!!!")
        meta = meta or {"uri": uri}

        # update media entry with new data
        for k, v in meta.items():
            if not v:
                continue
            if hasattr(self.now_playing, k):
                self.now_playing.__setattr__(k, v)
            else:
                self.now_playing.data[k] = v
        has_gui = is_gui_running() or is_gui_connected(self.bus)
        if not has_gui:
            # No gui, so lets force playback to use audio only
            # audio playback configured to use mycroft media player
            self.now_playing.playback = CommonPlayPlaybackType.AUDIO
        self.update_screen()
        return meta

    def handle_sync_seekbar(self, message):
        """ event sent by ovos audio backend plugins """
        # cast to dict for faster sync with GUI, 1 bus message instead of 3
        media = dict(self.gui.get("media") or {})
        media["length"] = message.data["length"]
        media["position"] = message.data["position"]
        media["status"] = "Playing"
        self.gui["media"] = media

    # playback control
    def set_now_playing(self, track):
        """ Currently playing media """
        if isinstance(track, dict):
            track = MediaEntry.from_dict(track)
        assert isinstance(track, MediaEntry)
        self.now_playing = track
        # sync with gui media player on track change
        self.bus.emit(Message("gui.player.media.service.set.meta",
                              {"title": self.now_playing.title,
                               "image": self.now_playing.image,
                               "artist": self.now_playing.artist}))
        if self.now_playing not in self.playlist:
            self.playlist.add_entry(self.now_playing)
            self.playlist.position = len(self.playlist) - 1

    def play(self):
        # fallback to playlists if there is nothing to play
        if not self.now_playing:
            if self.playlist.current_track:
                self.now_playing = self.playlist.current_track
            if self.search_playlist.current_track:
                self.now_playing = self.search_playlist.current_track
            if not self.now_playing:
                pass  # TODO Error screen (?)
        assert isinstance(self.now_playing, MediaEntry)

        self.active_skill = self.now_playing.skill_id

        # self.stop()

        meta = self._prepare_stream()

        if self.now_playing.playback == CommonPlayPlaybackType.AUDIO:
            LOG.debug("Requesting playback: CommonPlayPlaybackType.AUDIO")
            real_url = meta["uri"]
            if is_gui_running():
                # handle audio natively in mycroft-gui
                self.bus.emit(Message("playback.display.audio.type"))
                self.now_playing.status = CommonPlayStatus.PLAYING_AUDIO
                self.bus.emit(
                    Message(
                        "gui.player.media.service.play", {
                            "track": real_url,
                            "mime": find_mime(real_url),
                            "repeat": False}))
                self.handle_guiplayer_metadata_request(
                    Message('gui.player.media.service.get.meta'))
            else:
                # we explicitly want to use vlc for audio only output
                self.gui["media"]["position"] = 0
                self.gui["media"]["length"] = -1
                self.audio_service.play(real_url, utterance="vlc")
                self.now_playing.status = CommonPlayStatus.PLAYING_AUDIOSERVICE

            self.gui["media"]["status"] = "Playing"
        elif self.now_playing.playback == CommonPlayPlaybackType.SKILL:
            self.now_playing.status = CommonPlayStatus.PLAYING
            LOG.debug("Requesting playback: CommonPlayPlaybackType.SKILL")
            if self.now_playing.data.get("is_old_style"):
                LOG.debug("     - Mycroft common play result selected")
                self.bus.emit(Message('play:start',
                                      {"skill_id": self.now_playing.skill_id,
                                       "callback_data": self.now_playing.info,
                                       "phrase": self.now_playing.phrase}))
            else:
                self.bus.emit(Message(
                    f'ovos.common_play.{self.now_playing.skill_id}.play',
                    self.now_playing.info))
        elif self.now_playing.playback == CommonPlayPlaybackType.VIDEO:
            LOG.debug("Requesting playback: CommonPlayPlaybackType.VIDEO")
            self.now_playing.status = CommonPlayStatus.PLAYING_VIDEO
            real_url = meta["uri"]
            self.gui["stream"] = real_url
            self.gui["media"]["status"] = "Playing"  # start video playback
        else:
            raise ValueError("invalid playback request")

    def play_next(self):
        n_tracks = len(self.playlist)
        n_tracks2 = len(self.search_playlist)
        # contains entries, and is not at end of playlist
        if n_tracks > 1 and self.playlist.position != n_tracks - 1:
            self.playlist.next_track()
            self.set_now_playing(self.playlist.current_track)
            LOG.debug(f"Next track index: {self.playlist.position}")
            self.play()
        elif n_tracks2 > 1 and self.search_playlist.position != n_tracks2 - 1:
            self.search_playlist.next_track()
            self.set_now_playing(self.search_playlist.current_track)
            LOG.debug(f"Next search index: {self.search_playlist.position}")
            self.play()
        else:
            LOG.debug("requested next, but there aren't any more tracks")
            self.gui.release()
            # show search results, release screen after 60 seconds
            search_qml = "Disambiguation.qml"
            self.gui.show_page(search_qml, override_idle=60)
            self.update_status({"status": CommonPlayStatus.END_OF_MEDIA})

    def play_prev(self):
        # contains entries, and is not at start of playlist
        if len(self.playlist) > 1 and self.playlist.position != 0:
            self.playlist.prev_track()
            self.set_now_playing(self.playlist.current_track)
            LOG.debug(f"Previous track index: {self.playlist.position}")
            self.play()
        elif len(self.search_playlist) > 1 and \
                self.search_playlist.position != 0:
            self.search_playlist.prev_track()
            self.set_now_playing(self.search_playlist.current_track)
            LOG.debug(f"Previous search index: "
                      f"{self.search_playlist.position}")
            self.play()
        else:
            LOG.debug("requested previous, but already in 1st track")

    def pause(self):
        LOG.debug(f"Pausing playback: {self.active_backend}")
        if self.gui.get("media"):
            self.gui["media"]["status"] = "Paused"
        self.update_status({"status": CommonPlayStatus.PAUSED})
        self.audio_service.pause()
        self.bus.emit(Message("gui.player.media.service.pause"))
        self.bus.emit(Message(f'ovos.common_play.{self.active_skill}.pause'))

    def resume(self):
        if self.gui.get("media"):
            self.gui["media"]["status"] = "Playing"

        if not self.active_backend:
            # TODO we dont want everything to resume,
            #   eg audio + gui playing at same time
            # but we also do not know which one is being used!
            # this only happens if skill reloaded and info is still in GUI,
            # or possibly directly triggered by bus message. lets do our
            # best guess, it will correct itself in next play query
            self.active_backend = CommonPlayStatus.PLAYING_VIDEO

        if self.active_backend == CommonPlayStatus.PLAYING_AUDIOSERVICE:
            self.audio_service.resume()
        elif self.active_backend == CommonPlayStatus.PLAYING:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.resume'))
        else:
            # Mycroft Media framework
            # https://github.com/MycroftAI/mycroft-gui/pull/97
            self.bus.emit(Message('gui.player.media.service.resume'))
        LOG.debug(f"Resuming playback: {self.active_backend}")
        self.update_status({"status": self.active_backend})

    def stop(self):
        LOG.debug("Stopping playback")
        if self.gui.get("media"):
            self.gui["media"]["status"] = "Stopped"
        self.audio_service.stop()
        self.bus.emit(Message(f'ovos.common_play.{self.active_skill}.stop'))
        # Stop Mycroft Media framework
        # https://github.com/MycroftAI/mycroft-gui/pull/97
        self.bus.emit(Message("gui.player.media.service.stop"))

        self.update_status({"status": CommonPlayStatus.END_OF_MEDIA})
        stopped = self.active_backend is not None
        self.active_backend = None
        self.active_skill = None
        return stopped

    # ######### GUI integration ###############
    def register_gui_handlers(self):
        self.gui.register_handler('ovos.common_play.resume',
                                  self.handle_click_resume)
        self.gui.register_handler('ovos.common_play.pause',
                                  self.handle_click_pause)
        self.gui.register_handler('ovos.common_play.next',
                                  self.handle_click_next)
        self.gui.register_handler('ovos.common_play.previous',
                                  self.handle_click_previous)
        self.gui.register_handler('ovos.common_play.seek',
                                  self.handle_click_seek)
        # TODO something is wrong in qml, sent at wrong time
        # self.gui.register_handler(
        #     'ovos.common_play.video.media.playback.ended',
        #     self.handle_playback_ended)

        self.gui.register_handler('ovos.common_play.playlist.play',
                                  self.handle_play_from_playlist)
        self.gui.register_handler('ovos.common_play.search.play',
                                  self.handle_play_from_search)
        self.gui.register_handler('ovos.common_play.collection.play',
                                  self.handle_play_from_collection)

    def _show_pages(self, pages):
        self.gui["searchModel"] = {
            "data": [e.info for e in self.search_playlist.entries]
        }
        self.gui["playlistModel"] = {
            "data": [e.info for e in self.playlist.entries]
        }
        self.gui.show_pages(pages, override_idle=True)

    def update_screen(self, search=None, media=None, playlist=None, page=0):
        search_qml = "Disambiguation.qml"
        player_qml = "AudioPlayer.qml"
        playlist_qml = "Playlist.qml"
        video_player_qml = "VideoPlayer.qml"
        # if we have a local GUI skip the audio backend completely
        if is_gui_running():
            player_qml = "OVOSAudioPlayer.qml"

        # send gui track data
        self.gui["media"] = self.now_playing.info
        self.gui["media"]["status"] = "Playing"
        self.gui["title"] = self.now_playing.title
        self.gui["image"] = self.now_playing.image
        self.gui["artist"] = self.now_playing.artist
        self.gui["bg_image"] = self.now_playing.bg_image

        if self.now_playing.playback == CommonPlayPlaybackType.VIDEO:
            pages = [video_player_qml, search_qml, playlist_qml]
            self.gui.remove_pages(["AudioPlayer.qml", "OVOSAudioPlayer.qml"])

        # display "now playing" music page
        # tries to keep in sync with audio service
        else:
            if self.gui.get("media"):
                self.gui["media"]["status"] = "Stopped"
            self.gui["stream"] = None  # stop any previous VIDEO playback
            pages = [player_qml, search_qml, playlist_qml]
            self.gui.remove_pages(["VideoPlayer.qml"])

        self._show_pages(pages)

    #  gui <-> audio service
    def handle_click_pause(self, message):
        if not self.active_backend:
            self.active_backend = CommonPlayStatus.PLAYING_AUDIOSERVICE
        self.pause()

    def handle_click_resume(self, message):
        if not self.active_backend:
            self.active_backend = CommonPlayStatus.PLAYING_AUDIOSERVICE
        self.resume()

    def handle_click_next(self, message):
        self.play_next()

    def handle_click_previous(self, message):
        self.play_prev()

    def handle_click_seek(self, message):
        if not self.active_backend:
            self.active_backend = CommonPlayStatus.PLAYING_AUDIOSERVICE
        position = message.data.get("seekValue", "")
        if position:
            self.audio_service.set_track_position(position / 1000)
            self.gui["media"]["position"] = position

    def handle_playback_ended(self, message):
        LOG.debug("Playback ended")
        search_qml = "Disambiguation.qml"
        self.audio_service.stop()
        if self.autoplay:
            self.play_next()
            return
        self.gui.release()
        # show search results, release screen after 60 seconds
        self.gui.show_page(search_qml, override_idle=60)
        self.update_status({"status": CommonPlayStatus.END_OF_MEDIA})


    # gui <-> playlists
    def handle_play_from_playlist(self, message):
        # TODO playlist handling (move index pointer to selected track)
        media = message.data["playlistData"]
        self.set_now_playing(media)
        self.play()

    def handle_play_from_search(self, message):
        # TODO playlist handling (move index pointer to selected track)
        media = message.data["playlistData"]
        self.play_media(media)

    def handle_play_from_collection(self, message):
        # TODO playlist handling (move index pointer to selected track)
        # self.gui.clear()
        playlist = message.data["playlistData"]
        collection = message.data["collection"]
        media = playlist[0]
        self.play_media(media, playlist=playlist, disambiguation=collection)


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
