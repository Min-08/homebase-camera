from __future__ import annotations

from dataclasses import replace
import json
import urllib.error
import urllib.request

import numpy as np
import pytest

from homebase_camera.capture import CaptureManager, FrameResult
from homebase_camera.config import load_settings
from homebase_camera.streaming import LiveFrameProducer, LiveStreamServer, _parse_polygon


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
        assert error.value.code == 400
    finally:
        server.stop()
        capture.close()
