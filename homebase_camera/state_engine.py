from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable

from .config import DetectionConfig
from .zones import Zone


STATUS_EMPTY = 0
STATUS_OCCUPIED = 1
STATUS_PERSON = STATUS_OCCUPIED


STATUS_LABELS = {
    STATUS_EMPTY: "Empty / available",
    STATUS_OCCUPIED: "Occupied",
}


@dataclass
class ZoneEvidence:
    valid: bool = True
    diff_changed: bool = False
    diff_ratio: float = 0.0
    person_checked: bool = False
    person_detected: bool = False
    person_confidence: float = 0.0
    object_detected: bool = False
    object_confidence: float = 0.0
    object_classes: list[str] = field(default_factory=list)
    source: str = "diff"
    message: str = ""

    def merge(self, other: "ZoneEvidence") -> "ZoneEvidence":
        classes = sorted(set(self.object_classes + other.object_classes))
        return ZoneEvidence(
            valid=self.valid and other.valid,
            diff_changed=self.diff_changed or other.diff_changed,
            diff_ratio=max(float(self.diff_ratio), float(other.diff_ratio)),
            person_checked=self.person_checked or other.person_checked,
            person_detected=self.person_detected or other.person_detected,
            person_confidence=max(float(self.person_confidence), float(other.person_confidence)),
            object_detected=self.object_detected or other.object_detected,
            object_confidence=max(float(self.object_confidence), float(other.object_confidence)),
            object_classes=classes,
            source="+".join(sorted(set(filter(None, [self.source, other.source])))),
            message="; ".join(filter(None, [self.message, other.message])),
        )


@dataclass
class SeatDecision:
    seat_id: str
    seat_name: str
    status: int
    confidence: float
    evidence: str
    updated_at: str


@dataclass
class _SeatHistory:
    status: int = STATUS_EMPTY
    person_hits: int = 0
    occupied_hits: int = 0
    empty_hits: int = 0
    last_confidence: float = 0.0


class SeatStateEngine:
    def __init__(
        self,
        *,
        object_occupancy_enabled: bool = True,
        object_conservativeness: int = 5,
        empty_required_hits: int = 2,
        person_required_hits: int = 1,
        person_confidence_threshold: float = 0.25,
    ) -> None:
        if not 0 <= int(object_conservativeness) <= 10:
            raise ValueError("object_conservativeness must be from 0 to 10.")
        # Legacy object settings remain accepted so older settings files still load,
        # but binary occupancy is intentionally person-only.
        self.object_occupancy_enabled = False
        self.object_conservativeness = int(object_conservativeness)
        self.empty_required_hits = max(1, int(empty_required_hits))
        self.person_required_hits = max(1, int(person_required_hits))
        self.person_confidence_threshold = min(1.0, max(0.01, float(person_confidence_threshold)))
        self._history: dict[str, _SeatHistory] = {}

    @classmethod
    def from_config(cls, config: DetectionConfig) -> "SeatStateEngine":
        return cls(
            object_occupancy_enabled=config.object_occupancy_enabled,
            object_conservativeness=config.object_conservativeness,
            empty_required_hits=config.empty_required_hits,
            person_required_hits=config.person_required_hits,
            person_confidence_threshold=config.person_confidence_threshold,
        )

    @property
    def required_object_hits(self) -> int:
        return 0

    @property
    def required_occupied_hits(self) -> int:
        return self.person_required_hits

    @property
    def object_conf_threshold(self) -> float:
        return self.person_confidence_threshold

    @property
    def occupied_conf_threshold(self) -> float:
        return self.person_confidence_threshold

    def reset(self) -> None:
        self._history.clear()

    def restore_statuses(self, rows: Iterable[dict]) -> None:
        for row in rows:
            seat_id = str(row.get("seat_id", "")).strip()
            if not seat_id:
                continue
            status = int(row.get("status", STATUS_EMPTY))
            if status != STATUS_EMPTY:
                status = STATUS_OCCUPIED
            confidence = float(row.get("confidence", 0.0) or 0.0)
            self._history[seat_id] = _SeatHistory(
                status=status,
                person_hits=self.person_required_hits if status == STATUS_OCCUPIED else 0,
                occupied_hits=0,
                empty_hits=self.empty_required_hits if status == STATUS_EMPTY else 0,
                last_confidence=confidence,
            )

    def update_all(
        self,
        zones: Iterable[Zone],
        evidence_by_seat: dict[str, ZoneEvidence],
    ) -> dict[str, SeatDecision]:
        return {
            zone.seat_id: self.update(zone, evidence_by_seat.get(zone.seat_id, ZoneEvidence()))
            for zone in zones
        }

    def update(self, zone: Zone, evidence: ZoneEvidence) -> SeatDecision:
        history = self._history.setdefault(zone.seat_id, _SeatHistory())
        if not evidence.valid:
            reason = "analysis invalid; preserving previous status"
            return self._decision(zone, history, evidence, reason)

        person_signal = (
            evidence.person_checked
            and evidence.person_detected
            and evidence.person_confidence >= self.person_confidence_threshold
        )

        if person_signal:
            history.person_hits = min(self.person_required_hits, history.person_hits + 1)
            history.occupied_hits = 0
            history.empty_hits = 0
            if history.person_hits >= self.person_required_hits:
                history.status = STATUS_OCCUPIED
                history.last_confidence = max(0.70, evidence.person_confidence)
            reason = f"person evidence {history.person_hits}/{self.person_required_hits}"

        elif evidence.person_checked:
            history.person_hits = 0
            history.occupied_hits = 0
            history.empty_hits = min(self.empty_required_hits, history.empty_hits + 1)

            required_empty_hits = 1 if not evidence.diff_changed else self.empty_required_hits

            if history.empty_hits >= required_empty_hits:
                history.status = STATUS_EMPTY
                history.last_confidence = max(0.70, 1.0 - evidence.person_confidence)

            reason = f"person not detected {history.empty_hits}/{required_empty_hits}"

        else:
            history.person_hits = 0
            history.occupied_hits = 0
            history.empty_hits = 0
            reason = "awaiting person detector; preserving previous status"

        return self._decision(zone, history, evidence, reason)

    def _decision(
        self,
        zone: Zone,
        history: _SeatHistory,
        evidence: ZoneEvidence,
        reason: str,
    ) -> SeatDecision:
        return SeatDecision(
            seat_id=zone.seat_id,
            seat_name=zone.seat_name,
            status=history.status,
            confidence=round(float(history.last_confidence), 3),
            evidence=self._summarize_evidence(evidence, reason),
            updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    def _summarize_evidence(self, evidence: ZoneEvidence, reason: str) -> str:
        parts = [
            reason,
            f"diff_ratio={evidence.diff_ratio:.3f}",
            f"person={evidence.person_confidence:.2f}" if evidence.person_detected else (
                "person=not-detected" if evidence.person_checked else "person=not-checked"
            ),
            f"object={evidence.object_confidence:.2f}" if evidence.object_detected else "object=none",
        ]
        if evidence.object_classes:
            parts.append("classes=" + ",".join(evidence.object_classes))
        if evidence.message:
            parts.append(evidence.message)
        return "; ".join(parts)
