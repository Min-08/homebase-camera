from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
import urllib.error
import urllib.request

import numpy as np
import pytest

from homebase_camera.capture import CaptureManager, FrameResult
from homebase_camera.config import load_settings
from homebase_camera.state_engine import ZoneEvidence
from homebase_camera.streaming import LiveAnalysisWorker, LiveFrameProducer, LiveStreamServer, _parse_polygon


class _FakeCapture:
    def __init__(self) -> None:
        self.sequence = 0

    def background_running(self) -> bool:
        return True

    def start_background(self, fps: int) -> None:
        return

    def latest_frame(self) -> FrameResult:
        self.sequence += 1
        frame = np.full((24, 32, 3), self.sequence % 255, dtype=np.uint8)
        return FrameResult(frame, True, "fake")

    def latest_sequence(self) -> int:
        return self.sequence


class _FakeAnalyzer:
    def current_zones(self):
        return []

    def current_status_map(self):
        return {}


def test_live_frame_producer_shares_cached_jpeg_between_consumers():
    config = load_settings("config/settings.demo.toml")
    config = replace(config, streaming=replace(config.streaming, fps=30, jpeg_quality=60))
    producer = LiveFrameProducer(config, _FakeCapture(), _FakeAnalyzer())
    producer.start()
    first = producer.wait_for_frame(-1, timeout=2)
    producer.stop()

    assert first is not None
    first_sequence, first_jpeg = first
    second = producer.wait_for_frame(-1, timeout=0)

    assert second == (first_sequence, first_jpeg)
    assert first_jpeg.startswith(b"\xff\xd8")
    assert first_jpeg.endswith(b"\xff\xd9")


def test_parse_polygon_rejects_partial_or_non_numeric_points():
    with pytest.raises(ValueError, match=r"polygon\[1\]"):
        _parse_polygon([[1, 2], [3], [4, 5]])

    with pytest.raises(ValueError, match="finite numbers"):
        _parse_polygon([[1, 2], ["not-a-number", 4], [5, 6]])


def test_live_server_health_snapshot_and_json_validation(tmp_path):
    config = load_settings("config/settings.demo.toml")
    config = replace(
        config,
        camera=replace(config.camera, source="mock", frame_width=160, frame_height=90),
        detection=replace(config.detection, baseline_path=str(tmp_path / "baseline.jpg"), yolo_enabled=False),
        storage=replace(config.storage, db_path=str(tmp_path / "status.db")),
        streaming=replace(config.streaming, host="127.0.0.1", port=0, fps=20, jpeg_quality=60),
        mock_mode=True,
    )
    capture = CaptureManager(config)
    server = LiveStreamServer(config, capture)
    server.start()
    port = int(server.httpd.server_address[1])
    base = f"http://127.0.0.1:{port}"

    try:
        with urllib.request.urlopen(base + "/health", timeout=3) as response:
            health = json.load(response)
        with urllib.request.urlopen(base + "/snapshot.jpg", timeout=3) as response:
            snapshot = response.read()
        with urllib.request.urlopen(base + "/api/preflight", timeout=3) as response:
            preflight = json.load(response)

        invalid = urllib.request.Request(
            base + "/api/zones",
            data=b"not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(invalid, timeout=3)

        assert health["ok"] is True
        assert health["capture"]["running"] is True
        assert health["stream"]["running"] is True
        assert snapshot.startswith(b"\xff\xd8")
        assert snapshot.endswith(b"\xff\xd9")
        assert preflight["ready"] is False
        assert next(check for check in preflight["checks"] if check["id"] == "yolo")["ok"] is False
        assert next(check for check in preflight["checks"] if check["id"] == "person_scan")["ok"] is False
        assert error.value.code == 400
    finally:
        server.stop()
        capture.close()


def test_live_analysis_requests_periodic_person_check_even_without_diff_change(tmp_path):
    config = load_settings("config/settings.example.toml")
    config = replace(
        config,
        storage=replace(config.storage, db_path=str(tmp_path / "status.db")),
        detection=replace(config.detection, baseline_path=str(tmp_path / "baseline.jpg"), yolo_enabled=True),
    )
    capture = _FakeCapture()
    worker = LiveAnalysisWorker(config, capture)  # type: ignore[arg-type]
    worker.yolo.close()

    class FakeDiff:
        warning = None
        baseline_path = tmp_path / "baseline.jpg"

        def analyze(self, frame, zones):
            return {zone.seat_id: ZoneEvidence() for zone in zones}

    class FakeAsync:
        pending = False
        last_elapsed_seconds = 0.0
        last_error = ""

        def __init__(self):
            self.urgent_calls = []

        def poll(self):
            return None

        def submit(self, frame, zones, *, sequence, diff_state, urgent=False):
            self.urgent_calls.append(urgent)
            return True

        def invalidate(self):
            return None

    fake_async = FakeAsync()
    worker.detector = FakeDiff()  # type: ignore[assignment]
    worker.yolo_detector = SimpleNamespace(status=SimpleNamespace(available=True, message="ready"))
    worker.yolo = fake_async  # type: ignore[assignment]

    worker._run_once()
    worker._run_once()

    assert fake_async.urgent_calls == [True, False]
    assert worker.status()["valid"] is False
    assert "first person detector result" in str(worker.status()["invalid_reason"])
