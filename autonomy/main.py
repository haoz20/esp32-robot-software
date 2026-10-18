"""Wires the camera stream, detector, navigator, and robot client together.

Two loops run side by side so the debug window never lags behind the
robot's motion:

- The control loop (a worker thread), each tick: grab a fresh frame,
  detect, ask the navigator for a command, execute it -- a pulse-then-stop,
  or, for continuous search, a spin that keeps running across ticks -- and
  publish what it saw for the display.
- The display loop (the main thread, since cv2 windows must live there on
  macOS) redraws at the stream's frame rate with the control loop's latest
  boxes on top, and polls the kill switch.

Previously the window was drawn once per tick, after the pulse and the
loop-interval sleep, so it showed only 1-2 frames a second.
"""

import os

# opencv-python and torch (via ultralytics) each bundle their own copy of
# libomp.dylib on macOS; loading both aborts the process with "OMP: Error
# #15" unless this is set before either is imported. Letting both
# runtimes actually run threads concurrently -- e.g. cv2's stream-reading
# thread alongside a torch inference call -- can still segfault even with
# the abort suppressed, so also pin both to a single thread each; for one
# frame at a time on a control loop this costs negligible latency and
# avoids the concurrent-thread-pool collision entirely. All of this must
# be set before any lazy cv2/torch import below.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import threading
import time

import requests

from autonomy import config
from autonomy.detector import Detector
from autonomy.navigator import Command, CommandType, NavigatorState, State, step
from autonomy.robot_client import RobotClient
from autonomy.stream import FrameGrabber

_COMMAND_TO_CLIENT_CALL = {
    CommandType.TURN_LEFT: "left",
    CommandType.TURN_RIGHT: "right",
    CommandType.CREEP_FORWARD: "go",
}
_COMMAND_TO_PULSE_S = {
    CommandType.TURN_LEFT: config.TURN_PULSE_S,
    CommandType.TURN_RIGHT: config.TURN_PULSE_S,
    CommandType.CREEP_FORWARD: config.CREEP_PULSE_S,
}
_STOP_RETRY_ATTEMPTS = 3
_STOP_RETRY_DELAY_S = 0.2


def run_tick(nav_state, frame, detector, robot_client, sleep=time.sleep, *,
             continuous_search=False, spin=None):
    """Run one control-loop tick. Returns (command, new_nav_state, detections).

    With continuous_search, `spin` (a _Spin) tracks whether the robot is
    currently spinning: SPIN_RIGHT starts a spin only if one isn't already
    running, and any other command ends it with a /stop first.
    """
    detections = detector.detect(frame)
    if spin is None:
        spin = _Spin()
    command, new_nav_state = step(
        nav_state,
        detections,
        confidence_threshold=config.CONFIDENCE_THRESHOLD,
        deadzone_fraction=config.DEADZONE_FRACTION,
        arrival_height_fraction=config.ARRIVAL_HEIGHT_FRACTION,
        lost_target_ticks=config.LOST_TARGET_TICKS,
        rotation_steps_per_sweep=config.ROTATION_STEPS_PER_SWEEP,
        continuous_search=continuous_search,
        search_confidence_threshold=config.SEARCH_CONFIDENCE_THRESHOLD,
        spin_elapsed_s=spin.elapsed(),
        max_spin_s=config.MAX_SPIN_S,
        max_correction_steps=config.MAX_CORRECTION_STEPS,
    )

    if command.type == CommandType.SPIN_RIGHT:
        if not spin.active:
            try:
                robot_client.right()
            except requests.exceptions.RequestException as exc:
                print(f"autonomy: spin command dropped ({exc}), retrying next tick")
                _stop_with_retries(robot_client, sleep=sleep)
                return Command(CommandType.NONE), nav_state, detections
            spin.start()
        return command, new_nav_state, detections

    if spin.active or command.type == CommandType.STOP:
        # Mark the spin over before stopping: if every stop retry fails,
        # the caller's error path keeps sending /stop, and the next SPIN
        # tick re-sends /right rather than assuming it's still running.
        spin.clear()
        _stop_with_retries(robot_client, sleep=sleep)
        if command.type == CommandType.STOP:
            # Let the robot come to rest so the next frame -- the one
            # CONFIRMING judges -- isn't blurred.
            sleep(config.SPIN_SETTLE_S)
            return command, new_nav_state, detections

    call_name = _COMMAND_TO_CLIENT_CALL.get(command.type)
    if call_name is not None:
        try:
            getattr(robot_client, call_name)()
            sleep(_COMMAND_TO_PULSE_S[command.type])
        except requests.exceptions.RequestException as exc:
            # A single dropped request on the robot's busy WiFi link is
            # routine -- the robot's own control page (index_handler in
            # app_httpd.cpp) fires commands and silently ignores failures.
            # Treat it as "nothing happened this tick": stop, and keep the
            # old nav state so the same step is retried next tick.
            print(f"autonomy: {call_name} command dropped ({exc}), retrying next tick")
            _stop_with_retries(robot_client, sleep=sleep)
            return Command(CommandType.NONE), nav_state, detections
        _stop_with_retries(robot_client, sleep=sleep)
    return command, new_nav_state, detections


class _Spin:
    """Whether a continuous spin is running on the robot, and for how long."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._started_at = None

    @property
    def active(self):
        return self._started_at is not None

    def start(self):
        self._started_at = self._clock()

    def clear(self):
        self._started_at = None

    def elapsed(self):
        return 0.0 if self._started_at is None else self._clock() - self._started_at


def _stop_with_retries(robot_client, sleep=time.sleep):
    """Send /stop, retrying a few times before giving up.

    A movement pulse's paired stop is the single highest-risk failure in
    this system: the robot has no obstacle sensor, so a stop that never
    arrives leaves it driving indefinitely (the firmware's drive endpoints
    run until told to stop). Retry before letting the failure propagate.
    """
    last_error = None
    for attempt in range(_STOP_RETRY_ATTEMPTS):
        try:
            robot_client.stop()
            return
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt < _STOP_RETRY_ATTEMPTS - 1:
                sleep(_STOP_RETRY_DELAY_S)
    raise last_error


def draw_debug_frame(frame, detections, nav_state, stream_ok=True):
    import cv2

    annotated = frame.copy()
    height, width = annotated.shape[0], annotated.shape[1]
    for detection in detections:
        x1 = int((detection.x_center - detection.width / 2) * width)
        y1 = int((detection.y_center - detection.height / 2) * height)
        x2 = int((detection.x_center + detection.width / 2) * width)
        y2 = int((detection.y_center + detection.height / 2) * height)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            annotated, f"{detection.label} {detection.confidence:.2f}",
            (x1, max(y1 - 5, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
        )
    cv2.putText(
        annotated, nav_state.state.name, (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
    )
    if not stream_ok:
        cv2.putText(
            annotated, "STREAM STALLED - robot held", (10, height - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1,
        )
    return annotated


class _ControlView:
    """What the control loop last saw, for the display loop to draw."""

    def __init__(self):
        self._lock = threading.Lock()
        self._detections = []
        self._nav_state = NavigatorState()

    def publish(self, detections, nav_state):
        with self._lock:
            self._detections = detections
            self._nav_state = nav_state

    def get(self):
        with self._lock:
            return self._detections, self._nav_state


def control_loop(frame_grabber, detector, robot_client, view, stop_event):
    """Drive the robot until stop_event is set. Always leaves it stopped."""
    nav_state = NavigatorState()
    spin = _Spin()
    stream_stalled = False
    last_report = None
    try:
        while not stop_event.is_set():
            try:
                frame = frame_grabber.read()
            except RuntimeError as exc:
                # Watchdog: never act -- or keep spinning -- on a frame we
                # can't trust. The grabber keeps the connection open and
                # frames normally resume within a second or two.
                spin.clear()
                _stop_best_effort(robot_client)
                if not stream_stalled:
                    print(f"autonomy: {exc}; holding the robot stopped")
                    stream_stalled = True
                stop_event.wait(config.STALE_FRAME_WAIT_S)
                continue
            if stream_stalled:
                print("autonomy: fresh frames again, resuming")
                stream_stalled = False

            try:
                command, nav_state, detections = run_tick(
                    nav_state, frame, detector, robot_client,
                    continuous_search=config.CONTINUOUS_SEARCH, spin=spin,
                )
            except requests.exceptions.RequestException as exc:
                # Even /stop's retries failed. Exiting wouldn't stop the
                # robot either -- it would just stop trying. Keep looping:
                # the next tick sends /stop again, and if the robot is truly
                # gone the stream goes stale and the watchdog above holds
                # it. Falls through so the kill switch still gets checked.
                print(f"autonomy: can't reach the robot ({exc}), retrying")
                spin.clear()
                _stop_best_effort(robot_client)
                command, detections = Command(CommandType.NONE), []

            view.publish(detections, nav_state)

            # While spinning, a tick runs every frame; only log changes.
            seen = ", ".join(f"{d.label} {d.confidence:.2f}" for d in detections) or "nothing"
            report = (nav_state.state, command.type, seen)
            if report != last_report:
                print(f"[{nav_state.state.name}] sees: {seen} -> {command.type.name}")
                last_report = report

            # A spin has to be watched every frame; stepped moves get the
            # usual pause between ticks.
            if not spin.active:
                stop_event.wait(config.LOOP_INTERVAL_S)
    finally:
        _stop_best_effort(robot_client)


def main():
    import cv2
    import numpy as np

    cv2.namedWindow(config.DEBUG_WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(config.DEBUG_WINDOW_NAME, config.DEBUG_WINDOW_WIDTH, config.DEBUG_WINDOW_HEIGHT)

    robot_client = RobotClient(
        config.ROBOT_IP, port=config.ROBOT_HTTP_PORT, timeout_s=config.ROBOT_HTTP_TIMEOUT_S
    )
    # The kill switch's immediate stop gets its own client: RobotClient's
    # requests.Session isn't safe to share with the control thread.
    kill_client = RobotClient(
        config.ROBOT_IP, port=config.ROBOT_HTTP_PORT, timeout_s=config.ROBOT_HTTP_TIMEOUT_S
    )
    frame_grabber = FrameGrabber(
        config.ROBOT_IP, port=config.ROBOT_STREAM_PORT,
        max_frame_age_s=config.MAX_FRAME_AGE_S,
        connect_timeout_s=config.STREAM_CONNECT_TIMEOUT_S,
        header_timeout_s=config.STREAM_HEADER_TIMEOUT_S,
        stall_timeout_s=config.STREAM_STALL_TIMEOUT_S,
    )
    # Built on the main thread, before the control thread exists.
    detector = Detector(config.MODEL_PATH, config.CONFIDENCE_THRESHOLD)

    view = _ControlView()
    stop_event = threading.Event()
    control = threading.Thread(
        target=control_loop,
        args=(frame_grabber, detector, robot_client, view, stop_event),
        daemon=True,
    )
    control.start()

    placeholder = np.zeros((config.DEBUG_WINDOW_HEIGHT, config.DEBUG_WINDOW_WIDTH, 3), np.uint8)
    try:
        while control.is_alive():
            _, frame, age_s = frame_grabber.latest()
            if frame is None:
                image = placeholder
            else:
                detections, nav_state = view.get()
                image = draw_debug_frame(frame, detections, nav_state,
                                         stream_ok=age_s <= config.MAX_FRAME_AGE_S)
            # Redraw every pass, even with no new frame: on at least one
            # Windows setup, cv2.waitKey() with nothing new shown hung
            # instead of returning, freezing the kill switch.
            cv2.imshow(config.DEBUG_WINDOW_NAME, image)
            key = cv2.waitKey(config.DISPLAY_INTERVAL_MS) & 0xFF
            if key == config.KILL_SWITCH_KEY:
                break
        else:
            print("autonomy: control loop exited unexpectedly")
    finally:
        stop_event.set()
        # Stop now rather than waiting for the control thread to finish its
        # current tick (up to a pulse plus stop retries).
        _stop_best_effort(kill_client)
        control.join(timeout=5.0)
        # And again after it has finished, in case its last tick started a
        # move after the stop above.
        _stop_best_effort(kill_client)
        frame_grabber.release()
        cv2.destroyAllWindows()


def _stop_best_effort(robot_client):
    """Attempt /stop with retries; never raises, so cleanup/exit can't be skipped."""
    try:
        _stop_with_retries(robot_client)
    except requests.exceptions.RequestException:
        pass


if __name__ == "__main__":
    main()
