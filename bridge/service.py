"""Bridge state: which modes are on, and the threads that serve them.

The robot's port-81 camera stream serves one client at a time, so the
bridge is that one client (a single FrameGrabber) and everything else --
the browser's video, YOLO detection, the autonomy control loop -- reads
frames from it.

Modes:
- detect: a worker thread runs YOLO on the newest frame whenever it's
  free, so slow inference lowers the box update rate, never the video's.
- auto: autonomy's own control_loop runs in a thread, exactly as
  `python -m autonomy.main` runs it, minus the cv2 window. While it runs it
  does the detection itself, so the detect worker idles.

Safety: turning auto off always stops the robot (and again after the
control thread has finished its tick), and if no UI has polled /status
for heartbeat_timeout_s -- tab closed, laptop asleep -- auto is turned off,
so the robot never drives itself with nobody watching.
"""

import threading
import time

from autonomy import config as autonomy_config
from autonomy.main import _ControlView, _stop_best_effort, control_loop as _control_loop


class LockedDetector:
    """Serializes detect() calls: the model is shared by two threads."""

    def __init__(self, detector):
        self._detector = detector
        self._lock = threading.Lock()

    def detect(self, frame):
        with self._lock:
            return self._detector.detect(frame)


class Bridge:
    def __init__(self, frame_grabber, detector, make_robot_client, *,
                 control_loop=_control_loop, heartbeat_timeout_s=3.0,
                 max_frame_age_s=autonomy_config.MAX_FRAME_AGE_S,
                 clock=time.monotonic, start_threads=True, log=print):
        self.frame_grabber = frame_grabber
        # None when the model failed to load: video and manual driving
        # still work, the modes are refused.
        self._detector = LockedDetector(detector) if detector is not None else None
        self._make_robot_client = make_robot_client
        self._control_loop = control_loop
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._max_frame_age_s = max_frame_age_s
        self._clock = clock
        self._log = log

        self._mode_lock = threading.Lock()  # serializes mode changes
        self._state_lock = threading.Lock()  # guards the fields below
        self._detect = False
        self._detections = []
        self._detect_ms = 0.0
        self._control_thread = None
        self._control_stop = None
        self._view = None
        self._last_heartbeat = clock()

        self._kill_client = make_robot_client()
        self._closed = threading.Event()
        self._threads = []
        if start_threads:
            for target in (self._detect_worker, self._watchdog):
                thread = threading.Thread(target=target, daemon=True)
                thread.start()
                self._threads.append(thread)

    # ---- modes ----

    @property
    def detector_available(self):
        return self._detector is not None

    @property
    def closed(self):
        return self._closed.is_set()

    def auto_running(self):
        thread = self._control_thread
        return thread is not None and thread.is_alive() and not self._control_stop.is_set()

    def set_modes(self, auto=None, detect=None):
        """Change modes; None leaves a mode as it is. Returns status()."""
        with self._mode_lock:
            if not self.detector_available:
                auto = False if auto else auto
                detect = False if detect else detect
            if detect is not None:
                with self._state_lock:
                    self._detect = bool(detect)
                    if not detect:
                        self._detections = []
                self._log(f"bridge: detection {'on' if detect else 'off'}")
            if auto and not self.auto_running():
                self._start_autonomy()
            elif auto is False and self._control_thread is not None:
                self._stop_autonomy()
        return self.status()

    def _start_autonomy(self):
        self._last_heartbeat = self._clock()
        view = _ControlView()
        stop = threading.Event()
        thread = threading.Thread(target=self._run_control, args=(view, stop), daemon=True)
        with self._state_lock:
            self._view = view
            self._control_stop = stop
            self._control_thread = thread
        self._log("bridge: autonomy on")
        thread.start()

    def _run_control(self, view, stop):
        try:
            self._control_loop(self.frame_grabber, self._detector,
                               self._make_robot_client(), view, stop)
        except Exception as exc:
            # control_loop's own finally has already sent /stop.
            self._log(f"bridge: autonomy loop crashed ({exc!r}); autonomy off")
        else:
            if not stop.is_set():
                self._log("bridge: autonomy loop exited; autonomy off")

    def _stop_autonomy(self):
        with self._state_lock:
            thread, stop = self._control_thread, self._control_stop
        stop.set()
        # Stop now rather than after the control thread finishes its tick
        # (up to a pulse plus stop retries)...
        _stop_best_effort(self._kill_client)
        thread.join(timeout=5.0)
        # ...and again, in case that last tick started a move.
        _stop_best_effort(self._kill_client)
        with self._state_lock:
            self._control_thread = None
            self._control_stop = None
            self._view = None
        self._log("bridge: autonomy off, robot stopped")

    def heartbeat(self):
        self._last_heartbeat = self._clock()

    # ---- what to draw / report ----

    def overlay(self):
        """(detections to draw, nav state or None) for the video."""
        with self._state_lock:
            detect = self._detect
            view = self._view
            detections = self._detections
        nav_state = None
        if view is not None and self.auto_running():
            control_detections, nav_state = view.get()
            detections = control_detections
        return (detections if detect else []), nav_state

    def status(self):
        detections, nav_state = self.overlay()
        _, frame, age_s = self.frame_grabber.latest()
        with self._state_lock:
            detect = self._detect
            detect_ms = self._detect_ms
        return {
            "auto": self.auto_running(),
            "detect": detect,
            "detector_available": self.detector_available,
            "nav_state": nav_state.state.name if nav_state is not None else None,
            "detections": [
                {"label": d.label, "confidence": round(d.confidence, 3)} for d in detections
            ],
            "detect_ms": round(detect_ms),
            "stream": {
                "ok": frame is not None and age_s <= self._max_frame_age_s,
                "frame_age_s": None if age_s is None else round(age_s, 2),
            },
        }

    # ---- background threads ----

    def _detect_worker(self):
        done_id = 0
        while not self._closed.is_set():
            with self._state_lock:
                wanted = self._detect
            if not wanted or self.auto_running() or self._detector is None:
                self._closed.wait(0.05)
                continue
            frame_id, frame, age_s = self.frame_grabber.latest()
            if frame is None or frame_id == done_id or age_s > self._max_frame_age_s:
                self._closed.wait(0.01)
                continue
            done_id = frame_id
            started = time.monotonic()
            try:
                detections = self._detector.detect(frame)
            except Exception as exc:
                self._log(f"bridge: detection failed ({exc!r})")
                self._closed.wait(0.5)
                continue
            with self._state_lock:
                if self._detect:
                    self._detections = detections
                    self._detect_ms = (time.monotonic() - started) * 1000

    def _watchdog(self):
        while not self._closed.wait(0.5):
            self.check_heartbeat()

    def check_heartbeat(self):
        if self.auto_running() and self._clock() - self._last_heartbeat > self._heartbeat_timeout_s:
            self._log(f"bridge: no UI for {self._heartbeat_timeout_s:.0f}s, turning autonomy off")
            self.set_modes(auto=False)

    def shutdown(self):
        self.set_modes(auto=False)
        self._closed.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        _stop_best_effort(self._kill_client)
        self.frame_grabber.release()
