from threading import Lock
from time import sleep
from ovos_utils.messagebus import Message, get_mycroft_bus
from ovos_utils.log import LOG
from ovos_utils.configuration import read_mycroft_config


class CommonCanvas:
    def __init__(self, bus=None):
        self.bus = bus or get_mycroft_bus()
        self.config = read_mycroft_config().get("common_windows") or {}
        self.service_lock = Lock()

        self.default = None
        self.services = []
        self.current = None

        raise NotImplementedError
        self.services = load_services(self.config, self.bus)

        # Register end of picture callback
        for s in self.services:
            s.set_window_start_callback(self.window_start)

        # Find default backend
        default_name = self.config.get('default-backend', '')
        LOG.info('Finding default backend...')
        for s in self.services:
            if s.name == default_name:
                self.default = s
                LOG.info('Found ' + self.default.name)
                break
        else:
            self.default = None
            LOG.info('no default found')

        # Setup event handlers
        self.bus.on('ovos.ccanvas.window', self._display)
        self.bus.on('ovos.ccanvas.queue', self._queue)
        self.bus.on('ovos.ccanvas.stop', self._stop)
        self.bus.on('ovos.ccanvas.clear', self._clear)
        self.bus.on('ovos.ccanvas.close', self._close)
        self.bus.on('ovos.ccanvas.reset', self._reset)
        self.bus.on('ovos.ccanvas.next', self._next)
        self.bus.on('ovos.ccanvas.prev', self._prev)
        self.bus.on('ovos.ccanvas.height', self._set_height)
        self.bus.on('ovos.ccanvas.width', self._set_width)
        self.bus.on('ovos.ccanvas.fullscreen', self._set_fullscreen)
        self.bus.on('ovos.ccanvas.picture_info', self._picture_info)
        self.bus.on('ovos.ccanvas.list_backends', self._list_backends)

    def get_prefered(self, utterance=""):
        # Find if the user wants to use a specific backend
        for s in self.services:
            if s.name in utterance:
                prefered_service = s
                LOG.debug(s.name + ' would be prefered')
                break
        else:
            prefered_service = None
        return prefered_service

    def window_start(self, picture):
        """
            Callback method called from the services to indicate start of
            playback of a picture.
        """
        self.bus.emit(Message('ovos.ccanvas.display_picture',
                              data={'picture': picture}))

    def _set_fullscreen(self, message=None):
        value = message.data["value"]
        if self.current:
            self.current.change_fullscreen(value)

    def _set_height(self, message=None):
        value = message.data["value"]
        if self.current:
            self.current.set_height(value)

    def _set_width(self, message=None):
        value = message.data["value"]
        if self.current:
            self.current.set_width(value)

    def _close(self, message=None):
        if self.current:
            self.current.close()

    def _clear(self, message=None):
        if self.current:
            self.current.clear()

    def _reset(self, message=None):
        if self.current:
            self.current.reset()
        else:
            LOG.error("No active window to reset")

    def _next(self, message=None):
        if self.current:
            self.current.next()

    def _prev(self, message=None):
        if self.current:
            self.current.previous()

    def _stop(self, message=None):
        LOG.debug('stopping window services')
        with self.service_lock:
            if self.current:
                name = self.current.name
                if self.current.stop():
                    self.bus.emit(Message("mycroft.stop.handled",
                                          {"by": "window:" + name}))

                self.current = None

    def _queue(self, message):
        if self.current:
            pictures = message.data['pictures']
            self.current.add_pictures(pictures)
        else:
            self._display(message)

    def _display(self, message):
        """
            Handler for ovos.ccanvas.play. Starts window of a
            picturelist. Also  determines if the user requested a special
            service.

            Args:
                message: message bus message, not used but required
        """
        try:
            pictures = message.data['pictures']
            prefered_service = self.get_prefered(message.data.get("utterance", ""))

            if isinstance(pictures[0], str):
                uri_type = pictures[0].split(':')[0]
            else:
                uri_type = pictures[0][0].split(':')[0]

            # check if user requested a particular service
            if prefered_service and uri_type in prefered_service.supported_uris():
                selected_service = prefered_service
            # check if default supports the uri
            elif self.default and uri_type in self.default.supported_uris():
                LOG.debug("Using default backend ({})".format(self.default.name))
                selected_service = self.default
            else:  # Check if any other service can play the media
                LOG.debug("Searching the services")
                for s in self.services:
                    if uri_type in s.supported_uris():
                        LOG.debug("Service {} supports URI {}".format(s, uri_type))
                        selected_service = s
                        break
                else:
                    LOG.info('No service found for uri_type: ' + uri_type)
                    return
            selected_service.clear_pictures()
            selected_service.add_pictures(pictures)
            selected_service.window()
            self.current = selected_service
        except Exception as e:
            LOG.exception(e)

    def _picture_info(self, message):
        """
            Returns picture info on the message bus.

            Args:
                message: message bus message, not used but required
        """
        if self.current:
            picture_info = self.current.picture_info()
        else:
            picture_info = {}
        self.bus.emit(Message('ovos.ccanvas.picture_info_reply',
                              data=picture_info))

    def _list_backends(self, message):
        """ Return a dict of available backends. """
        data = {}
        for s in self.services:
            info = {
                'supported_uris': s.supported_uris(),
                'default': s == self.default
            }
            data[s.name] = info
        self.bus.emit(message.response(data))

    def shutdown(self):
        for s in self.services:
            try:
                LOG.info('shutting down ' + s.name)
                s.shutdown()
            except Exception as e:
                LOG.error('shutdown of ' + s.name + ' failed: ' + repr(e))

        # remove listeners
        self.bus.remove('ovos.ccanvas.window', self._display)
        self.bus.remove('ovos.ccanvas.queue', self._queue)
        self.bus.remove('ovos.ccanvas.stop', self._stop)
        self.bus.remove('ovos.ccanvas.clear', self._clear)
        self.bus.remove('ovos.ccanvas.close', self._close)
        self.bus.remove('ovos.ccanvas.reset', self._reset)
        self.bus.remove('ovos.ccanvas.next', self._next)
        self.bus.remove('ovos.ccanvas.prev', self._prev)
        self.bus.remove('ovos.ccanvas.height', self._set_height)
        self.bus.remove('ovos.ccanvas.width', self._set_width)
        self.bus.remove('ovos.ccanvas.fullscreen', self._set_fullscreen)
        self.bus.remove('ovos.ccanvas.picture_info', self._picture_info)
        self.bus.remove('ovos.ccanvas.list_backends', self._list_backends)


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

    def window(self):
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
        self.window()

    def previous(self):
        """
            Skip to previous pic in playlist.
        """
        self.index -= 1
        if self.index > 0:
            self.index = len(self.pictures)
        self.window()

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
        self.window()

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


