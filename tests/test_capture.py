from __future__ import annotations

from dataclasses import replace
import time

import numpy as np

from homebase_camera.capture import CaptureManager, FrameResult
from homebase_camera.config import load_settings


def test_background_capture_recovers_after_unexpected_exception(monkeypatch):
    config = load_settings("config/settings.demo.toml")
    config = replace(config, camera=replace(config.camera, source="mock"), mock_mode=True)
    manager = CaptureManager(config)
    calls = 0

    def flaky_read() -> FrameResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic capture failure")
        return FrameResult(np.zeros((12, 16, 3), dtype=np.uint8), True, "recovered")

    monkeypatch.setattr(manager, "_read_frame_locked", flaky_read)
    manager.start_background(fps=30)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = manager.background_status()
        if status["frame_count"] >= 1:
            break
        time.sleep(0.02)

    status = manager.background_status()
    manager.close()

    assert status["running"] is True
    assert status["failure_count"] >= 1
    assert status["frame_count"] >= 1
    assert status["latest_sequence"] >= status["frame_count"]
    assert manager.latest_ok() is True
