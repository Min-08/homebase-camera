from __future__ import annotations

from datetime import UTC, datetime

from homebase_camera.scheduler import IntervalGate


def test_interval_gate_runs_first_then_waits_until_interval():
    gate = IntervalGate(interval_seconds=3)

    assert gate.should_run(10.0)
    gate.mark_run(10.0, datetime(2026, 7, 7, tzinfo=UTC))

    assert not gate.should_run(12.9)
    assert gate.should_run(13.0)
    assert gate.last_run_label == "2026-07-07T00:00:00+00:00"
    assert gate.seconds_until_next(11.0) == 2.0
