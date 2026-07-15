from __future__ import annotations

import builtins

import numpy as np

from homebase_camera.state_engine import ZoneEvidence
from homebase_camera.yolo_detector import AsyncYoloDetector, YoloDetector, YoloStatus, _best_zone_for_box
from homebase_camera.zones import Zone


ZONE = Zone("seat_001", "Seat 1", ((0, 0), (9, 0), (9, 9), (0, 9)))


def test_missing_ultralytics_keeps_yolo_unavailable(monkeypatch):
    original_import = builtins.__import__

    def missing_ultralytics(name, *args, **kwargs):
        if name == "ultralytics":
            raise ModuleNotFoundError("synthetic missing ultralytics")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_ultralytics)

    detector = YoloDetector(enabled=True, model_name="legacy-test.pt")

    assert detector.status.available is False
    assert "ultralytics is not installed" in detector.status.message


def test_missing_onnx_model_keeps_yolo_unavailable(tmp_path):
    detector = YoloDetector(enabled=True, model_name=str(tmp_path / "missing.onnx"))

    assert detector.status.available is False
    assert "YOLO ONNX model was not found" in detector.status.message


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


def test_person_box_uses_lower_body_anchor_to_match_seat_zone():
    seat = Zone("seat_001", "Seat 1", ((20, 70), (80, 70), (80, 100), (20, 100)))

    matched = _best_zone_for_box((25, 5, 75, 95), [seat])

    assert matched == seat


def test_async_detector_returns_without_blocking_caller():
    import time
    from types import SimpleNamespace

    class SlowDetector:
        enabled = True
        interval_seconds = 0
        status = SimpleNamespace(available=True)

        def detect(self, frame, zones, *, force=False):
            time.sleep(0.08)
            return {zones[0].seat_id: ZoneEvidence(person_checked=True, person_detected=True)}

    detector = AsyncYoloDetector(SlowDetector())  # type: ignore[arg-type]
    started = time.monotonic()
    assert detector.submit(np.zeros((12, 12, 3), dtype=np.uint8), [ZONE], sequence=7, diff_state={ZONE.seat_id: True})
    assert time.monotonic() - started < 0.05
    assert not detector.submit(np.zeros((12, 12, 3), dtype=np.uint8), [ZONE], sequence=8, diff_state={ZONE.seat_id: True})

    result = None
    deadline = time.monotonic() + 1
    while result is None and time.monotonic() < deadline:
        time.sleep(0.01)
        result = detector.poll()
    detector.close()

    assert result is not None
    assert result.submitted_sequence == 7
    assert result.submitted_diff_state == ((ZONE.seat_id, True),)
    assert result.submitted_zone_signature == ((ZONE.seat_id, ZONE.polygon),)
    assert result.evidence[ZONE.seat_id].person_detected


def test_async_detector_discards_result_after_invalidation():
    import time
    from types import SimpleNamespace

    class SlowDetector:
        enabled = True
        interval_seconds = 0
        status = SimpleNamespace(available=True)

        def detect(self, frame, zones, *, force=False):
            time.sleep(0.04)
            return {ZONE.seat_id: ZoneEvidence(person_checked=True, person_detected=True)}

    detector = AsyncYoloDetector(SlowDetector())  # type: ignore[arg-type]
    assert detector.submit(np.zeros((12, 12, 3), dtype=np.uint8), [ZONE], sequence=1, diff_state={ZONE.seat_id: True})
    detector.invalidate()
    time.sleep(0.08)

    assert detector.poll() is None
    detector.close()
