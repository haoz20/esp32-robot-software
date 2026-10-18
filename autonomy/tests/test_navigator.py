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


def test_searching_with_no_detections_taps_left_and_counts_steps():
    nav_state = NavigatorState(state=State.SEARCHING, rotation_step=0)
    command, next_state = step(nav_state, [], **SEARCH_KWARGS)
    assert command == Command(CommandType.TURN_LEFT)
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


CONTINUOUS_KWARGS = dict(
    SEARCH_KWARGS,
    continuous_search=True,
    search_confidence_threshold=0.3,
    max_spin_s=8.0,
    max_correction_steps=2,
)


def test_continuous_search_keeps_spinning_with_no_detections():
    command, next_state = step(NavigatorState(state=State.SEARCHING), [],
                               spin_elapsed_s=1.0, **CONTINUOUS_KWARGS)
    assert command == Command(CommandType.SPIN_RIGHT)
    assert next_state.state == State.SEARCHING


def test_continuous_search_stops_and_confirms_on_a_sighting():
    # 0.4 is below the approach threshold but above the search threshold:
    # mid-spin frames are blurred, so a weak sighting is enough to stop.
    blurry = make_detection(confidence=0.4)
    command, next_state = step(NavigatorState(state=State.SEARCHING), [blurry],
                               **CONTINUOUS_KWARGS)
    assert command == Command(CommandType.STOP)
    assert next_state.state == State.CONFIRMING
    assert next_state.correction_step == 0


def test_continuous_search_ignores_detections_below_the_search_threshold():
    noise = make_detection(confidence=0.1)
    command, _ = step(NavigatorState(state=State.SEARCHING), [noise], **CONTINUOUS_KWARGS)
    assert command == Command(CommandType.SPIN_RIGHT)


def test_continuous_search_creeps_forward_after_spinning_too_long():
    command, next_state = step(NavigatorState(state=State.SEARCHING), [],
                               spin_elapsed_s=8.0, **CONTINUOUS_KWARGS)
    assert command == Command(CommandType.CREEP_FORWARD)
    assert next_state.state == State.SEARCHING


def test_confirming_with_target_on_still_frame_acts_as_approaching():
    left_target = make_detection(x_center=0.2, height=0.2)
    command, next_state = step(NavigatorState(state=State.CONFIRMING), [left_target],
                               **CONTINUOUS_KWARGS)
    assert command == Command(CommandType.TURN_LEFT)
    assert next_state.state == State.APPROACHING


def test_confirming_without_target_turns_back_left_to_undo_overshoot():
    command, next_state = step(NavigatorState(state=State.CONFIRMING), [], **CONTINUOUS_KWARGS)
    assert command == Command(CommandType.TURN_LEFT)
    assert next_state.state == State.CONFIRMING
    assert next_state.correction_step == 1


def test_confirming_gives_up_and_searches_again_after_max_corrections():
    nav_state = NavigatorState(state=State.CONFIRMING, correction_step=2)
    command, next_state = step(nav_state, [], **CONTINUOUS_KWARGS)
    assert command == Command(CommandType.NONE)
    assert next_state.state == State.SEARCHING


def test_confirming_requires_the_full_confidence_threshold():
    # A still frame should be clear; a weak hit there is not a confirmation.
    weak = make_detection(confidence=0.4)
    command, next_state = step(NavigatorState(state=State.CONFIRMING), [weak],
                               **CONTINUOUS_KWARGS)
    assert command == Command(CommandType.TURN_LEFT)
    assert next_state.state == State.CONFIRMING


def test_pulse_search_is_still_the_default():
    command, _ = step(NavigatorState(state=State.SEARCHING), [], **SEARCH_KWARGS)
    assert command == Command(CommandType.TURN_LEFT)


def test_search_ignores_a_target_below_the_approach_threshold():
    # 0.7 would have been approached before; now only > 0.8 counts.
    weak = make_detection(confidence=0.7)
    command, next_state = step(NavigatorState(state=State.SEARCHING), [weak],
                               **dict(SEARCH_KWARGS, confidence_threshold=0.8))
    assert command == Command(CommandType.TURN_LEFT)
    assert next_state.state == State.SEARCHING


def test_approach_uses_short_creeps_once_the_target_is_near():
    near = make_detection(x_center=0.5, height=0.7)
    command, next_state = step(NavigatorState(state=State.APPROACHING), [near],
                               near_height_fraction=0.6,
                               **dict(SEARCH_KWARGS, arrival_height_fraction=0.85))
    assert command == Command(CommandType.CREEP_FORWARD_SHORT)
    assert next_state.state == State.APPROACHING


def test_approach_uses_normal_creeps_while_the_target_is_far():
    far = make_detection(x_center=0.5, height=0.3)
    command, _ = step(NavigatorState(state=State.APPROACHING), [far],
                      near_height_fraction=0.6,
                      **dict(SEARCH_KWARGS, arrival_height_fraction=0.85))
    assert command == Command(CommandType.CREEP_FORWARD)


def test_approach_centers_before_creeping_even_when_near():
    near_left = make_detection(x_center=0.2, height=0.7)
    command, _ = step(NavigatorState(state=State.APPROACHING), [near_left],
                      near_height_fraction=0.6,
                      **dict(SEARCH_KWARGS, arrival_height_fraction=0.85))
    assert command == Command(CommandType.TURN_LEFT)
