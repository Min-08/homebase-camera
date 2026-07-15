from __future__ import annotations

import sqlite3

from homebase_camera.state_engine import STATUS_EMPTY, STATUS_OCCUPIED, SeatDecision
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

    store.upsert(_decision(STATUS_OCCUPIED))
    store.upsert(_decision(STATUS_OCCUPIED, "2026-07-07T00:00:01+00:00"))
    store.upsert(_decision(STATUS_EMPTY, "2026-07-07T00:00:02+00:00"))

    current = store.get_current()
    log = store.get_log()

    assert len(current) == 1
    assert current[0]["status"] == STATUS_EMPTY
    assert [row["status"] for row in log] == [STATUS_EMPTY, STATUS_OCCUPIED]


def test_reset_logs(tmp_path):
    store = StatusStore(tmp_path / "status.db")

    store.upsert(_decision(STATUS_OCCUPIED))
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
    store.upsert(_decision(STATUS_OCCUPIED))
    store.get_log()

    assert journal_configurations == 0


def test_storage_retries_locked_database_errors(tmp_path, monkeypatch):
    store = StatusStore(tmp_path / "status.db", retries=3)
    original_connect = store._connect
    attempts = 0

    def flaky_connect():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("database is locked")
        return original_connect()

    monkeypatch.setattr(store, "_connect", flaky_connect)

    store.upsert(_decision(STATUS_OCCUPIED))

    assert attempts == 3
    assert store.get_current()[0]["status"] == STATUS_OCCUPIED


def test_storage_migrates_legacy_status_2_to_binary_status_1(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE current_status(
              seat_id TEXT PRIMARY KEY, status INTEGER NOT NULL, confidence REAL NOT NULL,
              evidence TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE status_log(
              id INTEGER PRIMARY KEY AUTOINCREMENT, seat_id TEXT NOT NULL, status INTEGER NOT NULL,
              confidence REAL NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL
            );
            INSERT INTO current_status VALUES('seat_001', 2, 0.8, 'legacy', '2026-07-07T00:00:00+00:00');
            INSERT INTO status_log(seat_id, status, confidence, evidence, created_at)
            VALUES('seat_001', 2, 0.8, 'legacy', '2026-07-07T00:00:00+00:00');
            """
        )

    store = StatusStore(path)

    assert store.get_current()[0]["status"] == STATUS_OCCUPIED
    assert store.get_log()[0]["status"] == STATUS_OCCUPIED
