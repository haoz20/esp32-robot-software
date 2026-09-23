# Autonomy Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python service that drives the robot car toward a detected red or green bottle using the ESP32 camera and a YOLO model, searching by rotating-then-creeping when nothing is visible.

**Architecture:** A pure, hardware-free state machine (`navigator.py`) decides commands from detections; thin adapter modules (`robot_client.py`, `stream.py`, `detector.py`) wrap HTTP, the MJPEG stream, and YOLO inference respectively; `main.py` wires them into a poll loop with a live debug window and a keyboard kill switch.

**Tech Stack:** Python 3.11 (conda env), `ultralytics` (YOLO), `opencv-python` (stream capture + debug window), `requests` (HTTP to the robot), `pytest` (tests).

**Spec:** [docs/superpowers/specs/2026-09-23-autonomy-service-design.md](../specs/2026-09-23-autonomy-service-design.md)

## Global Constraints

- Drive endpoints (`/go`, `/back`, `/left`, `/right`) run **continuously until `/stop`** — every commanded move must be paired with an explicit follow-up `/stop` call after a fixed pulse duration. Never send a drive command without a paired stop.
- No obstacle/distance sensor exists on the robot — blind driving (search creep) is a real risk. Pulses must stay short and bounded; there is no "cancel mid-pulse" beyond the kill switch.
- Default robot IP is `192.168.4.1`; HTTP control port `80`; MJPEG stream port `81` at path `/stream`.
- `navigator.py` must have zero dependency on `requests`, `cv2`, or `ultralytics` — it is pure logic, unit tested without hardware.
- Environment is managed with conda (`autonomy/environment.yml`), not a bare `requirements.txt`.
- This plan assumes a trained model file will later be dropped at `autonomy/models/best.pt` with classes `red_bottle` / `green_bottle`. No task in this plan produces that file — data collection/training is separate follow-on work per the spec's "Open items deferred to later work."

---

## Task 1: Project scaffolding

**Files:**
- Create: `autonomy/__init__.py`
- Create: `autonomy/environment.yml`
- Create: `autonomy/config.py`
- Create: `autonomy/models/.gitkeep`
- Create: `autonomy/.gitignore`
- Create: `autonomy/README.md`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: module `autonomy.config` with constants `ROBOT_IP: str`, `ROBOT_HTTP_PORT: int`, `ROBOT_STREAM_PORT: int`, `ROBOT_HTTP_TIMEOUT_S: float`, `MODEL_PATH: str`, `CONFIDENCE_THRESHOLD: float`, `DEADZONE_FRACTION: float`, `ARRIVAL_HEIGHT_FRACTION: float`, `LOST_TARGET_TICKS: int`, `TURN_PULSE_S: float`, `CREEP_PULSE_S: float`, `ROTATION_STEPS_PER_SWEEP: int`, `LOOP_INTERVAL_S: float`, `KILL_SWITCH_KEY: int`

- [ ] **Step 1: Create the package init**

```python
# autonomy/__init__.py
```

(empty file — marks `autonomy/` as a Python package)

- [ ] **Step 2: Create the conda environment file**

```yaml
# autonomy/environment.yml
name: esp32-robot-autonomy
channels:
  - conda-forge
dependencies:
  - python=3.11
  - opencv
  - numpy
  - pip
  - pip:
      - ultralytics
      - requests
      - pytest
```

- [ ] **Step 3: Create the config module**

```python
# autonomy/config.py
"""Tunable constants for the autonomy service.

All values here are expected to need empirical tuning against the real
robot; nothing in navigator.py, detector.py, robot_client.py, or stream.py
hardcodes these inline.
"""

# --- Robot connection ---
ROBOT_IP = "192.168.4.1"
ROBOT_HTTP_PORT = 80
ROBOT_STREAM_PORT = 81
ROBOT_HTTP_TIMEOUT_S = 2.0

# --- Detection model ---
MODEL_PATH = "autonomy/models/best.pt"
CONFIDENCE_THRESHOLD = 0.5

# --- Navigation thresholds ---
DEADZONE_FRACTION = 0.15
ARRIVAL_HEIGHT_FRACTION = 0.6
LOST_TARGET_TICKS = 3
ROTATION_STEPS_PER_SWEEP = 12

# --- Motor pulse durations (seconds) ---
TURN_PULSE_S = 0.2
CREEP_PULSE_S = 0.4

# --- Control loop ---
LOOP_INTERVAL_S = 0.25
KILL_SWITCH_KEY = ord(" ")
```

- [ ] **Step 4: Create the gitignore for trained weights and caches**

```
# autonomy/.gitignore
models/*.pt
__pycache__/
.pytest_cache/
```

- [ ] **Step 5: Keep the models directory in git despite ignoring its contents**

```
# autonomy/models/.gitkeep
```

(empty file)

- [ ] **Step 6: Create a short README**

```markdown
# autonomy/README.md
# Autonomy service

Drives the robot toward a detected red or green bottle using the ESP32
camera and a YOLO model. Runs standalone, alongside the manual webapp
control — it only calls the robot's existing HTTP endpoints.

See [../docs/superpowers/specs/2026-09-23-autonomy-service-design.md](../docs/superpowers/specs/2026-09-23-autonomy-service-design.md)
for the design.

## Setup

    conda env create -f autonomy/environment.yml
    conda activate esp32-robot-autonomy

Drop a trained YOLO model (classes `red_bottle`, `green_bottle`) at
`autonomy/models/best.pt` before running.

## Run

    python -m autonomy.main

Press SPACE in the debug window to stop the robot and exit at any time.

## Test

    pytest autonomy/tests
```

- [ ] **Step 7: Verify the config module imports cleanly**

Run: `python -c "from autonomy import config; assert config.ROBOT_IP == '192.168.4.1'; print('ok')"`
Expected: prints `ok`

- [ ] **Step 8: Commit**

```bash
git add autonomy/__init__.py autonomy/environment.yml autonomy/config.py autonomy/.gitignore autonomy/models/.gitkeep autonomy/README.md
git commit -m "autonomy: add project scaffolding and config"
```

---

## Task 2: Navigator — domain types and state machine

**Files:**
- Create: `autonomy/navigator.py`
- Test: `autonomy/tests/__init__.py`
- Test: `autonomy/tests/test_navigator.py`

**Interfaces:**
- Consumes: nothing (pure logic, no imports from other autonomy modules)
- Produces:
  - `class State(Enum)`: members `SEARCHING`, `APPROACHING`, `ARRIVED`
  - `class CommandType(Enum)`: members `TURN_LEFT`, `TURN_RIGHT`, `CREEP_FORWARD`, `NONE`
  - `@dataclass(frozen=True) class Command`: field `type: CommandType`
  - `@dataclass(frozen=True) class Detection`: fields `label: str`, `confidence: float`, `x_center: float`, `y_center: float`, `width: float`, `height: float` (all normalized 0..1 fractions of frame size except `label`/`confidence`)
  - `@dataclass class NavigatorState`: fields `state: State = State.SEARCHING`, `rotation_step: int = 0`, `lost_ticks: int = 0`
  - `def best_detection(detections: list[Detection], confidence_threshold: float) -> Detection | None`
  - `def step(nav_state: NavigatorState, detections: list[Detection], *, confidence_threshold: float, deadzone_fraction: float, arrival_height_fraction: float, lost_target_ticks: int, rotation_steps_per_sweep: int) -> tuple[Command, NavigatorState]`

- [ ] **Step 1: Write failing tests for the domain types and `best_detection`**

```python
# autonomy/tests/__init__.py
```

(empty file)

```python
# autonomy/tests/test_navigator.py
from autonomy.navigator import (
    Command,
    CommandType,
    Detection,
    NavigatorState,
    State,
    best_detection,
    step,
)


def make_detection(label="red_bottle", confidence=0.9, x_center=0.5, y_center=0.5,
                    width=0.2, height=0.2):
    return Detection(label=label, confidence=confidence, x_center=x_center,
                      y_center=y_center, width=width, height=height)


def test_navigator_state_defaults_to_searching():
    nav_state = NavigatorState()
    assert nav_state.state == State.SEARCHING
    assert nav_state.rotation_step == 0
    assert nav_state.lost_ticks == 0


def test_best_detection_returns_none_when_empty():
    assert best_detection([], confidence_threshold=0.5) is None


def test_best_detection_filters_below_threshold():
    low = make_detection(confidence=0.2)
    assert best_detection([low], confidence_threshold=0.5) is None


def test_best_detection_picks_highest_confidence_across_colors():
    red = make_detection(label="red_bottle", confidence=0.6)
    green = make_detection(label="green_bottle", confidence=0.9)
    assert best_detection([red, green], confidence_threshold=0.5) is green
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest autonomy/tests/test_navigator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.navigator'`

- [ ] **Step 3: Implement the domain types and `best_detection`**

```python
# autonomy/navigator.py
"""Pure navigation state machine.

No dependency on requests, cv2, or ultralytics — this module only reasons
about Detection values and NavigatorState, so it is fully unit-testable
without the robot, camera, or model present.
"""

from dataclasses import dataclass
from enum import Enum, auto


class State(Enum):
    SEARCHING = auto()
    APPROACHING = auto()
    ARRIVED = auto()


class CommandType(Enum):
    TURN_LEFT = auto()
    TURN_RIGHT = auto()
    CREEP_FORWARD = auto()
    NONE = auto()


@dataclass(frozen=True)
class Command:
    type: CommandType


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    x_center: float
    y_center: float
    width: float
    height: float


@dataclass
class NavigatorState:
    state: State = State.SEARCHING
    rotation_step: int = 0
    lost_ticks: int = 0


def best_detection(detections, confidence_threshold):
    candidates = [d for d in detections if d.confidence >= confidence_threshold]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.confidence)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest autonomy/tests/test_navigator.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add autonomy/navigator.py autonomy/tests/__init__.py autonomy/tests/test_navigator.py
git commit -m "autonomy: add navigator domain types and best_detection"
```

- [ ] **Step 6: Write failing tests for SEARCHING behavior**

Append to `autonomy/tests/test_navigator.py`:

```python
SEARCH_KWARGS = dict(
    confidence_threshold=0.5,
    deadzone_fraction=0.15,
    arrival_height_fraction=0.6,
    lost_target_ticks=3,
    rotation_steps_per_sweep=3,
)


def test_searching_with_no_detections_turns_right_and_counts_steps():
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=0)
    command, next_state = step(nav_state, [], **SEARCH_KWARGS)
    assert command == Command(CommandType.TURN_RIGHT)
    assert next_state.state == State.SEARCHING
    assert next_state.rotation_step == 1


def test_searching_creeps_forward_after_full_sweep():
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=3)
    command, next_state = step(nav_state, [], **SEARCH_KWARGS)
    assert command == Command(CommandType.CREEP_FORWARD)
    assert next_state.state == State.SEARCHING
    assert next_state.rotation_step == 0


def test_searching_transitions_to_approaching_when_target_found():
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=2)
    centered_far = make_detection(x_center=0.5, height=0.2)
    command, next_state = step(nav_state, [centered_far], **SEARCH_KWARGS)
    assert next_state.state == State.APPROACHING
```

- [ ] **Step 7: Run the tests to verify they fail**

Run: `pytest autonomy/tests/test_navigator.py -v`
Expected: FAIL with `ImportError: cannot import name 'step' from 'autonomy.navigator'`

- [ ] **Step 8: Implement `step` for the SEARCHING branch**

Append to `autonomy/navigator.py`:

```python
def step(nav_state, detections, *, confidence_threshold, deadzone_fraction,
          arrival_height_fraction, lost_target_ticks, rotation_steps_per_sweep):
    target = best_detection(detections, confidence_threshold)
    state = nav_state.state

    if state == State.SEARCHING and target is not None:
        state = State.APPROACHING

    if state == State.SEARCHING:
        if nav_state.rotation_step >= rotation_steps_per_sweep:
            return Command(CommandType.CREEP_FORWARD), NavigatorState(
                state=State.SEARCHING, rotation_step=0, lost_ticks=0
            )
        return Command(CommandType.TURN_RIGHT), NavigatorState(
            state=State.SEARCHING, rotation_step=nav_state.rotation_step + 1, lost_ticks=0
        )

    # APPROACHING/ARRIVED handled in a later step
    return Command(CommandType.NONE), NavigatorState(state=state, rotation_step=0, lost_ticks=0)
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `pytest autonomy/tests/test_navigator.py -v`
Expected: PASS (7 tests)

- [ ] **Step 10: Commit**

```bash
git add autonomy/navigator.py autonomy/tests/test_navigator.py
git commit -m "autonomy: implement navigator SEARCHING behavior"
```

- [ ] **Step 11: Write failing tests for APPROACHING and ARRIVED behavior**

Append to `autonomy/tests/test_navigator.py`:

```python
def test_approaching_turns_left_when_target_is_left_of_center():
    nav_state = NavigatorState(state=State.APPROACHING)
    left_target = make_detection(x_center=0.2, height=0.2)
    command, next_state = step(nav_state, [left_target], **SEARCH_KWARGS)
    assert command == Command(CommandType.TURN_LEFT)
    assert next_state.state == State.APPROACHING


def test_approaching_turns_right_when_target_is_right_of_center():
    nav_state = NavigatorState(state=State.APPROACHING)
    right_target = make_detection(x_center=0.8, height=0.2)
    command, next_state = step(nav_state, [right_target], **SEARCH_KWARGS)
    assert command == Command(CommandType.TURN_RIGHT)
    assert next_state.state == State.APPROACHING


def test_approaching_creeps_forward_when_centered_but_small():
    nav_state = NavigatorState(state=State.APPROACHING)
    small_centered = make_detection(x_center=0.5, height=0.2)
    command, next_state = step(nav_state, [small_centered], **SEARCH_KWARGS)
    assert command == Command(CommandType.CREEP_FORWARD)
    assert next_state.state == State.APPROACHING


def test_approaching_arrives_when_centered_and_large():
    nav_state = NavigatorState(state=State.APPROACHING)
    close_centered = make_detection(x_center=0.5, height=0.9)
    command, next_state = step(nav_state, [close_centered], **SEARCH_KWARGS)
    assert command == Command(CommandType.NONE)
    assert next_state.state == State.ARRIVED


def test_approaching_reverts_to_searching_after_losing_target_for_n_ticks():
    nav_state = NavigatorState(state=State.APPROACHING, lost_ticks=0)
    command, next_state = step(nav_state, [], **SEARCH_KWARGS)
    assert next_state.state == State.APPROACHING
    assert next_state.lost_ticks == 1

    nav_state = next_state
    command, next_state = step(nav_state, [], **SEARCH_KWARGS)
    assert next_state.state == State.APPROACHING
    assert next_state.lost_ticks == 2

    nav_state = next_state
    command, next_state = step(nav_state, [], **SEARCH_KWARGS)
    assert next_state.state == State.SEARCHING
    assert next_state.lost_ticks == 0


def test_arrived_stays_arrived_and_issues_no_commands():
    nav_state = NavigatorState(state=State.ARRIVED)
    target = make_detection(x_center=0.5, height=0.9)
    command, next_state = step(nav_state, [target], **SEARCH_KWARGS)
    assert command == Command(CommandType.NONE)
    assert next_state.state == State.ARRIVED
```

- [ ] **Step 12: Run the tests to verify they fail**

Run: `pytest autonomy/tests/test_navigator.py -v`
Expected: FAIL — e.g. `test_approaching_turns_left_when_target_is_left_of_center` fails because `step` currently returns `Command(CommandType.NONE)` for APPROACHING instead of centering on the target.

- [ ] **Step 13: Implement the APPROACHING and ARRIVED branches**

Replace the final two lines of `step` in `autonomy/navigator.py` (the `# APPROACHING/ARRIVED handled in a later step` comment and the `return` below it) with:

```python
    if state == State.APPROACHING:
        if target is None:
            lost_ticks = nav_state.lost_ticks + 1
            if lost_ticks >= lost_target_ticks:
                return Command(CommandType.NONE), NavigatorState(
                    state=State.SEARCHING, rotation_step=0, lost_ticks=0
                )
            return Command(CommandType.NONE), NavigatorState(
                state=State.APPROACHING, rotation_step=0, lost_ticks=lost_ticks
            )

        offset = target.x_center - 0.5
        if abs(offset) > deadzone_fraction:
            turn = CommandType.TURN_LEFT if offset < 0 else CommandType.TURN_RIGHT
            return Command(turn), NavigatorState(
                state=State.APPROACHING, rotation_step=0, lost_ticks=0
            )

        if target.height < arrival_height_fraction:
            return Command(CommandType.CREEP_FORWARD), NavigatorState(
                state=State.APPROACHING, rotation_step=0, lost_ticks=0
            )

        return Command(CommandType.NONE), NavigatorState(
            state=State.ARRIVED, rotation_step=0, lost_ticks=0
        )

    # ARRIVED
    return Command(CommandType.NONE), NavigatorState(
        state=State.ARRIVED, rotation_step=0, lost_ticks=0
    )
```

- [ ] **Step 14: Run the tests to verify they pass**

Run: `pytest autonomy/tests/test_navigator.py -v`
Expected: PASS (13 tests)

- [ ] **Step 15: Commit**

```bash
git add autonomy/navigator.py autonomy/tests/test_navigator.py
git commit -m "autonomy: implement navigator APPROACHING and ARRIVED behavior"
```

---

## Task 3: Robot HTTP client

**Files:**
- Create: `autonomy/robot_client.py`
- Test: `autonomy/tests/test_robot_client.py`

**Interfaces:**
- Consumes: nothing
- Produces: `class RobotClient` with `__init__(self, ip: str, port: int = 80, timeout_s: float = 2.0)` and methods `go()`, `back()`, `left()`, `right()`, `stop()`, each taking no args and returning `None`

- [ ] **Step 1: Write failing tests**

```python
# autonomy/tests/test_robot_client.py
from unittest.mock import patch

from autonomy.robot_client import RobotClient


@patch("autonomy.robot_client.requests.get")
def test_go_calls_the_go_endpoint(mock_get):
    client = RobotClient("192.168.4.1", port=80, timeout_s=2.0)
    client.go()
    mock_get.assert_called_once_with("http://192.168.4.1:80/go", timeout=2.0)


@patch("autonomy.robot_client.requests.get")
def test_stop_calls_the_stop_endpoint(mock_get):
    client = RobotClient("192.168.4.1")
    client.stop()
    mock_get.assert_called_once_with("http://192.168.4.1:80/stop", timeout=2.0)


@patch("autonomy.robot_client.requests.get")
def test_left_and_right_call_distinct_endpoints(mock_get):
    client = RobotClient("192.168.4.1")
    client.left()
    client.right()
    assert mock_get.call_args_list[0].args == ("http://192.168.4.1:80/left",)
    assert mock_get.call_args_list[1].args == ("http://192.168.4.1:80/right",)


@patch("autonomy.robot_client.requests.get")
def test_back_calls_the_back_endpoint(mock_get):
    client = RobotClient("192.168.4.1")
    client.back()
    mock_get.assert_called_once_with("http://192.168.4.1:80/back", timeout=2.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest autonomy/tests/test_robot_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.robot_client'`

- [ ] **Step 3: Implement the client**

```python
# autonomy/robot_client.py
"""Thin HTTP wrapper around the robot's drive endpoints.

Mirrors the request pattern the existing webapp uses
(webapp/src/hooks/useRobot.js): a plain GET per command. The firmware's
drive endpoints run continuously until /stop is called — this class does
not pulse or time anything itself, that responsibility lives in main.py.
"""

import requests


class RobotClient:
    def __init__(self, ip, port=80, timeout_s=2.0):
        self._base_url = f"http://{ip}:{port}"
        self._timeout_s = timeout_s

    def go(self):
        self._send("/go")

    def back(self):
        self._send("/back")

    def left(self):
        self._send("/left")

    def right(self):
        self._send("/right")

    def stop(self):
        self._send("/stop")

    def _send(self, path):
        requests.get(f"{self._base_url}{path}", timeout=self._timeout_s)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest autonomy/tests/test_robot_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add autonomy/robot_client.py autonomy/tests/test_robot_client.py
git commit -m "autonomy: add robot HTTP client"
```

---

## Task 4: Camera stream frame grabber

**Files:**
- Create: `autonomy/stream.py`
- Test: `autonomy/tests/test_stream.py`

**Interfaces:**
- Consumes: nothing
- Produces: `class FrameGrabber` with `__init__(self, ip: str, port: int = 81, capture_factory=None)` and methods `read() -> frame` (raises `RuntimeError` if the underlying capture fails) and `release() -> None`

- [ ] **Step 1: Write failing tests using a fake capture object**

```python
# autonomy/tests/test_stream.py
import pytest

from autonomy.stream import FrameGrabber


class FakeCapture:
    def __init__(self, url):
        self.url = url
        self.reads = [(True, "frame1"), (True, "frame2"), (False, None)]
        self.released = False

    def read(self):
        return self.reads.pop(0)

    def release(self):
        self.released = True


def test_frame_grabber_builds_the_stream_url():
    captures = []

    def factory(url):
        capture = FakeCapture(url)
        captures.append(capture)
        return capture

    FrameGrabber("192.168.4.1", port=81, capture_factory=factory)
    assert captures[0].url == "http://192.168.4.1:81/stream"


def test_read_returns_the_frame_on_success():
    grabber = FrameGrabber("192.168.4.1", capture_factory=FakeCapture)
    assert grabber.read() == "frame1"
    assert grabber.read() == "frame2"


def test_read_raises_on_failed_capture():
    grabber = FrameGrabber("192.168.4.1", capture_factory=FakeCapture)
    grabber.read()
    grabber.read()
    with pytest.raises(RuntimeError):
        grabber.read()


def test_release_delegates_to_the_underlying_capture():
    captures = []

    def factory(url):
        capture = FakeCapture(url)
        captures.append(capture)
        return capture

    grabber = FrameGrabber("192.168.4.1", capture_factory=factory)
    grabber.release()
    assert captures[0].released is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest autonomy/tests/test_stream.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.stream'`

- [ ] **Step 3: Implement the frame grabber**

```python
# autonomy/stream.py
"""MJPEG frame grabber for the ESP32 camera stream.

Wraps cv2.VideoCapture, which can open the ESP32's MJPEG HTTP stream
directly. capture_factory is injectable so tests don't need a real camera
or cv2 installed.
"""


class FrameGrabber:
    def __init__(self, ip, port=81, capture_factory=None):
        if capture_factory is None:
            import cv2
            capture_factory = cv2.VideoCapture
        self._url = f"http://{ip}:{port}/stream"
        self._capture = capture_factory(self._url)

    def read(self):
        ok, frame = self._capture.read()
        if not ok:
            raise RuntimeError(f"failed to read frame from {self._url}")
        return frame

    def release(self):
        self._capture.release()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest autonomy/tests/test_stream.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add autonomy/stream.py autonomy/tests/test_stream.py
git commit -m "autonomy: add camera stream frame grabber"
```

---

## Task 5: YOLO detector

**Files:**
- Create: `autonomy/detector.py`
- Test: `autonomy/tests/test_detector.py`

**Interfaces:**
- Consumes: `Detection` from `autonomy.navigator` (Task 2)
- Produces: `class Detector` with `__init__(self, model_path: str, confidence_threshold: float, model_loader=None)` and method `detect(frame) -> list[Detection]`

- [ ] **Step 1: Write failing tests using a fake YOLO model**

```python
# autonomy/tests/test_detector.py
import numpy as np

from autonomy.detector import Detector
from autonomy.navigator import Detection


class FakeBox:
    def __init__(self, conf, cls, xyxy):
        self.conf = [conf]
        self.cls = [cls]
        self.xyxy = [xyxy]


class FakeResults:
    def __init__(self, boxes, names):
        self.boxes = boxes
        self.names = names


class FakeModel:
    def __init__(self, path):
        self.path = path
        self.next_results = FakeResults(boxes=[], names={0: "red_bottle", 1: "green_bottle"})

    def predict(self, frame, verbose=False):
        return [self.next_results]


def test_detector_loads_the_model_with_the_given_path():
    loaded_paths = []

    def loader(path):
        loaded_paths.append(path)
        return FakeModel(path)

    Detector("autonomy/models/best.pt", confidence_threshold=0.5, model_loader=loader)
    assert loaded_paths == ["autonomy/models/best.pt"]


def test_detect_converts_boxes_to_normalized_detections():
    model = FakeModel("autonomy/models/best.pt")
    box = FakeBox(conf=0.75, cls=1, xyxy=[100.0, 50.0, 300.0, 250.0])
    model.next_results = FakeResults(
        boxes=[box], names={0: "red_bottle", 1: "green_bottle"}
    )
    detector = Detector("path", confidence_threshold=0.5, model_loader=lambda p: model)

    frame = np.zeros((400, 400, 3), dtype=np.uint8)  # height=400, width=400
    detections = detector.detect(frame)

    assert detections == [
        Detection(
            label="green_bottle",
            confidence=0.75,
            x_center=200.0 / 400,
            y_center=150.0 / 400,
            width=200.0 / 400,
            height=200.0 / 400,
        )
    ]


def test_detect_filters_out_boxes_below_threshold():
    model = FakeModel("autonomy/models/best.pt")
    low_box = FakeBox(conf=0.2, cls=0, xyxy=[0.0, 0.0, 10.0, 10.0])
    model.next_results = FakeResults(
        boxes=[low_box], names={0: "red_bottle", 1: "green_bottle"}
    )
    detector = Detector("path", confidence_threshold=0.5, model_loader=lambda p: model)

    frame = np.zeros((400, 400, 3), dtype=np.uint8)
    assert detector.detect(frame) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest autonomy/tests/test_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.detector'`

- [ ] **Step 3: Implement the detector**

```python
# autonomy/detector.py
"""YOLO-based bottle detector.

Wraps an ultralytics-style model (anything exposing .predict(frame) ->
[results] with results.boxes and results.names) and converts its output
into our own normalized Detection values.
"""

from autonomy.navigator import Detection


class Detector:
    def __init__(self, model_path, confidence_threshold, model_loader=None):
        if model_loader is None:
            from ultralytics import YOLO
            model_loader = YOLO
        self._model = model_loader(model_path)
        self._confidence_threshold = confidence_threshold

    def detect(self, frame):
        results = self._model.predict(frame, verbose=False)[0]
        frame_h, frame_w = frame.shape[0], frame.shape[1]
        detections = []
        for box in results.boxes:
            confidence = float(box.conf[0])
            if confidence < self._confidence_threshold:
                continue
            label = results.names[int(box.cls[0])]
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
            detections.append(
                Detection(
                    label=label,
                    confidence=confidence,
                    x_center=((x1 + x2) / 2) / frame_w,
                    y_center=((y1 + y2) / 2) / frame_h,
                    width=(x2 - x1) / frame_w,
                    height=(y2 - y1) / frame_h,
                )
            )
        return detections
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest autonomy/tests/test_detector.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add autonomy/detector.py autonomy/tests/test_detector.py
git commit -m "autonomy: add YOLO detector wrapper"
```

---

## Task 6: Control loop, debug overlay, and kill switch

**Files:**
- Create: `autonomy/main.py`
- Test: `autonomy/tests/test_main.py`

**Interfaces:**
- Consumes: `RobotClient` (Task 3), `FrameGrabber` (Task 4), `Detector` (Task 5), `Command`/`CommandType`/`NavigatorState`/`State`/`step` from `autonomy.navigator` (Task 2), `config` (Task 1)
- Produces: `def run_tick(nav_state, frame, detector, robot_client, sleep=time.sleep) -> tuple[Command, NavigatorState, list[Detection]]`, `def draw_debug_frame(frame, detections, nav_state) -> frame`, `def main() -> None`

- [ ] **Step 1: Write failing tests for `run_tick` using fakes**

```python
# autonomy/tests/test_main.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest autonomy/tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.main'`

- [ ] **Step 3: Implement `run_tick` and `draw_debug_frame`, plus the `main` entry point**

```python
# autonomy/main.py
"""Wires the camera stream, detector, navigator, and robot client together.

The control loop, in order, each tick: grab a frame, detect, ask the
navigator for a command, execute it as a pulse-then-stop, draw the debug
overlay, and check the kill switch.
"""

import time

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
        getattr(robot_client, call_name)()
        sleep(_COMMAND_TO_PULSE_S[command.type])
        robot_client.stop()
    return command, new_nav_state, detections


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

    robot_client = RobotClient(
        config.ROBOT_IP, port=config.ROBOT_HTTP_PORT, timeout_s=config.ROBOT_HTTP_TIMEOUT_S
    )
    frame_grabber = FrameGrabber(config.ROBOT_IP, port=config.ROBOT_STREAM_PORT)
    detector = Detector(config.MODEL_PATH, config.CONFIDENCE_THRESHOLD)
    nav_state = NavigatorState()

    try:
        while True:
            try:
                frame = frame_grabber.read()
            except RuntimeError:
                robot_client.stop()
                time.sleep(1.0)
                continue

            _, nav_state, detections = run_tick(nav_state, frame, detector, robot_client)

            cv2.imshow("autonomy", draw_debug_frame(frame, detections, nav_state))
            key = cv2.waitKey(1) & 0xFF
            if key == config.KILL_SWITCH_KEY:
                robot_client.stop()
                break

            time.sleep(config.LOOP_INTERVAL_S)
    finally:
        robot_client.stop()
        frame_grabber.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest autonomy/tests/test_main.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest autonomy/tests -v`
Expected: PASS (all tests across navigator, robot_client, stream, detector, main)

- [ ] **Step 6: Commit**

```bash
git add autonomy/main.py autonomy/tests/test_main.py
git commit -m "autonomy: wire control loop, debug overlay, and kill switch"
```

- [ ] **Step 7: Manual end-to-end smoke test (requires the real robot and a trained model)**

This step has no automated test — it requires physical hardware and the
trained model file this plan doesn't produce. Perform it once
`autonomy/models/best.pt` exists:

1. `conda env create -f autonomy/environment.yml && conda activate esp32-robot-autonomy`
2. Power on the robot, join its WiFi AP, confirm `config.ROBOT_IP` matches (default `192.168.4.1`)
3. In a controlled, obstacle-light space: `python -m autonomy.main`
4. Confirm the debug window shows the live stream with detection boxes and the current state name
5. Hold a red or green bottle in view; confirm the car turns to center it, creeps forward, and stops (ARRIVED) once close
6. With no bottle in view, confirm it rotates in place, then creeps forward and resumes rotating
7. Press SPACE; confirm the robot stops within roughly one loop tick and the process exits

No commit for this step — it's verification, not code.

---

## Self-Review Notes

- **Spec coverage:** conda env (Task 1) · continuous-until-stop pulse semantics (Tasks 3, 6) · SEARCHING rotate-then-creep (Task 2) · APPROACHING centering/creep/arrival (Task 2) · lost-target reversion (Task 2) · single "approach whichever is seen" mission, no multi-bottle logic (Task 2, `best_detection` has no color preference) · debug window (Task 6) · kill switch (Task 6, `config.KILL_SWITCH_KEY`) · best-effort stop on stream/command failure (Task 6, `main()`) · unit-testable navigator with zero hardware deps (Task 2) · manual smoke test for the rest (Task 6, Step 7). All spec sections have a corresponding task.
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code or an explicit manual-verification checklist.
- **Type consistency:** `Detection`, `Command`, `CommandType`, `State`, `NavigatorState`, `step()` signatures match across Tasks 2, 5, and 6 (checked field names and argument order against each usage site).
