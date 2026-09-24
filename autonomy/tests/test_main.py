import pytest
import requests

from autonomy import config
from autonomy.main import run_tick
from autonomy.navigator import Command, CommandType, NavigatorState, State


class FakeDetector:
    def __init__(self, detections):
        self._detections = detections

    def detect(self, frame):
        return self._detections


class FakeRobotClient:
    def __init__(self):
        self.calls = []

    def go(self):
        self.calls.append("go")

    def back(self):
        self.calls.append("back")

    def left(self):
        self.calls.append("left")

    def right(self):
        self.calls.append("right")

    def stop(self):
        self.calls.append("stop")


def test_run_tick_pulses_then_stops_for_a_turn_command():
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=0)
    detector = FakeDetector([])
    robot_client = FakeRobotClient()
    sleeps = []

    command, next_state, detections = run_tick(
        nav_state, frame="fake-frame", detector=detector,
        robot_client=robot_client, sleep=sleeps.append
    )

    assert command == Command(CommandType.TURN_RIGHT)
    assert next_state.state == State.SEARCHING
    assert detections == []
    assert robot_client.calls == ["right", "stop"]
    assert len(sleeps) == 1


def test_run_tick_issues_no_robot_calls_once_arrived():
    nav_state = NavigatorState(state=State.ARRIVED)
    detector = FakeDetector([])
    robot_client = FakeRobotClient()

    command, next_state, detections = run_tick(
        nav_state, frame="fake-frame", detector=detector,
        robot_client=robot_client, sleep=lambda s: None
    )

    assert command == Command(CommandType.NONE)
    assert next_state.state == State.ARRIVED
    assert robot_client.calls == []


class RaisingOnceRobotClient(FakeRobotClient):
    """right() raises once, then behaves normally; stop() always succeeds."""

    def __init__(self):
        super().__init__()
        self._right_raised = False

    def right(self):
        if not self._right_raised:
            self._right_raised = True
            self.calls.append("right (raised)")
            raise requests.exceptions.ConnectionError("simulated network failure")
        super().right()


def test_run_tick_still_stops_when_the_movement_call_fails():
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=0)
    detector = FakeDetector([])
    robot_client = RaisingOnceRobotClient()

    run_tick(
        nav_state, frame="fake-frame", detector=detector,
        robot_client=robot_client, sleep=lambda s: None
    )

    assert robot_client.calls == ["right (raised)", "stop"]


def test_a_dropped_movement_command_is_not_fatal_and_is_retried_next_tick():
    # The robot's own control page fires commands and ignores failures; one
    # dropped request on a busy WiFi link must not end the autonomy run.
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=3)
    detector = FakeDetector([])
    robot_client = RaisingOnceRobotClient()

    command, next_state, _ = run_tick(
        nav_state, frame="fake-frame", detector=detector,
        robot_client=robot_client, sleep=lambda s: None
    )

    assert command == Command(CommandType.NONE)
    assert next_state == nav_state  # not advanced: the turn never happened

    command, next_state, _ = run_tick(
        next_state, frame="fake-frame", detector=detector,
        robot_client=robot_client, sleep=lambda s: None
    )

    assert command == Command(CommandType.TURN_RIGHT)
    assert next_state.rotation_step == 4
    assert robot_client.calls == ["right (raised)", "stop", "right", "stop"]


class FlakyStopRobotClient(FakeRobotClient):
    """stop() fails a fixed number of times, then succeeds."""

    def __init__(self, fail_times):
        super().__init__()
        self._fail_times = fail_times

    def stop(self):
        if self._fail_times > 0:
            self._fail_times -= 1
            self.calls.append("stop (failed)")
            raise requests.exceptions.ConnectionError("simulated network failure")
        self.calls.append("stop")


def test_run_tick_retries_stop_before_giving_up():
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=0)
    detector = FakeDetector([])
    robot_client = FlakyStopRobotClient(fail_times=2)
    sleeps = []

    run_tick(
        nav_state, frame="fake-frame", detector=detector,
        robot_client=robot_client, sleep=sleeps.append
    )

    assert robot_client.calls == ["right", "stop (failed)", "stop (failed)", "stop"]
    # one sleep for the pulse duration, two for the stop-retry backoff
    assert len(sleeps) == 3


@pytest.mark.parametrize(
    "command_type, expected_call, expected_pulse_s",
    [
        (CommandType.TURN_LEFT, "left", config.TURN_PULSE_S),
        (CommandType.TURN_RIGHT, "right", config.TURN_PULSE_S),
        (CommandType.CREEP_FORWARD, "go", config.CREEP_PULSE_S),
    ],
)
def test_run_tick_dispatches_each_command_to_the_right_call_and_pulse(
    command_type, expected_call, expected_pulse_s, monkeypatch
):
    from autonomy import main as main_module

    monkeypatch.setattr(
        main_module, "step",
        lambda *a, **k: (Command(command_type), NavigatorState(state=State.SEARCHING)),
    )

    robot_client = FakeRobotClient()
    sleeps = []
    run_tick(
        NavigatorState(state=State.SEARCHING), frame="fake-frame",
        detector=FakeDetector([]), robot_client=robot_client, sleep=sleeps.append,
    )

    assert robot_client.calls == [expected_call, "stop"]
    assert sleeps == [expected_pulse_s]


class AlwaysFailingStopRobotClient(FakeRobotClient):
    def stop(self):
        self.calls.append("stop (failed)")
        raise requests.exceptions.ConnectionError("simulated network failure")


def test_run_tick_reraises_after_all_stop_retries_are_exhausted():
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=0)
    detector = FakeDetector([])
    robot_client = AlwaysFailingStopRobotClient()

    with pytest.raises(requests.exceptions.ConnectionError):
        run_tick(
            nav_state, frame="fake-frame", detector=detector,
            robot_client=robot_client, sleep=lambda s: None
        )

    assert robot_client.calls == ["right", "stop (failed)", "stop (failed)", "stop (failed)"]
