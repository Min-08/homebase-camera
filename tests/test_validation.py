from __future__ import annotations

from homebase_camera.validation import polygon_area, validate_zones
from homebase_camera.zones import Zone


def test_polygon_area():
    assert polygon_area([(0, 0), (10, 0), (10, 10), (0, 10)]) == 100


def test_validate_zones_warns_for_small_and_out_of_bounds():
    zones = [
        Zone("tiny", "Tiny", ((1, 1), (2, 1), (2, 2))),
        Zone("outside", "Outside", ((-5, 0), (20, 0), (20, 20), (-5, 20))),
    ]

    warnings = validate_zones(zones, (10, 10, 3))

    messages = " ".join(w.message for w in warnings)
    assert "very small" in messages
    assert "outside the image bounds" in messages
