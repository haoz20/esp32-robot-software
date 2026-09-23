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
