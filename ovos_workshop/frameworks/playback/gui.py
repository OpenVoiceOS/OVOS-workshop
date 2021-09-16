from ovos_utils.gui import is_gui_running, GUIInterface
from ovos_workshop.frameworks.playback.status import *
from ovos_utils.log import LOG


class OVOSMediaPlayerGUI(GUIInterface):
    def __init__(self, media_player):
        """
        media_player: OVOSMediaPlayer
        """
        self._player = media_player
        # the skill_id is chosen so the namespace matches the regular bus api
        # ie, the gui event "XXX" is sent in the bus as "ovos.common_play.XXX"
        super().__init__("ovos.common_play", bus=self._player.bus)
        self.register_playback_handlers()

    def register_playback_handlers(self):
        self.bus.on("ovos.common_play.playback_time",
                    self.handle_sync_seekbar)
        self.bus.on('ovos.common_play.playlist.play',
                    self.handle_play_from_playlist)
        self.bus.on('ovos.common_play.search.play',
                    self.handle_play_from_search)
        self.bus.on('ovos.common_play.collection.play',
                    self.handle_play_from_collection)

    @property
    def search_spinner_page(self):
        return "OVOSSearch.qml"

    @property
    def audio_player_page(self):
        return "OVOSAudioPlayer.qml"

    @property
    def audio_service_page(self):
        return "AudioPlayer.qml"

    @property
    def video_player_page(self):
        return "VideoPlayer.qml"

    @property
    def search_page(self):
        return "Disambiguation.qml"

    @property
    def playlist_page(self):
        return "Playlist.qml"

    def shutdown(self):
        self.bus.remove("ovos.common_play.playback_time",
                        self.handle_sync_seekbar)
        super().shutdown()

    # OVOSMediaPlayer interface
    def update_current_track(self):
        self["media"] = self._player.now_playing.info
        self["title"] = self._player.now_playing.title
        self["image"] = self._player.now_playing.image
        self["artist"] = self._player.now_playing.artist
        self["bg_image"] = self._player.now_playing.bg_image
        self["duration"] = self._player.now_playing.length
        self["position"] = self._player.now_playing.position

    def update_search_results(self):
        self["searchModel"] = {
            "data": [e.info for e in self._player.disambiguation]
        }

    def update_playlist(self):
        self["playlistModel"] = {
            "data": [e.info for e in self._player.tracks]
        }

    def show_playback_error(self):
        # TODO error page
        self.show_text("Playback error")

    def show_search_spinner(self):
        self.clear()
        self["footer_text"] = "Querying Skills\n\n"
        self.show_page(self.search_spinner_page,
                       override_idle=True,
                       override_animations=True)

    def show_player(self):
        to_remove = [self.search_spinner_page]
        if self._player.active_backend == PlaybackType.VIDEO:
            page = self.video_player_page
            to_remove += [self.audio_service_page, self.audio_player_page]
        elif self._player.active_backend == PlaybackType.AUDIO_SERVICE or \
                self._player.settings.force_audioservice:
            page = self.audio_service_page
            to_remove += [self.video_player_page, self.audio_player_page]
        elif self._player.active_backend == PlaybackType.AUDIO:
            page = self.audio_player_page
            to_remove += [self.video_player_page, self.audio_service_page]
        else:  # skill / undefined
            # TODO ?
            page = self.audio_service_page
            to_remove += [self.video_player_page, self.audio_player_page]

        self.remove_pages([p for p in to_remove if p in self.pages])
        self.show_pages([page, self.search_page, self.playlist_page],
                        index=0, override_idle=True, override_animations=True)

    # gui <-> playlists
    def handle_play_from_playlist(self, message):
        LOG.info("Playback requested from playlist results")
        media = message.data["playlistData"]
        self._player.play_media(media)

    def handle_play_from_search(self, message):
        LOG.info("Playback requested from search results")
        media = message.data["playlistData"]
        self._player.play_media(media)

    def handle_play_from_collection(self, message):
        playlist = message.data["playlistData"]
        collection = message.data["collection"]
        media = playlist[0]
        self._player.play_media(media, playlist=playlist,
                                disambiguation=collection)

    # audio service -> gui
    def handle_sync_seekbar(self, message):
        """ event sent by ovos audio backend plugins """
        self["length"] = message.data["length"]
        self["position"] = message.data["position"]

    # media player -> gui
    def handle_end_of_playback(self, message=None):
        search_qml = "Disambiguation.qml"
        self.clear()
        # show media results, release screen after 60 seconds
        self.show_page(search_qml, override_idle=60)
