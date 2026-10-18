"""Pure navigation state machine.

No dependency on requests, cv2, or ultralytics — this module only reasons
about Detection values and NavigatorState, so it is fully unit-testable
without the robot, camera, or model present.

Two search modes. Pulse search (the default) turns in fixed steps, looking
after each one. Continuous search (continuous_search=True) keeps the robot
spinning right (SPIN_RIGHT) and looks at every frame, which finds a target
much faster -- but a frame taken mid-spin is blurred and, by the time
detection returns, the robot has already turned past it. So a sighting
while spinning only stops the robot (STOP) and moves to CONFIRMING, which
re-checks on a still frame and, if the target isn't there, turns back left
in pulses to undo the overshoot.
"""

from dataclasses import dataclass
from enum import Enum, auto


class State(Enum):
    SEARCHING = auto()
    CONFIRMING = auto()
    APPROACHING = auto()
    ARRIVED = auto()


class CommandType(Enum):
    TURN_LEFT = auto()
    TURN_RIGHT = auto()
    CREEP_FORWARD = auto()
    SPIN_RIGHT = auto()  # start (or keep) turning right with no stop
    STOP = auto()
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
    correction_step: int = 0


def best_detection(detections, confidence_threshold):
    candidates = [d for d in detections if d.confidence >= confidence_threshold]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.confidence)


def step(nav_state, detections, *, confidence_threshold, deadzone_fraction,
          arrival_height_fraction, lost_target_ticks, rotation_steps_per_sweep,
          continuous_search=False, search_confidence_threshold=None,
          spin_elapsed_s=0.0, max_spin_s=float("inf"), max_correction_steps=0):
    """Decide the next command.

    Continuous-search-only arguments: search_confidence_threshold (lower
    than confidence_threshold, since mid-spin frames are blurred; defaults
    to confidence_threshold), spin_elapsed_s (how long the current spin has
    run, tracked by the caller since this module has no clock), max_spin_s
    (after this long without a sighting, creep forward for a new vantage
    point), and max_correction_steps (left pulses CONFIRMING tries before
    giving up and spinning again).
    """
    target = best_detection(detections, confidence_threshold)
    state = nav_state.state

    if state == State.SEARCHING and continuous_search:
        if search_confidence_threshold is None:
            search_confidence_threshold = confidence_threshold
        if best_detection(detections, search_confidence_threshold) is not None:
            return Command(CommandType.STOP), NavigatorState(state=State.CONFIRMING)
        if spin_elapsed_s >= max_spin_s:
            return Command(CommandType.CREEP_FORWARD), NavigatorState(state=State.SEARCHING)
        return Command(CommandType.SPIN_RIGHT), NavigatorState(state=State.SEARCHING)

    if state == State.CONFIRMING:
        if target is None:
            if nav_state.correction_step >= max_correction_steps:
                return Command(CommandType.NONE), NavigatorState(state=State.SEARCHING)
            return Command(CommandType.TURN_LEFT), NavigatorState(
                state=State.CONFIRMING, correction_step=nav_state.correction_step + 1
            )
        state = State.APPROACHING

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
