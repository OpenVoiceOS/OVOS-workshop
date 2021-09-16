from ovos_utils.gui import is_gui_connected, is_gui_running
from ovos_utils.log import LOG
from ovos_utils.messagebus import Message
from ovos_utils.skills.audioservice import AudioServiceInterface
from ovos_workshop.frameworks.playback.gui import OVOSMediaPlayerGUI
from ovos_workshop.frameworks.playback.playlists import Playlist, MediaEntry
from ovos_workshop.frameworks.playback.search import OVOSMediaSearch
from ovos_workshop.frameworks.playback.settings import CommonPlaySettings
from ovos_workshop.frameworks.playback.status import *


class NowPlaying(MediaEntry):
    def __init__(self, player):
        self._player = player
        super(NowPlaying, self).__init__()
        self.bus.on("ovos.common_play.track.state",
                    self.handle_track_state_change)
        self.bus.on("ovos.common_play.playback_time",
                    self.handle_sync_seekbar)
        self.bus.on('gui.player.media.service.get.meta',
                    self.handle_player_metadata_request)
        self.bus.on('mycroft.audio.service.track_info_reply',
                    self.handle_sync_trackinfo)

    @property
    def bus(self):
        return self._player.bus

    def shutdown(self):
        self.bus.remove("ovos.common_play.track.state",
                        self.handle_track_state_change)
        self.bus.remove("ovos.common_play.playback_time",
                        self.handle_sync_seekbar)
        self.bus.remove('gui._player.media.service.get.meta',
                        self.handle_player_metadata_request)
        self.bus.remove('mycroft.audio.service.track_info_reply',
                        self.handle_sync_trackinfo)

    def update(self, entry, skipkeys=None):
        super(NowPlaying, self).update(entry, skipkeys)
        # sync with gui media player on track change
        self.bus.emit(Message("gui.player.media.service.set.meta",
                              {"title": self.title,
                               "image": self.image,
                               "artist": self.artist}))

    # events from gui_player/audio_service
    def handle_player_metadata_request(self, message):
        self.bus.emit(message.reply("gui.player.media.service.set.meta",
                                    {"title": self.title,
                                     "image": self.image,
                                     "artist": self.artist}))

    def handle_track_state_change(self, message):
        status = message.data["state"]
        self.status = status
        for k in TrackState:
            if k == status:
                LOG.info(f"TrackState changed: {repr(k)}")

        if status == TrackState.PLAYING_SKILL:
            # skill is handling playback internally
            pass
        elif status == TrackState.PLAYING_AUDIOSERVICE:
            # audio service is handling playback
            pass
        elif status == TrackState.PLAYING_VIDEO:
            # ovos common play is handling playback in GUI
            pass
        elif status == TrackState.PLAYING_AUDIO:
            # ovos common play is handling playback in GUI
            pass

        elif status == TrackState.DISAMBIGUATION:
            # alternative results # TODO its this 1 track or a list ?
            pass
        elif status in [TrackState.QUEUED_SKILL,
                        TrackState.QUEUED_VIDEO,
                        TrackState.QUEUED_AUDIOSERVICE]:
            # audio service is handling playback and this is in playlist
            pass

    def handle_sync_seekbar(self, message):
        """ event sent by ovos audio backend plugins """
        self.length = message.data["length"]
        self.position = message.data["position"]

    def handle_sync_trackinfo(self, message):
        self.update(message.data)


class OVOSMediaPlayer:
    def __init__(self, bus, settings=None, audio_service=None):
        self.bus = bus
        self.state = PlayerState.STOPPED
        self.media_state = MediaState.NO_MEDIA
        self.settings = settings or CommonPlaySettings()
        self.audio_service = audio_service or AudioServiceInterface(self.bus)
        self.playlist = Playlist()
        self.repeat = False
        self.shuffle = False
        self.now_playing = NowPlaying(self)
        self.media = OVOSMediaSearch(self)
        self.gui = OVOSMediaPlayerGUI(self)
        self.register_bus_handlers()

    def register_bus_handlers(self):
        self.bus.on('recognizer_loop:record_begin', self.handle_duck_request)
        self.bus.on('recognizer_loop:record_end', self.handle_unduck_request)

        # mycroft-gui media service
        self.bus.on('gui.player.media.service.sync.status',
                    self.handle_player_state_update)
        self.bus.on("gui.player.media.service.get.next",
                    self.handle_next_request)
        self.bus.on("gui.player.media.service.get.previous",
                    self.handle_prev_request)
        self.bus.on("gui.player.media.service.get.repeat",
                    self.handle_repeat_toggle_request)
        self.bus.on("gui.player.media.service.get.shuffle",
                    self.handle_shuffle_toggle_request)

        # ovos video player qml
        self.bus.on('ovos.common_play.video.ended',
                    self.handle_playback_ended)

        # ovos common play bus api
        self.bus.on('ovos.common_play.player.state',
                    self.handle_player_state_update)
        self.bus.on('ovos.common_play.media.state',
                    self.handle_player_media_update)
        self.bus.on('ovos.common_play.play',
                    self.handle_play_request)
        self.bus.on('ovos.common_play.pause',
                    self.handle_pause_request)
        self.bus.on('ovos.common_play.resume',
                    self.handle_resume_request)
        self.bus.on('ovos.common_play.next',
                    self.handle_next_request)
        self.bus.on('ovos.common_play.previous',
                    self.handle_prev_request)
        self.bus.on('ovos.common_play.seek',
                    self.handle_seek_request)
        self.bus.on('ovos.common_play.playlist.set',
                    self.handle_playlist_set_request)
        self.bus.on('ovos.common_play.playlist.clear',
                    self.handle_playlist_clear_request)
        self.bus.on('ovos.common_play.playlist.queue',
                    self.handle_playlist_queue_request)
        self.bus.on('ovos.common_play.duck',
                    self.handle_duck_request)
        self.bus.on('ovos.common_play.unduck',
                    self.handle_unduck_request)

    @property
    def active_skill(self):
        return self.now_playing.skill_id

    @property
    def active_backend(self):
        return self.now_playing.playback

    @property
    def tracks(self):
        return self.playlist.entries

    @property
    def disambiguation(self):
        return self.media.search_playlist.entries

    # state
    def set_media_state(self, state):
        if state == self.media_state:
            return
        self.media_state = state
        self.bus.emit(Message("ovos.common_play.media.state",
                              {"state": self.media_state}))

    def set_player_state(self, state):
        if state == self.state:
            return
        self.state = state
        # TODO remove "media" key
        if state == PlayerState.PLAYING:
            self.gui["status"] = "Playing"
        if state == PlayerState.PAUSED:
            self.gui["status"] = "Paused"
        if state == PlayerState.STOPPED:
            self.gui["status"] = "Stopped"
        self.bus.emit(Message("ovos.common_play.player.state",
                              {"state": self.state}))

    def set_now_playing(self, track):
        """ Currently playing media """
        self.set_media_state(MediaState.LOADING_MEDIA)
        self.now_playing.update(track)
        if self.now_playing not in self.playlist:
            self.playlist.add_entry(self.now_playing)
            self.playlist.position = len(self.playlist) - 1

    # stream handling
    def validate_stream(self):
        self.set_media_state(MediaState.LOADING_MEDIA)
        try:
            self.now_playing.extract_stream()
        except Exception as e:
            LOG.exception(e)
            self.set_media_state(MediaState.INVALID_MEDIA)
            return False
        has_gui = is_gui_running() or is_gui_connected(self.bus)
        if not has_gui or self.settings.force_audioservice:
            # No gui, so lets force playback to use audio only
            self.now_playing.playback = PlaybackType.AUDIO_SERVICE
        self.gui["stream"] = self.now_playing.uri
        self.gui.update_current_track()
        return True

    def on_invalid_media(self):
        self.gui.show_playback_error()
        self.play_next()

    # media controls
    def play_media(self, track, disambiguation=None, playlist=None):
        self.pause()  # make it more responsive
        if disambiguation:
            self.media.search_playlist = Playlist(disambiguation)
            self.media.search_playlist.sort_by_conf()
        if playlist:
            self.playlist = Playlist(playlist)
        self.gui.update_search_results()
        self.gui.update_playlist()
        self.set_now_playing(track)
        self.play()

    def play(self):
        self.gui.show_player()
        if not self.validate_stream():
            self.on_invalid_media()
            return

        if self.active_backend in [PlaybackType.AUDIO,
                                   PlaybackType.AUDIO_SERVICE]:
            LOG.debug("Requesting playback: PlaybackType.AUDIO")
            if self.active_backend == PlaybackType.AUDIO_SERVICE:
                # we explicitly want to use vlc for audio only output
                self.audio_service.play(self.now_playing.uri, utterance="vlc")
                self.bus.emit(Message("ovos.common_play.track.state", {
                    "state": TrackState.PLAYING_AUDIOSERVICE}))
            elif is_gui_running():
                # handle audio natively in mycroft-gui
                self.bus.emit(Message("gui.player.media.service.play", {
                    "track": self.now_playing.uri,
                    "mime": self.now_playing.mimetype,
                    "repeat": False}))
                self.bus.emit(Message("ovos.common_play.track.state", {
                    "state": TrackState.PLAYING_AUDIO}))
        elif self.active_backend == PlaybackType.SKILL:
            LOG.debug("Requesting playback: PlaybackType.SKILL")
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
            self.bus.emit(Message("ovos.common_play.track.state", {
                "state": TrackState.PLAYING_SKILL}))
        elif self.active_backend == PlaybackType.VIDEO:
            LOG.debug("Requesting playback: PlaybackType.VIDEO")
            self.set_player_state(PlayerState.PLAYING)
            self.bus.emit(Message("ovos.common_play.track.state", {
                "state": TrackState.PLAYING_VIDEO}))
        else:
            raise ValueError("invalid playback request")
        self.set_media_state(MediaState.LOADED_MEDIA)

    def play_next(self):
        self.pause()  # make more responsive
        self.set_media_state(MediaState.LOADING_MEDIA)
        n_tracks = len(self.playlist)
        n_tracks2 = len(self.media.search_playlist)
        # contains entries, and is not at end of playlist
        if n_tracks > 1 and self.playlist.position != n_tracks - 1:
            self.playlist.next_track()
            self.set_now_playing(self.playlist.current_track)
            LOG.info(f"Next track index: {self.playlist.position}")
            self.play()
        elif n_tracks2 > 1 and \
                self.media.search_playlist.position != n_tracks2 - 1:
            self.media.search_playlist.next_track()
            self.set_now_playing(
                self.media.search_playlist.current_track)
            LOG.info(
                f"Next search index: {self.media.search_playlist.position}")
            self.play()
        else:
            LOG.info("requested next, but there aren't any more tracks")
            self.gui.handle_end_of_playback()

    def play_prev(self):
        self.pause()  # make more responsive
        self.set_media_state(MediaState.LOADING_MEDIA)
        # contains entries, and is not at start of playlist
        if len(self.playlist) > 1 and self.playlist.position != 0:
            self.playlist.prev_track()
            self.set_now_playing(self.playlist.current_track)
            LOG.debug(f"Previous track index: {self.playlist.position}")
            self.play()
        elif len(self.media.search_playlist) > 1 and \
                self.media.search_playlist.position != 0:
            self.media.search_playlist.prev_track()
            self.set_now_playing(
                self.media.search_playlist.current_track)
            LOG.debug(f"Previous search index: "
                      f"{self.media.search_playlist.position}")
            self.play()
        else:
            LOG.debug("requested previous, but already in 1st track")

    def pause(self):
        LOG.debug(f"Pausing playback: {self.active_backend}")
        if self.active_backend in [PlaybackType.AUDIO_SERVICE,
                                   PlaybackType.UNDEFINED]:
            self.audio_service.pause()
        if self.active_backend in [PlaybackType.AUDIO,
                                   PlaybackType.VIDEO,
                                   PlaybackType.UNDEFINED]:
            self.bus.emit(Message("gui.player.media.service.pause"))
        if self.active_backend in [PlaybackType.SKILL,
                                   PlaybackType.UNDEFINED]:
            self.bus.emit(Message(f'ovos.common_play'
                                  f'.{self.active_skill}.pause'))
        self.set_player_state(PlayerState.PAUSED)

    def resume(self):
        LOG.debug(f"Resuming playback: {self.active_backend}")
        if self.active_backend in [PlaybackType.AUDIO_SERVICE,
                                   PlaybackType.UNDEFINED]:
            self.audio_service.resume()

        if self.active_backend in [PlaybackType.SKILL,
                                   PlaybackType.UNDEFINED]:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.resume'))

        if self.active_backend in [PlaybackType.AUDIO,
                                   PlaybackType.VIDEO,
                                   PlaybackType.UNDEFINED]:
            self.bus.emit(Message('gui.player.media.service.resume'))
        self.set_player_state(PlayerState.PLAYING)

    def seek(self, position):
        if self.active_backend in [PlaybackType.AUDIO_SERVICE,
                                   PlaybackType.UNDEFINED]:
            self.audio_service.set_track_position(position / 1000)

    def stop(self):
        LOG.debug("Stopping playback")
        if self.active_backend in [PlaybackType.AUDIO_SERVICE,
                                   PlaybackType.SKILL,
                                   PlaybackType.UNDEFINED]:
            self.audio_service.stop()
        if self.active_backend in [PlaybackType.SKILL,
                                   PlaybackType.UNDEFINED]:
            self.bus.emit(
                Message(f'ovos.common_play.{self.active_skill}.stop'))
        if self.active_backend in [PlaybackType.AUDIO,
                                   PlaybackType.VIDEO,
                                   PlaybackType.UNDEFINED]:
            self.bus.emit(Message("gui.player.media.service.stop"))
        self.set_player_state(PlayerState.STOPPED)

    def reset(self):
        self.stop()
        self.playlist = Playlist()
        self.media.clear()
        self.set_media_state(MediaState.NO_MEDIA)

    def shutdown(self):
        self.stop()
        self.now_playing.shutdown()
        self.gui.shutdown()
        self.media.shutdown()
        self.bus.remove('recognizer_loop:record_begin',
                        self.handle_duck_request)
        self.bus.remove('recognizer_loop:record_end', self.handle_unduck_request)
        self.bus.remove('gui.player.media.service.sync.status',
                        self.handle_player_state_update)
        self.bus.remove("gui.player.media.service.get.next",
                        self.handle_next_request)
        self.bus.remove("gui.player.media.service.get.previous",
                        self.handle_prev_request)

    # player -> common play
    def handle_player_state_update(self, message):
        state = message.data.get("state")
        if state == self.state:
            return
        for k in PlayerState:
            if k == state:
                LOG.info(f"PlayerState changed: {repr(k)}")
        if state == PlayerState.PLAYING:
            self.state = PlayerState.PLAYING
            self.set_media_state(MediaState.BUFFERING_MEDIA)
        if state == PlayerState.PAUSED:
            self.state = PlayerState.PAUSED
        if state == PlayerState.STOPPED:
            # TODO remove once we have a new event from gui player for end of
            #  media
            if self.state == PlayerState.PLAYING:
                self.set_media_state(MediaState.END_OF_MEDIA)
            self.state = PlayerState.STOPPED

    def handle_player_media_update(self, message):
        state = message.data.get("state")
        if state == self.media_state:
            return
        for k in MediaState:
            if k == state:
                LOG.info(f"MediaState changed: {repr(k)}")
        self.media_state = state
        if state == MediaState.END_OF_MEDIA:
            self.handle_playback_ended(message)

    def handle_playback_ended(self, message):
        LOG.debug("Playback ended")
        if self.settings.autoplay:
            self.play_next()
            return
        self.stop()
        self.gui.handle_end_of_playback(message)

    # ovos common play bus api requests
    def handle_play_request(self, message):
        LOG.debug("Received external OVOS playback request")
        if message.data.get("tracks"):
            # backwards compat / old style
            playlist = disambiguation = message.data["tracks"]
            media = playlist[0]
        else:
            media = message.data.get("media")
            playlist = message.data.get("playlist") or [media]
            disambiguation = message.data.get("disambiguation") or [media]
        self.play_media(media, disambiguation, playlist)

    def handle_pause_request(self, message):
        self.pause()

    def handle_resume_request(self, message):
        self.resume()

    def handle_seek_request(self, message):
        # usually sent by audio service player GUI
        position = message.data.get("seekValue", "")
        if position:
            self.gui["position"] = position
            self.seek(position)

    def handle_next_request(self, message):
        self.play_next()

    def handle_prev_request(self, message):
        self.play_prev()

    # playlist control bus api
    def handle_repeat_toggle_request(self, message):
        self.repeat = not self.repeat
        LOG.info(f"Repeat: {self.repeat}")

    def handle_shuffle_toggle_request(self, message):
        self.shuffle = not self.shuffle
        LOG.info(f"Shuffle: {self.shuffle}")

    def handle_playlist_set_request(self, message):
        self.playlist = Playlist()
        self.handle_playlist_queue_request(message)

    def handle_playlist_queue_request(self, message):
        for track in message.data["tracks"]:
            self.playlist.add_entry(track)

    def handle_playlist_clear_request(self, message):
        self.playlist = Playlist()
        self.set_media_state(MediaState.NO_MEDIA)

    # audio ducking
    def handle_duck_request(self, message):
        if self.state == PlayerState.PLAYING:
            self.pause()

    def handle_unduck_request(self, message):
        if self.state == PlayerState.PAUSED:
            self.resume()
