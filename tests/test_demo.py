from __future__ import annotations

from homebase_camera.config import load_settings
from homebase_camera.demo import demo_evidence_for_step, load_demo_timeline
from homebase_camera.state_engine import STATUS_EMPTY, STATUS_OCCUPIED, SeatStateEngine
from homebase_camera.zones import Zone


ZONES = [
    Zone("seat_001", "Seat 1", ((0, 0), (10, 0), (10, 10), (0, 10))),
    Zone("seat_002", "Seat 2", ((20, 0), (30, 0), (30, 10), (20, 10))),
    Zone("seat_003", "Seat 3", ((40, 0), (50, 0), (50, 10), (40, 10))),
]


def test_demo_config_loads_as_demo_mode():
    config = load_settings("config/settings.demo.toml")

    assert config.demo.enabled is True
    assert config.camera.source == "demo"
    assert config.detection.yolo_enabled is False


def test_demo_timeline_loads_steps():
    config = load_settings("config/settings.demo.toml")
    timeline = load_demo_timeline(config.demo)

    assert len(timeline.steps) >= 5
    assert {step.expected_status["seat_001"] for step in timeline.steps} >= {STATUS_EMPTY, STATUS_OCCUPIED}


def test_demo_evidence_produces_binary_status_without_yolo():
    config = load_settings("config/settings.demo.toml")
    timeline = load_demo_timeline(config.demo)
    engine = SeatStateEngine.from_config(config.detection)

    statuses_seen = set()
    for step in timeline.steps:
        decisions = engine.update_all(ZONES, demo_evidence_for_step(step))
        statuses_seen.update(decision.status for decision in decisions.values())

    assert statuses_seen == {STATUS_EMPTY, STATUS_OCCUPIED}
