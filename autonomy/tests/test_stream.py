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
