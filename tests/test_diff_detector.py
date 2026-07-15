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
ZONE_2 = Zone(
    seat_id="seat_002",
    seat_name="Seat 2",
    polygon=((2, 2), (15, 2), (15, 15), (2, 15)),
)
ZONE_A = Zone("seat_a", "Seat A", ((10, 10), (25, 10), (25, 25), (10, 25)))
ZONE_B = Zone("seat_b", "Seat B", ((35, 10), (50, 10), (50, 25), (35, 25)))
ZONE_C = Zone("seat_c", "Seat C", ((60, 10), (75, 10), (75, 25), (60, 25)))


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
    baseline = np.indices((10, 10)).sum(axis=0).astype(np.uint8) * 12
    Image.fromarray(np.stack([baseline, baseline, baseline], axis=-1)).save(baseline_path)
    detector = DiffDetector(baseline_path=baseline_path)

    evidence = detector.analyze(np.zeros((20, 20, 3), dtype=np.uint8), [ZONE])

    assert "seat_001" in evidence
    assert detector.warning is not None
    assert "Baseline resolution 10x10 does not match current frame 20x20" in detector.warning


def test_blank_saved_baseline_is_rejected_instead_of_flagging_every_zone(tmp_path):
    baseline_path = tmp_path / "baseline.jpg"
    Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8)).save(baseline_path)
    detector = DiffDetector(baseline_path=baseline_path, change_ratio_threshold=0.01)

    frame = np.full((20, 20, 3), 120, dtype=np.uint8)
    evidence = detector.analyze(frame, [ZONE])

    assert evidence["seat_001"].diff_changed is False
    assert "invalid baseline" in evidence["seat_001"].message
    assert detector.warning is not None
    assert "nearly black" in detector.warning or "not usable" in detector.warning


def test_global_scene_mismatch_does_not_publish_object_evidence(tmp_path):
    baseline_path = tmp_path / "baseline.jpg"
    baseline = np.indices((20, 20)).sum(axis=0).astype(np.uint8) * 6
    Image.fromarray(np.stack([baseline, baseline, baseline], axis=-1)).save(baseline_path)
    detector = DiffDetector(baseline_path=baseline_path, diff_threshold=10, change_ratio_threshold=0.01)

    frame = 255 - np.stack([baseline, baseline, baseline], axis=-1)
    evidence = detector.analyze(frame, [ZONE, ZONE_2])

    assert evidence["seat_001"].diff_changed is False
    assert evidence["seat_002"].diff_changed is False
    assert "baseline mismatch" in evidence["seat_001"].message
    assert detector.warning is not None
    assert "All seat zones changed heavily" in detector.warning


def test_camera_shift_with_background_change_is_blocked(tmp_path):
    baseline_path = tmp_path / "baseline.jpg"
    rng = np.random.default_rng(42)
    baseline = rng.integers(60, 210, size=(50, 90, 3), dtype=np.uint8)
    Image.fromarray(baseline).save(baseline_path)
    detector = DiffDetector(baseline_path=baseline_path, diff_threshold=10, change_ratio_threshold=0.04)

    shifted = np.roll(baseline, 8, axis=1)
    evidence = detector.analyze(shifted, [ZONE_A, ZONE_B, ZONE_C])

    assert {seat_id: item.diff_changed for seat_id, item in evidence.items()} == {
        "seat_a": False,
        "seat_b": False,
        "seat_c": False,
    }
    assert detector.warning is not None
    assert "camera may have moved" in detector.warning


def test_all_zones_can_be_occupied_when_background_is_stable(tmp_path):
    baseline_path = tmp_path / "baseline.jpg"
    yy, xx = np.indices((50, 90))
    baseline = np.zeros((50, 90, 3), dtype=np.uint8)
    baseline[:, :, 0] = (80 + (xx % 70)).astype(np.uint8)
    baseline[:, :, 1] = (90 + (yy % 60)).astype(np.uint8)
    baseline[:, :, 2] = (100 + ((xx + yy) % 50)).astype(np.uint8)
    Image.fromarray(baseline).save(baseline_path)
    detector = DiffDetector(baseline_path=baseline_path, diff_threshold=10, change_ratio_threshold=0.04)

    occupied = baseline.copy()
    for x1 in (10, 35, 60):
        occupied[11:24, x1 + 1 : x1 + 14] = [20, 20, 20]
    evidence = detector.analyze(occupied, [ZONE_A, ZONE_B, ZONE_C])

    assert all(item.diff_changed for item in evidence.values())
    assert detector.warning is None


def test_temporary_baseline_warning_remains_until_saved_baseline_is_set(tmp_path):
    detector = DiffDetector(baseline_path=tmp_path / "missing.jpg")
    frame = np.zeros((20, 20, 3), dtype=np.uint8)

    detector.analyze(frame, [ZONE])
    detector.analyze(frame, [ZONE])

    assert detector.warning is not None
    assert "temporary in-memory baseline" in detector.warning

    detector.set_baseline(frame, save=True)
    detector.analyze(frame, [ZONE])

    assert detector.warning is None
