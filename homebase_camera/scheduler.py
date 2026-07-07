from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class IntervalGate:
    interval_seconds: int
    last_run_monotonic: float | None = None
    last_run_label: str = "never"

    def should_run(self, now_monotonic: float) -> bool:
        if self.last_run_monotonic is None:
            return True
        return (now_monotonic - self.last_run_monotonic) >= max(1, int(self.interval_seconds))

    def mark_run(self, now_monotonic: float, now_datetime: datetime | None = None) -> None:
        self.last_run_monotonic = now_monotonic
        timestamp = now_datetime or datetime.now(UTC)
        self.last_run_label = timestamp.isoformat(timespec="seconds")

    def seconds_until_next(self, now_monotonic: float) -> float:
        if self.last_run_monotonic is None:
            return 0.0
        elapsed = now_monotonic - self.last_run_monotonic
        return max(0.0, max(1, int(self.interval_seconds)) - elapsed)


@dataclass
class RuntimeSnapshot:
    diff_ran: bool
    yolo_ran: bool
    last_diff_run: str
    last_yolo_run: str
    next_diff_seconds: float
    next_yolo_seconds: float
