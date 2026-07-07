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


def test_storage_initializes_busy_timeout_and_wal(tmp_path):
    store = StatusStore(tmp_path / "status.db", busy_timeout_ms=4321, wal_enabled=True)

    pragmas = store.pragmas()

    assert pragmas["busy_timeout"] == 4321
    assert str(pragmas["journal_mode"]).lower() == "wal"


def test_storage_does_not_reapply_wal_on_regular_connections(tmp_path, monkeypatch):
    store = StatusStore(tmp_path / "status.db", wal_enabled=True)
    journal_configurations = 0
    original_configure = store._configure_connection

    def tracking_configure(conn, *, configure_journal=False):
        nonlocal journal_configurations
        if configure_journal:
            journal_configurations += 1
        return original_configure(conn, configure_journal=configure_journal)

    monkeypatch.setattr(store, "_configure_connection", tracking_configure)

    store.get_current()
    store.upsert(_decision(STATUS_PERSON))
    store.get_log()

    assert journal_configurations == 0
