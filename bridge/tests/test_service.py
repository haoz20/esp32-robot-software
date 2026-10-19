import threading
import time

from autonomy.navigator import Detection, NavigatorState, State
from bridge.service import Bridge


class FakeGrabber:
    def __init__(self):
        self.frame_id = 0
        self.frame = None
        self.age_s = None
        self.released = False

    def push(self, frame):
        self.frame_id += 1
        self.frame = frame
        self.age_s = 0.0

    def latest(self):
        return self.frame_id, self.frame, self.age_s

    def release(self):
        self.released = True


class FakeRobotClient:
    def __init__(self, calls):
        self._calls = calls

    def stop(self):
        self._calls.append("stop")


class FakeDetector:
    def __init__(self, detections):
        self.detections = detections
        self.frames = []

    def detect(self, frame):
        self.frames.append(frame)
        return self.detections


def _sighting():
    return Detection(label="red_bottle", confidence=0.9, x_center=0.5, y_center=0.5,
                     width=0.2, height=0.2)


class FakeControlLoop:
    """Stands in for autonomy's control_loop: publishes, then waits to be stopped."""

    def __init__(self):
        self.started = threading.Event()
        self.runs = 0

    def __call__(self, frame_grabber, detector, robot_client, view, stop_event):
        self.runs += 1
        view.publish([_sighting()], NavigatorState(state=State.APPROACHING))
        self.started.set()
        stop_event.wait(5.0)


def _wait_for(predicate, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def make_bridge(detector=None, control_loop=None, clock=time.monotonic, start_threads=False):
    calls = []
    bridge = Bridge(
        FakeGrabber(), detector if detector is not None else FakeDetector([]),
        lambda: FakeRobotClient(calls),
        control_loop=control_loop or FakeControlLoop(), clock=clock,
        start_threads=start_threads, log=lambda msg: None,
    )
    return bridge, calls


def test_modes_start_off():
    bridge, _ = make_bridge()
    status = bridge.status()
    assert status["auto"] is False
    assert status["detect"] is False
    assert status["detector_available"] is True


def test_auto_on_runs_the_control_loop_and_reports_its_state():
    loop = FakeControlLoop()
    bridge, _ = make_bridge(control_loop=loop)

    bridge.set_modes(auto=True)
    assert loop.started.wait(2.0)

    status = bridge.status()
    assert status["auto"] is True
    assert status["nav_state"] == "APPROACHING"
    bridge.set_modes(auto=False)


def test_auto_off_stops_the_robot_and_ends_the_loop():
    loop = FakeControlLoop()
    bridge, calls = make_bridge(control_loop=loop)
    bridge.set_modes(auto=True)
    assert loop.started.wait(2.0)

    status = bridge.set_modes(auto=False)

    assert status["auto"] is False
    assert calls.count("stop") >= 1
    assert status["nav_state"] is None


def test_turning_auto_on_twice_runs_one_loop():
    loop = FakeControlLoop()
    bridge, _ = make_bridge(control_loop=loop)
    bridge.set_modes(auto=True)
    assert loop.started.wait(2.0)
    bridge.set_modes(auto=True)
    assert loop.runs == 1
    bridge.set_modes(auto=False)


def test_watchdog_turns_auto_off_when_the_ui_stops_polling():
    clock = [100.0]
    loop = FakeControlLoop()
    bridge, calls = make_bridge(control_loop=loop, clock=lambda: clock[0])
    bridge.set_modes(auto=True)
    assert loop.started.wait(2.0)

    clock[0] = 102.0
    bridge.check_heartbeat()
    assert bridge.status()["auto"] is True  # 2s < 3s timeout

    clock[0] = 104.0
    bridge.check_heartbeat()
    assert bridge.status()["auto"] is False
    assert "stop" in calls


def test_heartbeat_keeps_auto_running():
    clock = [100.0]
    loop = FakeControlLoop()
    bridge, _ = make_bridge(control_loop=loop, clock=lambda: clock[0])
    bridge.set_modes(auto=True)
    assert loop.started.wait(2.0)

    for _ in range(5):
        clock[0] += 2.0
        bridge.heartbeat()
        bridge.check_heartbeat()
    assert bridge.status()["auto"] is True
    bridge.set_modes(auto=False)


def test_detection_boxes_are_only_reported_while_detect_is_on():
    detector = FakeDetector([_sighting()])
    bridge, _ = make_bridge(detector=detector, start_threads=True)
    try:
        bridge.frame_grabber.push("frame-1")
        bridge.set_modes(detect=True)
        assert _wait_for(lambda: bridge.status()["detections"]), "worker never detected"
        assert bridge.status()["detections"][0]["label"] == "red_bottle"

        bridge.set_modes(detect=False)
        assert bridge.status()["detections"] == []
    finally:
        bridge.shutdown()


def test_detect_worker_idles_while_autonomy_runs_detection_itself():
    detector = FakeDetector([_sighting()])
    loop = FakeControlLoop()
    bridge, _ = make_bridge(detector=detector, control_loop=loop, start_threads=True)
    try:
        bridge.set_modes(auto=True, detect=True)
        assert loop.started.wait(2.0)
        bridge.frame_grabber.push("frame-1")
        time.sleep(0.2)
        assert detector.frames == []  # only the control loop would have called it
        # Boxes come from the control loop's view instead.
        assert bridge.status()["detections"][0]["label"] == "red_bottle"
    finally:
        bridge.shutdown()


def test_modes_are_refused_without_a_model():
    calls = []
    bridge = Bridge(FakeGrabber(), None, lambda: FakeRobotClient(calls),
                    control_loop=FakeControlLoop(), start_threads=False, log=lambda m: None)
    status = bridge.set_modes(auto=True, detect=True)
    assert status["detector_available"] is False
    assert status["auto"] is False
    assert status["detect"] is False


def test_shutdown_stops_the_robot_and_releases_the_stream():
    loop = FakeControlLoop()
    bridge, calls = make_bridge(control_loop=loop, start_threads=True)
    bridge.set_modes(auto=True)
    assert loop.started.wait(2.0)

    bridge.shutdown()

    assert bridge.status()["auto"] is False
    assert "stop" in calls
    assert bridge.frame_grabber.released
