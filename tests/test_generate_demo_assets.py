from __future__ import annotations

import json

from tools.generate_demo_assets import generate_demo_assets


def test_generate_demo_assets_preserves_existing_assets_by_default(tmp_path):
    generate_demo_assets(tmp_path)
    seats_path = tmp_path / "demo" / "demo_seats.json"
    timeline_path = tmp_path / "demo" / "demo_timeline.json"
    frame_path = tmp_path / "demo" / "frames" / "000_empty.jpg"

    custom_seats = {
        "zones": [
            {
                "seat_id": "custom_seat",
                "seat_name": "User Edited Seat",
                "polygon": [[1, 1], [20, 1], [20, 20]],
                "enabled": True,
            }
        ]
    }
    custom_timeline = {"steps": [{"frame": "custom.jpg", "label": "User edited"}]}
    seats_path.write_text(json.dumps(custom_seats) + "\n", encoding="utf-8")
    timeline_path.write_text(json.dumps(custom_timeline) + "\n", encoding="utf-8")
    frame_path.write_bytes(b"user-edited-frame")

    summary = generate_demo_assets(tmp_path)

    assert json.loads(seats_path.read_text(encoding="utf-8")) == custom_seats
    assert json.loads(timeline_path.read_text(encoding="utf-8")) == custom_timeline
    assert frame_path.read_bytes() == b"user-edited-frame"
    assert seats_path in summary.skipped
    assert timeline_path in summary.skipped
    assert frame_path in summary.skipped


def test_generate_demo_assets_force_overwrites_existing_assets(tmp_path):
    generate_demo_assets(tmp_path)
    seats_path = tmp_path / "demo" / "demo_seats.json"
    timeline_path = tmp_path / "demo" / "demo_timeline.json"
    frame_path = tmp_path / "demo" / "frames" / "000_empty.jpg"

    seats_path.write_text('{"zones": []}\n', encoding="utf-8")
    timeline_path.write_text('{"steps": []}\n', encoding="utf-8")
    frame_path.write_bytes(b"user-edited-frame")

    summary = generate_demo_assets(tmp_path, force=True)

    seats = json.loads(seats_path.read_text(encoding="utf-8"))
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert seats["zones"][0]["seat_id"] == "seat_001"
    assert timeline["steps"][0]["frame"] == "000_empty.jpg"
    assert frame_path.read_bytes() != b"user-edited-frame"
    assert seats_path in summary.generated
    assert timeline_path in summary.generated
    assert frame_path in summary.generated
    assert not summary.skipped
