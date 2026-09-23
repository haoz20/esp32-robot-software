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
