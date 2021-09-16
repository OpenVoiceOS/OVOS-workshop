from ovos_utils.gui import GUIInterface
from ovos_utils.messagebus import get_mycroft_bus


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

        self.gui.register_handler('ovos.common_play.player.playlist.play',
                                  self.handle_play_from_playlist)
        self.gui.register_handler('ovos.common_play.player.search.play',
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
