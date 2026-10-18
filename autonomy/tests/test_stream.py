import threading
import time

import pytest

from autonomy.stream import FrameGrabber


class FakeCapture:
    def __init__(self, url):
        self.url = url
        self.reads = [(True, "frame1"), (True, "frame2"), (False, None)]
        self.released = False

    def read(self):
        if not self.reads:
            return False, None
        return self.reads.pop(0)

    def release(self):
        self.released = True


def test_frame_grabber_builds_the_stream_url():
    captures = []

    def factory(url):
        capture = FakeCapture(url)
        captures.append(capture)
        return capture

    grabber = FrameGrabber("192.168.4.1", port=81, capture_factory=factory, start_thread=False)
    assert captures[0].url == "http://192.168.4.1:81/stream"


def test_read_raises_when_no_frame_has_arrived_yet():
    grabber = FrameGrabber("192.168.4.1", capture_factory=FakeCapture, start_thread=False)
    with pytest.raises(RuntimeError):
        grabber.read()


def test_read_returns_the_latest_stored_frame_when_fresh():
    clock = [100.0]
    grabber = FrameGrabber(
        "192.168.4.1", capture_factory=FakeCapture, start_thread=False,
        clock=lambda: clock[0], max_frame_age_s=1.0,
    )
    grabber._store_frame("frame1")
    clock[0] = 100.5  # 0.5s later, still fresh
    assert grabber.read() == "frame1"


def test_read_raises_when_the_stored_frame_has_gone_stale():
    clock = [100.0]
    grabber = FrameGrabber(
        "192.168.4.1", capture_factory=FakeCapture, start_thread=False,
        clock=lambda: clock[0], max_frame_age_s=1.0,
    )
    grabber._store_frame("frame1")
    clock[0] = 102.0  # 2s later, stale
    with pytest.raises(RuntimeError):
        grabber.read()


def test_release_delegates_to_the_underlying_capture():
    captures = []

    def factory(url):
        capture = FakeCapture(url)
        captures.append(capture)
        return capture

    grabber = FrameGrabber("192.168.4.1", capture_factory=factory, start_thread=False)
    grabber.release()
    assert captures[0].released is True


class BlockingFakeCapture:
    """A capture whose read() blocks until the test pushes a frame."""

    def __init__(self, url):
        self.url = url
        self._ready = threading.Event()
        self._frame = None
        self.released = False

    def push_frame(self, frame):
        self._frame = frame
        self._ready.set()

    def read(self):
        self._ready.wait(timeout=2.0)
        self._ready.clear()
        return True, self._frame

    def release(self):
        self.released = True


def test_background_thread_picks_up_frames_pushed_to_the_capture():
    captures = []

    def factory(url):
        capture = BlockingFakeCapture(url)
        captures.append(capture)
        return capture

    grabber = FrameGrabber("192.168.4.1", capture_factory=factory)
    captures[0].push_frame("live-frame")

    deadline = time.monotonic() + 2.0
    picked_up = False
    while time.monotonic() < deadline:
        try:
            if grabber.read() == "live-frame":
                picked_up = True
                break
        except RuntimeError:
            pass
        time.sleep(0.01)

    grabber.release()
    assert picked_up, "background thread never picked up the pushed frame"
    assert captures[0].released is True


def _wait_for(predicate, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class DyingCapture:
    """Returns one frame, then reports the connection dead."""

    def __init__(self, url, frame):
        self.url = url
        self._reads = [(True, frame)]
        self.released = False

    def read(self):
        if self._reads:
            return self._reads.pop(0)
        if self.released:
            return False, None
        time.sleep(0.01)
        return False, None

    def release(self):
        self.released = True


def test_background_thread_reconnects_after_the_connection_dies():
    captures = []

    def factory(url):
        capture = DyingCapture(url, frame=f"frame-from-connection-{len(captures) + 1}")
        captures.append(capture)
        return capture

    grabber = FrameGrabber("192.168.4.1", capture_factory=factory,
                           reconnect_backoff_s=0.01, log=lambda msg: None)
    try:
        assert _wait_for(lambda: len(captures) >= 2), "never reconnected"
        assert captures[0].released is True
        assert _wait_for(lambda: grabber.latest()[1] == "frame-from-connection-2")
    finally:
        grabber.release()


def test_a_failed_first_connect_is_retried_instead_of_raising():
    attempts = []

    def factory(url):
        attempts.append(url)
        if len(attempts) == 1:
            raise ConnectionError("robot not up yet")
        return BlockingFakeCapture(url)

    grabber = FrameGrabber("192.168.4.1", capture_factory=factory,
                           reconnect_backoff_s=0.01, log=lambda msg: None)
    try:
        assert _wait_for(lambda: len(attempts) >= 2), "first connect failure was not retried"
    finally:
        grabber.release()


def test_a_stale_frame_does_not_drop_the_connection():
    # read() raising on a stale frame only means "don't act on it"; the
    # connection must stay open so frames resume after a short WiFi gap.
    clock = [100.0]
    captures = []

    def factory(url):
        capture = FakeCapture(url)
        captures.append(capture)
        return capture

    grabber = FrameGrabber("192.168.4.1", capture_factory=factory, start_thread=False,
                           clock=lambda: clock[0], max_frame_age_s=1.0)
    grabber._store_frame("frame1")
    clock[0] = 102.0
    with pytest.raises(RuntimeError):
        grabber.read()
    assert len(captures) == 1
    assert captures[0].released is False


def test_latest_reports_frame_id_and_age_without_raising():
    clock = [100.0]
    grabber = FrameGrabber("192.168.4.1", capture_factory=FakeCapture, start_thread=False,
                           clock=lambda: clock[0])
    assert grabber.latest() == (0, None, None)

    grabber._store_frame("frame1")
    clock[0] = 105.0  # stale for read(), still fine for display
    assert grabber.latest() == (1, "frame1", 5.0)
