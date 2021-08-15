from enum import IntEnum

from ovos_utils.gui import GUIInterface
from ovos_utils.messagebus import get_mycroft_bus


class CommonPlayPlaybackType(IntEnum):
    SKILL = 0  # skills handle playback whatever way they see fit,
               # eg spotify / mycroft common play
    VIDEO = 1  # Video results, player configurable in skill,
               # TODO by default GUI Media framework (?)
    AUDIO = 2  # Results should be played audio only (audio service)

    # Results should be played with the Mycroft Media framework
    # https://github.com/MycroftAI/mycroft-gui/pull/97
    MEDIA_VIDEO = 3
    MEDIA_WEB = 4  # webview in browser
    MEDIA_AUDIO = 4  # play audio, but using GUI

    UNDEFINED = 100  # data not available,
                     # hopefully status will be updated soon..


class CommonPlayMatchConfidence(IntEnum):
    EXACT = 95
    VERY_HIGH = 90
    HIGH = 80
    AVERAGE_HIGH = 70
    AVERAGE = 50
    AVERAGE_LOW = 30
    LOW = 15
    VERY_LOW = 1


class CommonPlayStatus(IntEnum):
    DISAMBIGUATION = 1  # not queued for playback, show in gui
    PLAYING = 20  # Skill is handling playback internally
    PLAYING_AUDIOSERVICE = 21  # Skill forwarded playback to audio service
    PLAYING_OVOS = 22  # Skill forwarded playback to ovos common play
    PLAYING_MYCROFTGUI = 23  # Skill forwarded playback to enclosure
    QUEUED = 30  # Waiting playback to be handled inside skill
    QUEUED_AUDIOSERVICE = 31  # Waiting playback in audio service
    QUEUED_GUI = 32  # Waiting playback in gui
    QUEUED_ENCLOSURE = 33  # Waiting for playback in enclosure
    PAUSED = 40  # media paused but ready to resume
    STALLED = 60  # playback has stalled, reason may be unknown
    BUFFERING = 61  # media is buffering from an external source
    END_OF_MEDIA = 90  # playback finished, is the default state when CPS loads


class CommonPlayMediaType(IntEnum):
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


class CommonPlayTracker:
    def __init__(self, bus=None, gui=None):
        self.bus = bus or get_mycroft_bus()
        self.bus.on("ovos.common_play.query.response",
                    self.handle_cps_response)
        self.bus.on("ovos.common_play.status.update",
                    self.handle_cps_status_change)
        self.bus.on('ovos.common_play.play',
                    self.handle_click_resume)
        self.bus.on('ovos.common_play.pause',
                    self.handle_click_pause)
        self.bus.on('ovos.common_play.next',
                    self.handle_click_next)
        self.bus.on('ovos.common_play.previous',
                    self.handle_click_previous)
        self.bus.on('ovos.common_play.seek',
                    self.handle_click_seek)

        self.gui = gui or GUIInterface("ovos.common_play", bus=self.bus)
        self.register_gui_handlers()

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

        self.gui.register_handler('ovos.common_play.playlist.play',
                                  self.handle_play_from_playlist)
        self.gui.register_handler('ovos.common_play.search.play',
                                  self.handle_play_from_search)

    def shutdown(self):
        self.bus.remove("ovos.common_play.query.response",
                        self.handle_cps_response)
        self.bus.remove("ovos.common_play.status.update",
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
