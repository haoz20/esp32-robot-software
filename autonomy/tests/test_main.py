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
