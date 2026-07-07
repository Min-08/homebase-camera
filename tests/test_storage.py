from __future__ import annotations

from homebase_camera.state_engine import STATUS_EMPTY, STATUS_PERSON, SeatDecision
from homebase_camera.storage import StatusStore


def _decision(status: int, timestamp: str = "2026-07-07T00:00:00+00:00") -> SeatDecision:
    return SeatDecision(
        seat_id="seat_001",
        seat_name="Seat 1",
        status=status,
        confidence=0.8,
        evidence="test evidence",
        updated_at=timestamp,
    )


def test_storage_upserts_current_status_and_logs_changes(tmp_path):
    store = StatusStore(tmp_path / "status.db")

    store.upsert(_decision(STATUS_PERSON))
    store.upsert(_decision(STATUS_PERSON, "2026-07-07T00:00:01+00:00"))
    store.upsert(_decision(STATUS_EMPTY, "2026-07-07T00:00:02+00:00"))

    current = store.get_current()
    log = store.get_log()

    assert len(current) == 1
    assert current[0]["status"] == STATUS_EMPTY
    assert [row["status"] for row in log] == [STATUS_EMPTY, STATUS_PERSON]


def test_reset_logs(tmp_path):
    store = StatusStore(tmp_path / "status.db")

    store.upsert(_decision(STATUS_PERSON))
    store.reset_logs()

    assert store.get_log() == []
