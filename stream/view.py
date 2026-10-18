"""Standalone MJPEG stream viewer for testing the robot's camera.

Connects to the firmware's port-81 /stream endpoint, shows the video in an
OpenCV window, and logs every connection event (connect, HTTP response,
first frame, throughput, stalls, disconnects, reconnects) to the console
and to stream/logs/stream-<timestamp>.log.

Smoothness comes from splitting the work: a background thread reads and
decodes the stream as fast as the robot pushes it and keeps only the
newest frame, so the display loop never waits on the network and never
falls behind showing stale frames.

YOLO detection (autonomy's model) runs in a third thread on whatever frame
is newest when it's free, and the display draws its latest boxes onto every
frame -- so slow inference lowers the detection rate, not the video rate.

    python -m stream.view                    # default robot IP, detection on
    python -m stream.view --ip 192.168.4.1 --port 81
    python -m stream.view --no-detect        # plain stream, no model
    python -m stream.view --model path/to/best.pt --conf 0.4

Press q or ESC in the window to quit.
"""

import os

# Same macOS OpenMP workaround as autonomy/main.py: opencv-python and torch
# each bundle libomp.dylib, and must be pinned to one thread each before
# either is imported or the process aborts/segfaults.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import argparse
import logging
import threading
import time
from datetime import datetime

import cv2
import numpy as np
import requests

from autonomy import config

DEFAULT_IP = "192.168.4.1"
DEFAULT_PORT = 81
CONNECT_TIMEOUT_S = 5.0
# Read timeout doubles as stall detection: no bytes for this long means the
# stream is dead, so drop the connection and reconnect.
READ_TIMEOUT_S = 3.0
# The firmware's port-81 server streams to one client at a time (its
# stream_handler loops until a send fails), so a new connection is accepted
# but gets no response while another client holds the stream -- or while
# the robot hasn't yet noticed a previous viewer is gone. Wait longer for
# that first response: every attempt abandoned early leaves one more dead
# connection queued on the robot, which it then has to work through.
HEADER_TIMEOUT_S = 10.0
CHUNK_SIZE = 16 * 1024
STATS_INTERVAL_S = 5.0
MAX_BACKOFF_S = 10.0
WINDOW_NAME = "robot stream"
WINDOW_WIDTH = 960
WINDOW_HEIGHT = 720

log = logging.getLogger("stream")


def setup_logging():
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"stream-{datetime.now():%Y%m%d-%H%M%S}.log")
    fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-5s %(message)s", "%H:%M:%S")
    for handler in (logging.StreamHandler(), logging.FileHandler(path)):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    return path


class StreamReader:
    """Background reader: keeps the newest decoded frame, reconnects forever."""

    def __init__(self, url):
        self.url = url
        self._lock = threading.Lock()
        self._frame = None
        self._frame_id = 0
        self._stop = threading.Event()
        self._response = None
        self.connected = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def latest(self):
        with self._lock:
            return self._frame_id, self._frame

    def stop(self):
        self._stop.set()
        # Closing the response unblocks a read stuck inside the socket.
        if self._response is not None:
            self._response.close()
        self._thread.join(timeout=2.0)

    def _run(self):
        attempt = 0
        busy_streak = 0
        while not self._stop.is_set():
            attempt += 1
            started = time.monotonic()
            try:
                self._session(attempt)
            except requests.exceptions.ConnectTimeout:
                log.warning("connect timed out after %.1fs (is the laptop on the robot's WiFi?)",
                            CONNECT_TIMEOUT_S)
            except requests.exceptions.ReadTimeout:
                busy_streak += 1
                log.warning("robot accepted the connection but sent nothing for %.1fs",
                            HEADER_TIMEOUT_S)
                if busy_streak == 2:
                    log.warning("the robot streams to one client at a time: close any other "
                                "viewer (webapp, browser tab on :81, autonomy). If none is "
                                "open, the robot may still be holding a dead connection -- "
                                "power-cycle it if this keeps up")
            except requests.exceptions.ConnectionError as e:
                if self._stop.is_set():
                    break
                log.warning("connection error: %s", _short(e))
            except requests.exceptions.HTTPError as e:
                log.warning("HTTP error: %s", e)
            except Exception as e:  # keep the viewer alive whatever happens
                if self._stop.is_set():
                    break
                log.exception("unexpected error: %s", e)
            finally:
                if self.connected:
                    busy_streak = 0
                    log.warning("disconnected after %.1fs", time.monotonic() - started)
                self.connected = False
                if self._response is not None:
                    self._response.close()
                    self._response = None

            if self._stop.is_set():
                break
            # A session that streamed for a while resets the backoff.
            if time.monotonic() - started > 10.0:
                attempt = 1
            backoff = min(MAX_BACKOFF_S, 0.5 * 2 ** (attempt - 1))
            log.info("reconnecting in %.1fs", backoff)
            self._stop.wait(backoff)

    def _session(self, attempt):
        log.info("connecting to %s (attempt %d)", self.url, attempt)
        t0 = time.monotonic()
        self._response = requests.get(self.url, stream=True,
                                      timeout=(CONNECT_TIMEOUT_S, HEADER_TIMEOUT_S))
        self._response.raise_for_status()
        # Headers arrived; tighten the socket timeout so a stalled stream is
        # noticed quickly.
        try:
            self._response.raw.connection.sock.settimeout(READ_TIMEOUT_S)
        except AttributeError:
            pass
        self.connected = True
        log.info("connected: HTTP %d in %.0fms, content-type=%s",
                 self._response.status_code, (time.monotonic() - t0) * 1000,
                 self._response.headers.get("Content-Type", "?"))

        buf = bytearray()
        frames = bytes_in = decode_fail = 0
        first_frame = True
        window_start = time.monotonic()
        last_frame_at = time.monotonic()
        max_gap = 0.0

        # read1() returns whatever bytes have arrived (up to CHUNK_SIZE)
        # instead of blocking until a full chunk fills, as iter_content
        # does -- that blocking is what makes frames arrive in clumps.
        raw = self._response.raw
        while not self._stop.is_set():
            try:
                chunk = raw.read1(CHUNK_SIZE)
            except Exception as e:
                if "timed out" in str(e).lower():
                    log.warning("stream stalled: no data for %.1fs", READ_TIMEOUT_S)
                    return
                raise
            if not chunk:
                break
            buf += chunk
            bytes_in += len(chunk)

            # Pull every complete JPEG out of the buffer; only the last one
            # matters for display but the count feeds the fps stat.
            jpg = None
            while True:
                start = buf.find(b"\xff\xd8")
                if start == -1:
                    buf.clear()
                    break
                end = buf.find(b"\xff\xd9", start + 2)
                if end == -1:
                    if start:
                        del buf[:start]
                    break
                jpg = bytes(buf[start:end + 2])
                del buf[:end + 2]
                frames += 1
                now = time.monotonic()
                max_gap = max(max_gap, now - last_frame_at)
                last_frame_at = now

            if jpg is not None:
                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    decode_fail += 1
                else:
                    if first_frame:
                        h, w = frame.shape[:2]
                        log.info("first frame after %.0fms: %dx%d, %d bytes",
                                 (time.monotonic() - t0) * 1000, w, h, len(jpg))
                        first_frame = False
                    with self._lock:
                        self._frame = frame
                        self._frame_id += 1

            elapsed = time.monotonic() - window_start
            if elapsed >= STATS_INTERVAL_S:
                log.info("stats: %.1f fps, %.0f KB/s, max frame gap %.0fms, decode failures %d",
                         frames / elapsed, bytes_in / elapsed / 1024, max_gap * 1000, decode_fail)
                frames = bytes_in = decode_fail = 0
                max_gap = 0.0
                window_start = time.monotonic()

        if not self._stop.is_set():
            log.warning("server closed the stream")


class DetectionWorker:
    """Background detector: runs the model on the newest frame, keeps the result."""

    def __init__(self, reader, detector):
        self._reader = reader
        self._detector = detector
        self._lock = threading.Lock()
        self._detections = []
        self._infer_ms = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def latest(self):
        with self._lock:
            return self._detections, self._infer_ms

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5.0)

    def _run(self):
        detector = self._detector
        done_id = 0
        runs = 0
        total_ms = 0.0
        last_seen = None
        window_start = time.monotonic()
        while not self._stop.is_set():
            frame_id, frame = self._reader.latest()
            if frame is None or frame_id == done_id:
                self._stop.wait(0.005)
                continue
            done_id = frame_id
            t = time.monotonic()
            try:
                detections = detector.detect(frame)
            except Exception as e:
                log.warning("detection failed: %s", _short(e))
                continue
            ms = (time.monotonic() - t) * 1000
            with self._lock:
                self._detections = detections
                self._infer_ms = ms
            runs += 1
            total_ms += ms

            # Log only when what's in view changes, not every frame.
            seen = sorted(d.label for d in detections)
            if seen != last_seen:
                desc = ", ".join(f"{d.label} {d.confidence:.2f}" for d in detections)
                log.info("detections: %s", desc or "nothing")
                last_seen = seen

            elapsed = time.monotonic() - window_start
            if elapsed >= STATS_INTERVAL_S:
                log.info("detect stats: %.1f inferences/s, avg %.0fms",
                         runs / elapsed, total_ms / runs)
                runs = 0
                total_ms = 0.0
                window_start = time.monotonic()


def load_detector(model_path, confidence):
    """Load the model and run one warm-up inference, or return None on failure.

    Runs on the main thread before the stream reader starts, the same way
    autonomy/main.py builds its Detector, so a model problem shows up
    before any streaming begins.
    """
    from autonomy.detector import Detector

    log.info("loading model %s (conf >= %.2f)", model_path, confidence)
    t0 = time.monotonic()
    try:
        detector = Detector(model_path, confidence)
        detector.detect(np.zeros((240, 320, 3), dtype=np.uint8))
    except Exception as e:
        log.error("model failed to load, detection disabled: %s", _short(e))
        return None
    log.info("model loaded and warmed up in %.1fs", time.monotonic() - t0)
    return detector


def draw_detections(frame, detections, infer_ms):
    annotated = frame.copy()
    h, w = annotated.shape[:2]
    for d in detections:
        x1 = int((d.x_center - d.width / 2) * w)
        y1 = int((d.y_center - d.height / 2) * h)
        x2 = int((d.x_center + d.width / 2) * w)
        y2 = int((d.y_center + d.height / 2) * h)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(annotated, f"{d.label} {d.confidence:.2f}", (x1, max(y1 - 5, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(annotated, f"{infer_ms:.0f}ms", (5, h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return annotated


def _short(exc):
    text = str(exc)
    return text if len(text) < 160 else text[:157] + "..."


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ip", default=DEFAULT_IP)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-detect", action="store_true", help="show the plain stream")
    parser.add_argument("--model", default=config.MODEL_PATH)
    parser.add_argument("--conf", type=float, default=config.CONFIDENCE_THRESHOLD)
    args = parser.parse_args()

    log_path = setup_logging()
    log.info("logging to %s", log_path)

    reader = StreamReader(f"http://{args.ip}:{args.port}/stream")
    model = None if args.no_detect else load_detector(args.model, args.conf)
    reader.start()
    detector = None
    if model is not None:
        detector = DetectionWorker(reader, model)
        detector.start()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, WINDOW_WIDTH, WINDOW_HEIGHT)
    placeholder = np.zeros((WINDOW_HEIGHT, WINDOW_WIDTH, 3), dtype=np.uint8)
    shown_id = 0
    try:
        while True:
            frame_id, frame = reader.latest()
            if frame_id != shown_id:
                if detector is not None:
                    frame = draw_detections(frame, *detector.latest())
                cv2.imshow(WINDOW_NAME, frame)
                shown_id = frame_id
            elif frame is None or not reader.connected:
                img = placeholder.copy() if frame is None else frame.copy()
                cv2.putText(img, "connecting..." if frame is None else "reconnecting...",
                            (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 255), 2)
                cv2.imshow(WINDOW_NAME, img)
            key = cv2.waitKey(10) & 0xFF
            if key in (ord("q"), 27):
                break
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        log.info("shutting down")
        if detector is not None:
            detector.stop()
        reader.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
