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


def step(nav_state, detections, *, confidence_threshold, deadzone_fraction,
          arrival_height_fraction, lost_target_ticks, rotation_steps_per_sweep):
    """Placeholder - will be implemented in later steps."""
    return Command(CommandType.NONE), NavigatorState()
