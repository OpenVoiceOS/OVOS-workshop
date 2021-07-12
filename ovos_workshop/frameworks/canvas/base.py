from time import sleep
from ovos_utils.messagebus import get_mycroft_bus
from ovos_utils.log import LOG


class AbstractCanvas:
    """
        Base class for all canvas backend implementations.
        Args:
            config: configuration dict for the instance
            bus: websocket object
    """
    def __init__(self, bus=None, config=None, name="dummy window"):
        self.name = name
        self.bus = bus or get_mycroft_bus()
        self.config = config
        self.index = 0
        self._is_windowing = False
        self.pictures = []
        self.width = 1600
        self.height = 900
        self.fullscreen = False
        self._window_start_callback = None
        self.default_picture = "https://raw.githubusercontent.com/OpenVoiceOS/ovos_assets/master/Logo/ovos-logo-512.png"

    @staticmethod
    def supported_uris():
        """
            Returns: list of supported uri types.
        """
        return ['file']  #, 'http', 'https']

    def handle_fullscreen(self, new_value, old_value):
        # window was told to change fullscreen status
        pass

    def handle_reset(self):
        # window was told to reset to default state
        # usually a logo
        if self.default_picture is not None:
            self.handle_window(self.default_picture)

    def handle_stop(self):
        # window was told to stop windowing
        self.handle_reset()

    def handle_close(self):
        # window was told to close window
        pass

    def handle_window(self, picture):
        # window was told to window picture
        pass

    def handle_clear(self):
        # window was told to clear
        # usually a black image
        pass

    def handle_height_change(self, new_value, old_value):
        # change window height in pixels
        pass

    def handle_width_change(self, new_value, old_value):
        # change window width in pixels
        pass

    def display(self):
        """
           Display self.index in Pictures List of paths
        """
        if len(self.pictures):
            pic = self.pictures[self.index]
            self.handle_window(pic)
        else:
            LOG.error("Nothing to window")

    def clear_pictures(self):
        self.pictures = []
        self.index = 0

    def add_pictures(self, picture_list):
        """
          add pics
        """
        self.pictures.extend(picture_list)

    def reset(self):
        """
            Reset Display.
        """
        self.index = 0
        self.pictures = []
        self.handle_reset()

    def clear(self):
        """
            Clear Display.
        """
        self.handle_clear()

    def next(self):
        """
            Skip to next pic in playlist.
        """
        self.index += 1
        if self.index > len(self.pictures):
            self.index = 0
        self.display()

    def previous(self):
        """
            Skip to previous pic in playlist.
        """
        self.index -= 1
        if self.index > 0:
            self.index = len(self.pictures)
        self.display()

    def lock(self):
        """
           Set Lock Flag so nothing else can window
        """
        pass

    def unlock(self):
        """
           Unset Lock Flag so nothing else can window
        """
        pass

    def change_index(self, index):
        """
           Change picture index
        """
        self.index = index
        self.display()

    def change_fullscreen(self, value=True):
        """
           toogle fullscreen
        """
        old = self.fullscreen
        self.fullscreen = value
        self.handle_fullscreen(value, old)

    def change_height(self, value=900):
        """
           change window height
        """
        old = self.height
        self.height = int(value)
        self.handle_height_change(int(value), old)

    def change_width(self, value=1600):
        """
           change window width
        """
        old = self.width
        self.width = int(value)
        self.handle_width_change(int(value), old)

    def stop(self):
        """
            Stop window.
        """
        self._is_windowing = False
        self.handle_stop()

    def close(self):
        self.stop()
        sleep(0.5)
        self.handle_close()

    def shutdown(self):
        """ Perform clean shutdown """
        self.stop()
        self.close()

    def set_window_start_callback(self, callback_func):
        """
            Register callback on window start, should be called as each
            picture in picture list is windowed
        """
        self._window_start_callback = callback_func

    def picture_info(self):
        ret = {}
        ret['artist'] = 'unknown'
        ret['path'] = None
        if len(self.pictures):
            ret['path'] = self.pictures[self.index]
        else:
            ret['path'] = self.default_picture
        ret["is_windowing"] = self._is_windowing
        return ret


