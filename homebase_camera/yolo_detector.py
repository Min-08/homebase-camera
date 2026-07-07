from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .state_engine import ZoneEvidence
from .zones import Zone, point_in_polygon


OBJECT_CLASSES = {
    "backpack",
    "handbag",
    "suitcase",
    "laptop",
    "book",
    "cell phone",
    "cup",
    "bottle",
    "umbrella",
}


@dataclass
class YoloStatus:
    available: bool
    message: str


class YoloDetector:
    def __init__(self, *, enabled: bool, model_name: str = "yolov8n.pt", interval_seconds: int = 20) -> None:
        self.enabled = bool(enabled)
        self.model_name = model_name
        self.interval_seconds = max(1, int(interval_seconds))
        self._last_run = 0.0
        self._model = None
        self.status = YoloStatus(False, "YOLO is disabled.")

        if self.enabled:
            self._load_model()

    def should_run(self) -> bool:
        return self.enabled and self.status.available and (time.monotonic() - self._last_run) >= self.interval_seconds

    def detect(self, frame: np.ndarray, zones: Iterable[Zone], *, force: bool = False) -> dict[str, ZoneEvidence]:
        if not force and not self.should_run():
            return {}

        self._last_run = time.monotonic()
        if self._model is None:
            return {}

        zone_list = list(zones)
        evidence = {zone.seat_id: ZoneEvidence(source="yolo") for zone in zone_list}
        try:
            results = self._model(frame, verbose=False)
        except Exception as exc:  # pragma: no cover - depends on optional model runtime
            self.status = YoloStatus(False, f"YOLO inference failed: {exc}")
            return {}

        names = getattr(self._model, "names", {}) or {}
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_idx = int(box.cls[0]) if getattr(box, "cls", None) is not None else -1
                label = str(names.get(cls_idx, cls_idx))
                confidence = float(box.conf[0]) if getattr(box, "conf", None) is not None else 0.0
                xyxy = box.xyxy[0].tolist()
                center = ((float(xyxy[0]) + float(xyxy[2])) / 2, (float(xyxy[1]) + float(xyxy[3])) / 2)

                for zone in zone_list:
                    if not point_in_polygon(center, zone.polygon):
                        continue
                    current = evidence[zone.seat_id]
                    if label == "person" and confidence > current.person_confidence:
                        evidence[zone.seat_id] = current.merge(
                            ZoneEvidence(
                                person_detected=True,
                                person_confidence=confidence,
                                source="yolo",
                                message="YOLO person center inside zone",
                            )
                        )
                    elif label in OBJECT_CLASSES and confidence > current.object_confidence:
                        evidence[zone.seat_id] = current.merge(
                            ZoneEvidence(
                                object_detected=True,
                                object_confidence=confidence,
                                object_classes=[label],
                                source="yolo",
                                message="YOLO object center inside zone",
                            )
                        )

        return evidence

    def _load_model(self) -> None:
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            self.status = YoloStatus(
                False,
                "YOLO is enabled in settings, but ultralytics is not installed. "
                "The app will continue in diff-only mode. Install with: pip install ultralytics",
            )
            return

        try:
            self._model = YOLO(self.model_name)
        except Exception as exc:  # pragma: no cover - optional dependency/model
            self.status = YoloStatus(False, f"Could not load YOLO model '{self.model_name}': {exc}")
            return

        self.status = YoloStatus(True, f"YOLO model loaded: {self.model_name}")
