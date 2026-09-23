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
