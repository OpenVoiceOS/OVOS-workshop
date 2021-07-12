from ovos_utils.messagebus import Message
from ovos_workshop.frameworks.canvas.base import AbstractCanvas
import imutils
import cv2
import numpy as np


# TODO move to opm
class OpenCVService(AbstractCanvas):
    """
        Display backend for opencv package.
    """
    def __init__(self, bus, config, name="opencv"):
        super().__init__(bus, config, name)
        self.bus.on("ovos.ccanvas.opencv.display", self._display)
        self.current_image = None

    @staticmethod
    def supported_uris():
        """
            Returns: list of supported uri types.
        """
        return ['file', 'http', 'https', "numpy"]

    def _display(self, message=None):
        self._prepare_window()
        self._is_displaying = True
        cv2.imshow("OpenCV Display", self.current_image)
        cv2.waitKey(0)

    def _prepare_window(self):
        if self._is_displaying:
            cv2.destroyWindow("OpenCV Display")

        cv2.namedWindow("OpenCV Display", cv2.WND_PROP_FULLSCREEN)
        if self.fullscreen:
            cv2.setWindowProperty("OpenCV Display", cv2.WND_PROP_FULLSCREEN,
                                  cv2.WINDOW_FULLSCREEN)
        else:
            cv2.setWindowProperty("OpenCV Display", cv2.WND_PROP_FULLSCREEN,
                                  not cv2.WINDOW_FULLSCREEN)
            cv2.resizeWindow("OpenCV Display", self.width, self.height)

    def handle_display(self, picture):
        path = picture.replace("file://", "")
        image = cv2.imread(path)
        image = imutils.resize(image, self.width, self.height)
        self.current_image = image
        self.bus.emit(Message("ovos.ccanvas.opencv.display"))

    def handle_fullscreen(self, new_value, old_value):
        # re-render
        self._display()

    def handle_height_change(self, new_value, old_value):
        # re-render
        self._display()

    def handle_width_change(self, new_value, old_value):
        # re-render
        self._display()

    def handle_clear(self):
        """
            Clear Display.
        """
        # Create a black image
        image = np.zeros((512, 512, 3), np.uint8)
        if not self.fullscreen:
            image = imutils.resize(image, self.width, self.height)
        self.current_image = image
        self._display()

    def handle_close(self):
        cv2.destroyAllWindows()
        self._is_displaying = False
