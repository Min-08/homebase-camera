from __future__ import annotations

import json

import numpy as np
import pytest

from homebase_camera.zones import ZoneConfigError, create_polygon_mask, load_zones, point_in_polygon


def test_load_zones_ignores_disabled(tmp_path):
    path = tmp_path / "seats.json"
    path.write_text(
        json.dumps(
            {
                "zones": [
                    {
                        "seat_id": "seat_001",
                        "seat_name": "Seat 1",
                        "polygon": [[1, 1], [8, 1], [8, 8], [1, 8]],
                        "enabled": True,
                    },
                    {
                        "seat_id": "seat_002",
                        "seat_name": "Seat 2",
                        "polygon": [[10, 10], [12, 10], [12, 12]],
                        "enabled": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = load_zones(path)

    assert [zone.seat_id for zone in result.zones] == ["seat_001"]
    assert result.zones[0].polygon == ((1, 1), (8, 1), (8, 8), (1, 8))


def test_load_zones_rejects_malformed_polygon(tmp_path):
    path = tmp_path / "bad_seats.json"
    path.write_text(
        json.dumps({"zones": [{"seat_id": "seat_001", "seat_name": "Seat 1", "polygon": [[1, 2]]}]}),
        encoding="utf-8",
    )

    with pytest.raises(ZoneConfigError):
        load_zones(path)


def test_polygon_mask_and_point_in_polygon():
    polygon = [(2, 2), (8, 2), (8, 8), (2, 8)]

    mask = create_polygon_mask((12, 12, 3), polygon)

    assert mask.shape == (12, 12)
    assert mask.dtype == np.bool_
    assert mask[5, 5]
    assert not mask[0, 0]
    assert point_in_polygon((5, 5), polygon)
    assert point_in_polygon((2, 5), polygon)
    assert not point_in_polygon((10, 10), polygon)
