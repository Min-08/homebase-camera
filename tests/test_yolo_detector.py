from __future__ import annotations

import builtins

import numpy as np

from homebase_camera.yolo_detector import YoloDetector, YoloStatus
from homebase_camera.zones import Zone


ZONE = Zone("seat_001", "Seat 1", ((0, 0), (9, 0), (9, 9), (0, 9)))


def test_missing_ultralytics_keeps_yolo_unavailable(monkeypatch):
    original_import = builtins.__import__

    def missing_ultralytics(name, *args, **kwargs):
        if name == "ultralytics":
            raise ModuleNotFoundError("synthetic missing ultralytics")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_ultralytics)

    detector = YoloDetector(enabled=True)

    assert detector.status.available is False
    assert "ultralytics is not installed" in detector.status.message


def test_inference_exception_disables_yolo_without_raising():
    class BrokenModel:
        def __call__(self, frame, verbose=False):
            raise RuntimeError("synthetic inference failure")

    detector = YoloDetector(enabled=False)
    detector.enabled = True
    detector._model = BrokenModel()
    detector.status = YoloStatus(True, "test model")

    result = detector.detect(np.zeros((10, 10, 3), dtype=np.uint8), [ZONE], force=True)

    assert result == {}
    assert detector.status.available is False
    assert "synthetic inference failure" in detector.status.message
