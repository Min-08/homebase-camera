from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable

from .config import resolve_path
from .state_engine import SeatDecision


SCHEMA = """
CREATE TABLE IF NOT EXISTS current_status(
  seat_id TEXT PRIMARY KEY,
  status INTEGER NOT NULL,
  confidence REAL NOT NULL,
  evidence TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS status_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seat_id TEXT NOT NULL,
  status INTEGER NOT NULL,
  confidence REAL NOT NULL,
  evidence TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


class StatusStore:
    def __init__(
        self,
        db_path: str | Path = "data/status.db",
        *,
        timeout_seconds: int = 10,
        busy_timeout_ms: int = 5000,
        wal_enabled: bool = True,
        retries: int = 3,
    ) -> None:
        self.db_path = resolve_path(db_path)
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.busy_timeout_ms = max(100, int(busy_timeout_ms))
        self.wal_enabled = bool(wal_enabled)
        self.retries = max(1, int(retries))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def init_db(self) -> None:
        self._write_with_retry(self._init_db)

    def _init_db(self, conn: sqlite3.Connection) -> None:
        self._configure_connection(conn, configure_journal=True)
        conn.executescript(SCHEMA)

    def upsert_many(self, decisions: Iterable[SeatDecision]) -> None:
        self._write_with_retry(lambda conn: [self._upsert(conn, decision) for decision in decisions])

    def upsert(self, decision: SeatDecision) -> None:
        self._write_with_retry(lambda conn: self._upsert(conn, decision))

    def get_current(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seat_id, status, confidence, evidence, updated_at FROM current_status ORDER BY seat_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_log(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, seat_id, status, confidence, evidence, created_at
                FROM status_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def reset_logs(self) -> None:
        self._write_with_retry(lambda conn: conn.execute("DELETE FROM status_log"))

    def pragmas(self) -> dict[str, object]:
        with self._connect() as conn:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        return {"journal_mode": journal_mode, "busy_timeout": busy_timeout}

    def _upsert(self, conn: sqlite3.Connection, decision: SeatDecision) -> None:
        previous = conn.execute(
            "SELECT status FROM current_status WHERE seat_id = ?",
            (decision.seat_id,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO current_status(seat_id, status, confidence, evidence, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(seat_id) DO UPDATE SET
                status = excluded.status,
                confidence = excluded.confidence,
                evidence = excluded.evidence,
                updated_at = excluded.updated_at
            """,
            (decision.seat_id, decision.status, decision.confidence, decision.evidence, decision.updated_at),
        )
        if previous is None or int(previous["status"]) != int(decision.status):
            conn.execute(
                """
                INSERT INTO status_log(seat_id, status, confidence, evidence, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (decision.seat_id, decision.status, decision.confidence, decision.evidence, decision.updated_at),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        self._configure_connection(conn)
        return conn

    def _configure_connection(self, conn: sqlite3.Connection, *, configure_journal: bool = False) -> None:
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        if self.wal_enabled and configure_journal:
            conn.execute("PRAGMA journal_mode = WAL")

    def _write_with_retry(self, callback) -> None:
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(self.retries):
            try:
                with self._connect() as conn:
                    callback(conn)
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                time.sleep(0.1 * (attempt + 1))
        if last_error is not None:
            raise last_error
