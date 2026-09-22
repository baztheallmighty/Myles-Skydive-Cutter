"""The person detector: loading it, and reading people out of one frame.

Ultralytics is AGPL-3.0 and is installed on the user's own machine rather than shipped, so this module is the only
place that touches it.
"""
from dataclasses import dataclass
import os

from app import PROJECT_ROOT


@dataclass(frozen=True)
class DetectionBox:
    """One person in one frame. Areas are percentages of that frame, so views of different sizes compare."""
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    frame_width: int
    frame_height: int

    @property
    def box_area_percent(self):
        frame_area = float(max(1, self.frame_width * self.frame_height))
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1) / frame_area * 100.0


def load_yolo_model(model_path):
    """Load the local weights. Nothing is downloaded: this app works offline after setup."""
    config_root = PROJECT_ROOT / '.ultralytics'
    config_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('YOLO_CONFIG_DIR', str(config_root))
    from ultralytics import YOLO
    return YOLO(model_path)


def find_person_class_ids(model):
    names = getattr(model, 'names', {})
    if isinstance(names, dict):
        return [int(class_id) for class_id, name in names.items() if str(name) == 'person']
    try:
        return [index for index, name in enumerate(names) if str(name) == 'person']
    except TypeError:
        return []


def detect_people(model, frame, confidence_threshold, person_class_ids):
    """Every person the detector is sure enough about, in one frame."""
    frame_height, frame_width = frame.shape[:2]
    results = model.predict(source=frame, conf=confidence_threshold,
                            classes=person_class_ids or None, verbose=False)
    boxes = []
    for result in results:
        for box in getattr(result, 'boxes', None) or []:
            confidence = float(box.conf[0].item())
            if confidence < confidence_threshold:
                continue
            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
            boxes.append(DetectionBox(confidence, x1, y1, x2, y2, int(frame_width), int(frame_height)))
    return boxes
