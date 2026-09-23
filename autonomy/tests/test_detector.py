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
