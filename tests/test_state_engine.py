from __future__ import annotations

from homebase_camera.state_engine import STATUS_EMPTY, STATUS_OBJECT, STATUS_PERSON, SeatStateEngine, ZoneEvidence
from homebase_camera.zones import Zone


ZONE = Zone(
    seat_id="seat_001",
    seat_name="Seat 1",
    polygon=((0, 0), (10, 0), (10, 10), (0, 10)),
)


def test_person_evidence_triggers_status_1_immediately():
    engine = SeatStateEngine(person_required_hits=1)

    decision = engine.update(ZONE, ZoneEvidence(person_detected=True, person_confidence=0.82))

    assert decision.status == STATUS_PERSON
    assert decision.confidence == 0.82


def test_object_only_evidence_can_trigger_status_2_when_enabled():
    engine = SeatStateEngine(object_occupancy_enabled=True, object_conservativeness=0)

    decision = engine.update(ZONE, ZoneEvidence(object_detected=True, object_confidence=0.40, object_classes=["laptop"]))

    assert decision.status == STATUS_OBJECT


def test_object_only_evidence_does_not_trigger_status_2_when_disabled():
    engine = SeatStateEngine(object_occupancy_enabled=False, object_conservativeness=0)

    for _ in range(3):
        decision = engine.update(ZONE, ZoneEvidence(object_detected=True, object_confidence=0.95, object_classes=["laptop"]))

    assert decision.status == STATUS_EMPTY


def test_higher_conservativeness_requires_repeated_object_evidence():
    engine = SeatStateEngine(object_occupancy_enabled=True, object_conservativeness=10)

    for _ in range(5):
        decision = engine.update(ZONE, ZoneEvidence(object_detected=True, object_confidence=0.90, object_classes=["bag"]))
        assert decision.status == STATUS_EMPTY

    decision = engine.update(ZONE, ZoneEvidence(object_detected=True, object_confidence=0.90, object_classes=["bag"]))

    assert engine.required_object_hits == 6
    assert decision.status == STATUS_OBJECT


def test_empty_evidence_returns_to_status_0_after_required_hits():
    engine = SeatStateEngine(empty_required_hits=2)
    occupied = engine.update(ZONE, ZoneEvidence(person_detected=True, person_confidence=0.90))
    assert occupied.status == STATUS_PERSON

    first_empty = engine.update(ZONE, ZoneEvidence())
    second_empty = engine.update(ZONE, ZoneEvidence())

    assert first_empty.status == STATUS_PERSON
    assert second_empty.status == STATUS_EMPTY
