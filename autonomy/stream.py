"""MJPEG frame grabber for the ESP32 camera stream.

Wraps cv2.VideoCapture, which can open the ESP32's MJPEG HTTP stream
directly. capture_factory is injectable so tests don't need a real camera
or cv2 installed.

The ESP32 pushes frames faster than one control-loop tick can consume
(a tick includes inference plus a motor pulse), so naive reads fall behind
and return frames that are stale by the time the navigator acts on them.
A background thread continuously drains the stream and keeps only the
newest frame; read() hands that back, raising if it's gone stale (the
stream stalled, or no frame has arrived yet) rather than silently acting
on an old one.
"""

import threading
import time


class FrameGrabber:
    def __init__(self, ip, port=81, capture_factory=None, max_frame_age_s=1.0,
                 clock=time.monotonic, start_thread=True):
        if capture_factory is None:
            import cv2
            capture_factory = cv2.VideoCapture
        self._url = f"http://{ip}:{port}/stream"
        self._capture = capture_factory(self._url)
        self._max_frame_age_s = max_frame_age_s
        self._clock = clock
        self._lock = threading.Lock()
        self._latest_frame = None
        self._latest_frame_time = None
        self._stop_event = threading.Event()
        self._thread = None
        if start_thread:
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()

    def _read_loop(self):
        while not self._stop_event.is_set():
            ok, frame = self._capture.read()
            if ok:
                self._store_frame(frame)
            else:
                time.sleep(0.01)

    def _store_frame(self, frame):
        with self._lock:
            self._latest_frame = frame
            self._latest_frame_time = self._clock()

    def read(self):
        with self._lock:
            frame = self._latest_frame
            frame_time = self._latest_frame_time
        if frame is None:
            raise RuntimeError(f"no frame received yet from {self._url}")
        age = self._clock() - frame_time
        if age > self._max_frame_age_s:
            raise RuntimeError(
                f"frame from {self._url} is {age:.1f}s old (max {self._max_frame_age_s}s) "
                "-- stream may have stalled"
            )
        return frame

    def release(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._capture.release()
