"""Wires the camera stream, detector, navigator, and robot client together.

The control loop, in order, each tick: grab a frame, detect, ask the
navigator for a command, execute it as a pulse-then-stop, draw the debug
overlay, and check the kill switch.
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

import time

import requests

from autonomy import config
from autonomy.detector import Detector
from autonomy.navigator import CommandType, NavigatorState, State, step
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


def run_tick(nav_state, frame, detector, robot_client, sleep=time.sleep):
    """Run one control-loop tick. Returns (command, new_nav_state, detections)."""
    detections = detector.detect(frame)
    command, new_nav_state = step(
        nav_state,
        detections,
        confidence_threshold=config.CONFIDENCE_THRESHOLD,
        deadzone_fraction=config.DEADZONE_FRACTION,
        arrival_height_fraction=config.ARRIVAL_HEIGHT_FRACTION,
        lost_target_ticks=config.LOST_TARGET_TICKS,
        rotation_steps_per_sweep=config.ROTATION_STEPS_PER_SWEEP,
    )
    call_name = _COMMAND_TO_CLIENT_CALL.get(command.type)
    if call_name is not None:
        try:
            getattr(robot_client, call_name)()
            sleep(_COMMAND_TO_PULSE_S[command.type])
        finally:
            _stop_with_retries(robot_client, sleep=sleep)
    return command, new_nav_state, detections


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


def draw_debug_frame(frame, detections, nav_state):
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
    return annotated


def main():
    import cv2

    cv2.namedWindow(config.DEBUG_WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(config.DEBUG_WINDOW_NAME, config.DEBUG_WINDOW_WIDTH, config.DEBUG_WINDOW_HEIGHT)

    robot_client = RobotClient(
        config.ROBOT_IP, port=config.ROBOT_HTTP_PORT, timeout_s=config.ROBOT_HTTP_TIMEOUT_S
    )
    frame_grabber = FrameGrabber(config.ROBOT_IP, port=config.ROBOT_STREAM_PORT)
    detector = Detector(config.MODEL_PATH, config.CONFIDENCE_THRESHOLD)
    nav_state = NavigatorState()
    stream_backoff_s = 1.0

    try:
        while True:
            try:
                frame = frame_grabber.read()
            except RuntimeError:
                _stop_best_effort(robot_client)
                _wait_up_to(stream_backoff_s)
                frame_grabber.release()
                try:
                    frame_grabber = FrameGrabber(config.ROBOT_IP, port=config.ROBOT_STREAM_PORT)
                except Exception as exc:
                    # Reconnect failed -- likely the robot hasn't finished
                    # recovering yet (e.g. a brief brownout/WiFi drop from
                    # motor current draw). frame_grabber still points at the
                    # old, already-released grabber; its next .read() call
                    # raises RuntimeError immediately (stale/no frame),
                    # routing back through this same branch to retry with a
                    # longer backoff, instead of crashing the process.
                    print(f"autonomy: stream reconnect failed ({exc}), retrying in up to {stream_backoff_s:.0f}s")
                stream_backoff_s = min(stream_backoff_s * 2, 10.0)
                continue

            stream_backoff_s = 1.0

            try:
                command, nav_state, detections = run_tick(nav_state, frame, detector, robot_client)
            except requests.exceptions.RequestException as exc:
                print(f"autonomy: lost contact with the robot, stopping: {exc}")
                break

            seen = ", ".join(f"{d.label} {d.confidence:.2f}" for d in detections) or "nothing"
            print(f"[{nav_state.state.name}] sees: {seen} -> {command.type.name}")

            cv2.imshow(config.DEBUG_WINDOW_NAME, draw_debug_frame(frame, detections, nav_state))
            key = cv2.waitKey(1) & 0xFF
            if key == config.KILL_SWITCH_KEY:
                _stop_best_effort(robot_client)
                break

            time.sleep(config.LOOP_INTERVAL_S)
    finally:
        _stop_best_effort(robot_client)
        frame_grabber.release()
        cv2.destroyAllWindows()


def _stop_best_effort(robot_client):
    """Attempt /stop with retries; never raises, so cleanup/exit can't be skipped."""
    try:
        _stop_with_retries(robot_client)
    except requests.exceptions.RequestException:
        pass


def _wait_up_to(seconds):
    """Wait up to `seconds` (a bounded stream-reconnect backoff, capped at 10s).

    Does not poll the kill switch here: this previously called
    cv2.waitKey() in a loop, which hung indefinitely instead of returning
    every 50ms as documented on at least one real setup (Windows), freezing
    the whole process with no error and no way to recover short of killing
    it externally. The robot is already stopped for the whole duration of
    this wait (the caller stops it before calling this), so losing kill-
    switch responsiveness for this one bounded wait isn't a safety issue --
    it just means the kill switch takes up to `seconds` to register if
    pressed while the stream is down, rather than a real hang.
    """
    time.sleep(seconds)


if __name__ == "__main__":
    main()
