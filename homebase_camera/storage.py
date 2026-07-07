from __future__ import annotations

import sqlite3
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
    def __init__(self, db_path: str | Path = "data/status.db") -> None:
        self.db_path = resolve_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_many(self, decisions: Iterable[SeatDecision]) -> None:
        with self._connect() as conn:
            for decision in decisions:
                self._upsert(conn, decision)

    def upsert(self, decision: SeatDecision) -> None:
        with self._connect() as conn:
            self._upsert(conn, decision)

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
        with self._connect() as conn:
            conn.execute("DELETE FROM status_log")

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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
