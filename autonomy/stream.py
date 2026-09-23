"""MJPEG frame grabber for the ESP32 camera stream.

Wraps cv2.VideoCapture, which can open the ESP32's MJPEG HTTP stream
directly. capture_factory is injectable so tests don't need a real camera
or cv2 installed.
"""


class FrameGrabber:
    def __init__(self, ip, port=81, capture_factory=None):
        if capture_factory is None:
            import cv2
            capture_factory = cv2.VideoCapture
        self._url = f"http://{ip}:{port}/stream"
        self._capture = capture_factory(self._url)

    def read(self):
        ok, frame = self._capture.read()
        if not ok:
            raise RuntimeError(f"failed to read frame from {self._url}")
        return frame

    def release(self):
        self._capture.release()
