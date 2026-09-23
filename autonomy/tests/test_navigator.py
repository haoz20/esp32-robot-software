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
