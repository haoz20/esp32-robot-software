"""MJPEG frame grabber for the ESP32 camera stream.

The ESP32 serves its camera as a multipart/x-mixed-replace MJPEG-over-HTTP
push stream -- not a standard video container. cv2.VideoCapture delegates
to FFmpeg's generic demuxer, which is unreliable against this exact stream
type (a common, well-documented issue with ESP32-CAM-style streams
specifically). _MjpegHttpCapture instead reads the raw HTTP response and
parses out each JPEG frame directly, which is the reliable approach for
this stream type. capture_factory is injectable so tests don't need a
real camera, cv2, or requests installed.

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


class _MjpegHttpCapture:
    """Reads a multipart/x-mixed-replace MJPEG-over-HTTP stream directly.

    Mimics the small slice of cv2.VideoCapture's interface FrameGrabber
    needs (read() -> (ok, frame), release()) so it's a drop-in default
    capture_factory.
    """

    def __init__(self, url, timeout_s=5.0):
        import requests

        self._url = url
        self._response = requests.get(url, stream=True, timeout=timeout_s)
        self._response.raise_for_status()
        self._chunks = self._response.iter_content(chunk_size=1024)
        self._buffer = b""

    def read(self):
        import cv2
        import numpy as np

        try:
            for chunk in self._chunks:
                self._buffer += chunk
                start = self._buffer.find(b"\xff\xd8")  # JPEG SOI marker
                end = self._buffer.find(b"\xff\xd9")  # JPEG EOI marker
                if start != -1 and end != -1 and end > start:
                    jpg = self._buffer[start:end + 2]
                    self._buffer = self._buffer[end + 2:]
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        return True, frame
        except Exception:
            return False, None
        return False, None

    def release(self):
        self._response.close()


class FrameGrabber:
    def __init__(self, ip, port=81, capture_factory=None, max_frame_age_s=1.0,
                 clock=time.monotonic, start_thread=True):
        if capture_factory is None:
            capture_factory = _MjpegHttpCapture
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
