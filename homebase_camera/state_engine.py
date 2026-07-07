from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable

from .config import DetectionConfig
from .zones import Zone


STATUS_EMPTY = 0
STATUS_PERSON = 1
STATUS_OBJECT = 2


STATUS_LABELS = {
    STATUS_EMPTY: "Empty / available",
    STATUS_PERSON: "Occupied by person",
    STATUS_OBJECT: "Temporarily left / object occupancy",
}


@dataclass
class ZoneEvidence:
    diff_changed: bool = False
    diff_ratio: float = 0.0
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
            diff_changed=self.diff_changed or other.diff_changed,
            diff_ratio=max(float(self.diff_ratio), float(other.diff_ratio)),
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
    object_hits: int = 0
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
    ) -> None:
        if not 0 <= int(object_conservativeness) <= 10:
            raise ValueError("object_conservativeness must be from 0 to 10.")
        self.object_occupancy_enabled = bool(object_occupancy_enabled)
        self.object_conservativeness = int(object_conservativeness)
        self.empty_required_hits = max(1, int(empty_required_hits))
        self.person_required_hits = max(1, int(person_required_hits))
        self._history: dict[str, _SeatHistory] = {}

    @classmethod
    def from_config(cls, config: DetectionConfig) -> "SeatStateEngine":
        return cls(
            object_occupancy_enabled=config.object_occupancy_enabled,
            object_conservativeness=config.object_conservativeness,
            empty_required_hits=config.empty_required_hits,
            person_required_hits=config.person_required_hits,
        )

    @property
    def required_object_hits(self) -> int:
        return round(1 + self.object_conservativeness * 0.5)

    @property
    def object_conf_threshold(self) -> float:
        return 0.25 + self.object_conservativeness * 0.04

    def reset(self) -> None:
        self._history.clear()

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
        person_signal = evidence.person_detected and evidence.person_confidence >= 0.20
        object_signal, object_confidence, object_reason = self._object_signal(evidence)

        if person_signal:
            history.person_hits += 1
            history.object_hits = 0
            history.empty_hits = 0
            if history.person_hits >= self.person_required_hits:
                history.status = STATUS_PERSON
                history.last_confidence = max(0.70, evidence.person_confidence)
            reason = f"person evidence {history.person_hits}/{self.person_required_hits}"

        elif self.object_occupancy_enabled and object_signal:
            history.person_hits = 0
            history.empty_hits = 0
            history.object_hits += 1
            if history.object_hits >= self.required_object_hits:
                history.status = STATUS_OBJECT
                history.last_confidence = object_confidence
            reason = f"{object_reason}; object hits {history.object_hits}/{self.required_object_hits}"

        else:
            history.person_hits = 0
            history.object_hits = 0
            if not self.object_occupancy_enabled or not evidence.diff_changed:
                history.empty_hits += 1
            else:
                history.empty_hits = 0

            if history.empty_hits >= self.empty_required_hits:
                history.status = STATUS_EMPTY
                history.last_confidence = max(0.30, 1.0 - evidence.diff_ratio)

            if not self.object_occupancy_enabled and (evidence.object_detected or evidence.diff_changed):
                reason = "object occupancy disabled; object-only evidence is not published"
            elif evidence.diff_changed:
                reason = "changed zone, but object evidence is below threshold"
            else:
                reason = f"empty evidence {history.empty_hits}/{self.empty_required_hits}"

        return SeatDecision(
            seat_id=zone.seat_id,
            seat_name=zone.seat_name,
            status=history.status,
            confidence=round(float(history.last_confidence), 3),
            evidence=self._summarize_evidence(evidence, reason),
            updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    def _object_signal(self, evidence: ZoneEvidence) -> tuple[bool, float, str]:
        threshold = self.object_conf_threshold
        if evidence.object_detected and evidence.object_confidence >= threshold:
            classes = ", ".join(evidence.object_classes) if evidence.object_classes else "object"
            return True, evidence.object_confidence, f"YOLO object ({classes}) confidence {evidence.object_confidence:.2f}"

        # Diff-only mode cannot identify the object class, but persistent localized change is useful
        # for a prototype when YOLO is missing or too slow on Raspberry Pi.
        if evidence.diff_changed and not evidence.person_detected:
            diff_confidence = min(0.95, 0.25 + evidence.diff_ratio * 5.0)
            if diff_confidence >= threshold:
                return True, diff_confidence, f"diff-only object candidate ratio {evidence.diff_ratio:.3f}"

        return False, 0.0, "no strong object evidence"

    def _summarize_evidence(self, evidence: ZoneEvidence, reason: str) -> str:
        parts = [
            reason,
            f"diff_ratio={evidence.diff_ratio:.3f}",
            f"person={evidence.person_confidence:.2f}" if evidence.person_detected else "person=none",
            f"object={evidence.object_confidence:.2f}" if evidence.object_detected else "object=none",
        ]
        if evidence.object_classes:
            parts.append("classes=" + ",".join(evidence.object_classes))
        if evidence.message:
            parts.append(evidence.message)
        return "; ".join(parts)
