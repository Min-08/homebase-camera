from __future__ import annotations

import numpy as np
from PIL import Image

from homebase_camera.diff_detector import DiffDetector
from homebase_camera.zones import Zone


ZONE = Zone(
    seat_id="seat_001",
    seat_name="Seat 1",
    polygon=((2, 2), (15, 2), (15, 15), (2, 15)),
)


def test_corrupted_baseline_warning_is_preserved_when_using_temporary_baseline(tmp_path):
    baseline_path = tmp_path / "baseline.jpg"
    baseline_path.write_bytes(b"not an image")
    detector = DiffDetector(baseline_path=baseline_path)

    evidence = detector.analyze(np.zeros((20, 20, 3), dtype=np.uint8), [ZONE])

    assert evidence["seat_001"].message == "temporary baseline initialized"
    assert detector.warning is not None
    assert "Could not read baseline image" in detector.warning
    assert "temporary baseline" in detector.warning


def test_baseline_resolution_mismatch_warns_and_continues(tmp_path):
    baseline_path = tmp_path / "baseline.jpg"
    Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(baseline_path)
    detector = DiffDetector(baseline_path=baseline_path)

    evidence = detector.analyze(np.zeros((20, 20, 3), dtype=np.uint8), [ZONE])

    assert "seat_001" in evidence
    assert detector.warning is not None
    assert "Baseline resolution 10x10 does not match current frame 20x20" in detector.warning
