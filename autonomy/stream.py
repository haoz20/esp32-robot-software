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

"Frame too old to act on" and "connection dead" are deliberately separate.
The robot's WiFi routinely pauses for 1-2s (worse under motor current
draw); read() raising on a stale frame only tells the caller to hold the
robot still, while the connection is kept open and frames resume on their
own. The background thread reconnects only when the connection is really
gone -- no bytes for stall_timeout_s, or the server closed it. Tearing the
connection down on every short gap made things much worse: the firmware's
port-81 server streams to one client at a time, so a new connection gets
no response until the robot notices the old one is dead, and every attempt
abandoned early leaves another dead connection queued on the robot.
"""

import threading
import time


class _MjpegHttpCapture:
    """Reads a multipart/x-mixed-replace MJPEG-over-HTTP stream directly.

    Mimics the small slice of cv2.VideoCapture's interface FrameGrabber
    needs (read() -> (ok, frame), release()) so it's a drop-in default
    capture_factory. read() returning (False, None) means the connection is
    dead and the capture should be replaced.
    """

    _CHUNK_SIZE = 16 * 1024

    def __init__(self, url, connect_timeout_s=5.0, header_timeout_s=10.0, stall_timeout_s=3.0):
        import requests

        self._url = url
        # header_timeout_s is generous on purpose: while another client (or
        # a dead connection the robot hasn't noticed yet) holds the stream,
        # the robot accepts the connection but sends nothing.
        self._response = requests.get(url, stream=True,
                                      timeout=(connect_timeout_s, header_timeout_s))
        self._response.raise_for_status()
        # Headers arrived; tighten the socket timeout so a stalled stream is
        # noticed quickly.
        try:
            self._response.raw.connection.sock.settimeout(stall_timeout_s)
        except AttributeError:
            pass
        self._raw = self._response.raw
        self._buffer = bytearray()

    def read(self):
        import cv2
        import numpy as np

        try:
            while True:
                # read1() returns whatever bytes have arrived instead of
                # blocking until a full chunk fills; waiting for full chunks
                # makes frames arrive in clumps.
                chunk = self._raw.read1(self._CHUNK_SIZE)
                if not chunk:
                    return False, None
                self._buffer += chunk
                jpg = self._take_newest_jpeg()
                if jpg is None:
                    continue
                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    return True, frame
        except Exception:
            return False, None

    def _take_newest_jpeg(self):
        """Remove every complete JPEG from the buffer and return the last one."""
        buf = self._buffer
        newest = None
        while True:
            start = buf.find(b"\xff\xd8")  # JPEG SOI marker
            if start == -1:
                buf.clear()
                return newest
            end = buf.find(b"\xff\xd9", start + 2)  # JPEG EOI marker
            if end == -1:
                if start:
                    del buf[:start]
                return newest
            newest = bytes(buf[start:end + 2])
            del buf[:end + 2]

    def release(self):
        self._response.close()


class FrameGrabber:
    def __init__(self, ip, port=81, capture_factory=None, max_frame_age_s=1.0,
                 clock=time.monotonic, start_thread=True, connect_timeout_s=5.0,
                 header_timeout_s=10.0, stall_timeout_s=3.0, reconnect_backoff_s=0.5,
                 max_reconnect_backoff_s=10.0, log=print):
        if capture_factory is None:
            def capture_factory(url):
                return _MjpegHttpCapture(url, connect_timeout_s=connect_timeout_s,
                                         header_timeout_s=header_timeout_s,
                                         stall_timeout_s=stall_timeout_s)
        self._capture_factory = capture_factory
        self._url = f"http://{ip}:{port}/stream"
        self._max_frame_age_s = max_frame_age_s
        self._clock = clock
        self._reconnect_backoff_s = reconnect_backoff_s
        self._max_reconnect_backoff_s = max_reconnect_backoff_s
        self._log = log
        self._lock = threading.Lock()
        self._latest_frame = None
        self._latest_frame_time = None
        self._frame_id = 0
        self._stop_event = threading.Event()
        self._capture_lock = threading.Lock()
        self._capture = self._open()
        self._thread = None
        if start_thread:
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()

    def _open(self):
        """Connect once. Returns the capture, or None if the robot isn't reachable."""
        try:
            capture = self._capture_factory(self._url)
        except Exception as exc:
            self._log(f"autonomy: stream connect to {self._url} failed ({exc})")
            return None
        self._log(f"autonomy: stream connected to {self._url}")
        return capture

    def _read_loop(self):
        backoff_s = self._reconnect_backoff_s
        while not self._stop_event.is_set():
            capture = self._capture
            if capture is None:
                self._log(f"autonomy: stream reconnecting in {backoff_s:.1f}s")
                if self._stop_event.wait(backoff_s):
                    break
                backoff_s = min(backoff_s * 2, self._max_reconnect_backoff_s)
                capture = self._open()
                with self._capture_lock:
                    if self._stop_event.is_set():
                        # release() ran while we were connecting.
                        if capture is not None:
                            capture.release()
                        break
                    self._capture = capture
                continue

            ok, frame = capture.read()
            if ok:
                self._store_frame(frame)
                backoff_s = self._reconnect_backoff_s
                continue
            if self._stop_event.is_set():
                break
            self._log("autonomy: stream connection lost")
            with self._capture_lock:
                capture.release()
                self._capture = None

    def _store_frame(self, frame):
        with self._lock:
            self._latest_frame = frame
            self._latest_frame_time = self._clock()
            self._frame_id += 1

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

    def latest(self):
        """Newest frame for display, never raising: (frame_id, frame, age_s).

        frame is None (and age_s is None) until the first frame arrives.
        frame_id increases with every new frame, so a caller can tell
        whether anything changed since it last looked.
        """
        with self._lock:
            frame_id = self._frame_id
            frame = self._latest_frame
            frame_time = self._latest_frame_time
        if frame is None:
            return frame_id, None, None
        return frame_id, frame, self._clock() - frame_time

    def release(self):
        self._stop_event.set()
        # Close the underlying connection BEFORE joining the thread: if the
        # background thread is blocked inside a socket read when release()
        # is called, closing the connection first is what actually unblocks
        # it (some platforms, notably Windows, can otherwise leave a read
        # blocked indefinitely on a socket that's still technically open,
        # even after the peer stops responding -- silently hanging the
        # whole process rather than raising).
        with self._capture_lock:
            if self._capture is not None:
                self._capture.release()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
