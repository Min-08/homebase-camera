from __future__ import annotations

from homebase_camera.state_engine import STATUS_EMPTY, STATUS_OCCUPIED, SeatStateEngine, ZoneEvidence
from homebase_camera.zones import Zone


ZONE = Zone(
    seat_id="seat_001",
    seat_name="Seat 1",
    polygon=((0, 0), (10, 0), (10, 10), (0, 10)),
)


def test_person_evidence_triggers_status_1_immediately():
    engine = SeatStateEngine(person_required_hits=1)

    decision = engine.update(
        ZONE,
        ZoneEvidence(person_checked=True, person_detected=True, person_confidence=0.82),
    )

    assert decision.status == STATUS_OCCUPIED
    assert decision.confidence == 0.82


def test_object_only_evidence_never_triggers_person_occupancy_even_with_legacy_setting():
    engine = SeatStateEngine(object_occupancy_enabled=True, object_conservativeness=0)

    decision = engine.update(
        ZONE,
        ZoneEvidence(
            person_checked=True,
            object_detected=True,
            object_confidence=0.40,
            object_classes=["laptop"],
        ),
    )

    assert decision.status == STATUS_EMPTY


def test_diff_only_evidence_does_not_trigger_occupied_when_disabled():
    engine = SeatStateEngine(object_occupancy_enabled=False, object_conservativeness=0)

    for _ in range(3):
        decision = engine.update(ZONE, ZoneEvidence(diff_changed=True, diff_ratio=0.95))

    assert decision.status == STATUS_EMPTY


def test_person_required_hits_controls_positive_smoothing():
    engine = SeatStateEngine(person_required_hits=2)

    first = engine.update(
        ZONE,
        ZoneEvidence(person_checked=True, person_detected=True, person_confidence=0.90),
    )
    second = engine.update(
        ZONE,
        ZoneEvidence(person_checked=True, person_detected=True, person_confidence=0.90),
    )

    assert first.status == STATUS_EMPTY
    assert second.status == STATUS_OCCUPIED


def test_empty_evidence_returns_to_status_0_after_required_hits():
    engine = SeatStateEngine(empty_required_hits=2)
    occupied = engine.update(
        ZONE,
        ZoneEvidence(person_checked=True, person_detected=True, person_confidence=0.90),
    )
    assert occupied.status == STATUS_OCCUPIED

    first_empty = engine.update(
        ZONE,
        ZoneEvidence(person_checked=True, diff_changed=True, diff_ratio=0.2),
    )
    second_empty = engine.update(
        ZONE,
        ZoneEvidence(person_checked=True, diff_changed=True, diff_ratio=0.2),
    )

    assert first_empty.status == STATUS_OCCUPIED
    assert second_empty.status == STATUS_EMPTY


def test_diff_without_person_check_preserves_previous_occupied_state():
    engine = SeatStateEngine(empty_required_hits=1)
    occupied = engine.update(
        ZONE,
        ZoneEvidence(person_checked=True, person_detected=True, person_confidence=0.90),
    )
    unchanged = engine.update(ZONE, ZoneEvidence(diff_changed=False, diff_ratio=0.0))

    assert occupied.status == STATUS_OCCUPIED
    assert unchanged.status == STATUS_OCCUPIED


def test_invalid_analysis_preserves_previous_occupied_state():
    engine = SeatStateEngine(empty_required_hits=1)
    engine.update(
        ZONE,
        ZoneEvidence(person_checked=True, person_detected=True, person_confidence=0.90),
    )

    decision = engine.update(
        ZONE,
        ZoneEvidence(valid=False, diff_ratio=0.95, message="baseline mismatch"),
    )

    assert decision.status == STATUS_OCCUPIED
    assert "preserving previous status" in decision.evidence


def test_person_hit_and_empty_counters_are_saturated_in_evidence():
    engine = SeatStateEngine(person_required_hits=1, empty_required_hits=2)
    decision = None
    for _ in range(10):
        decision = engine.update(
            ZONE,
            ZoneEvidence(person_checked=True, diff_changed=True),
        )

    assert decision is not None
    assert "2/2" in decision.evidence
    assert "10/2" not in decision.evidence
