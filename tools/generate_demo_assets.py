from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


WIDTH = 1280
HEIGHT = 720

ZONES = [
    {
        "seat_id": "seat_001",
        "seat_name": "Seat 1",
        "polygon": [[150, 250], [390, 250], [390, 490], [150, 490]],
        "enabled": True,
    },
    {
        "seat_id": "seat_002",
        "seat_name": "Seat 2",
        "polygon": [[520, 250], [760, 250], [760, 490], [520, 490]],
        "enabled": True,
    },
    {
        "seat_id": "seat_003",
        "seat_name": "Seat 3",
        "polygon": [[890, 250], [1130, 250], [1130, 490], [890, 490]],
        "enabled": True,
    },
]

TIMELINE = [
    {
        "frame": "000_empty.jpg",
        "label": "All seats empty",
        "states": {"seat_001": 0, "seat_002": 0, "seat_003": 0},
    },
    {
        "frame": "001_person_seat_1.jpg",
        "label": "Person sits in Seat 1",
        "states": {"seat_001": 1, "seat_002": 0, "seat_003": 0},
    },
    {
        "frame": "002_object_seat_1.jpg",
        "label": "Bag only in Seat 1; no person",
        "states": {"seat_001": 0, "seat_002": 0, "seat_003": 0},
        "object_seats": ["seat_001"],
    },
    {
        "frame": "003_mixed.jpg",
        "label": "Bag in Seat 1, person in Seat 2",
        "states": {"seat_001": 0, "seat_002": 1, "seat_003": 0},
        "object_seats": ["seat_001"],
    },
    {
        "frame": "004_empty_again.jpg",
        "label": "All seats empty again",
        "states": {"seat_001": 0, "seat_002": 0, "seat_003": 0},
    },
]


@dataclass(frozen=True)
class GenerationSummary:
    generated: tuple[Path, ...]
    skipped: tuple[Path, ...]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Homebase Camera PC demo assets.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing demo seats, timeline, and frame assets.",
    )
    args = parser.parse_args()
    summary = generate_demo_assets(ROOT, force=args.force)
    demo_dir = ROOT / "demo"
    print(
        f"Demo assets ready under {demo_dir} "
        f"({len(summary.generated)} generated, {len(summary.skipped)} existing skipped)."
    )
    if summary.skipped and not args.force:
        print("Existing demo assets were preserved. Use --force to reset them.")
    return 0


def generate_demo_assets(root: Path = ROOT, *, force: bool = False) -> GenerationSummary:
    demo_dir = Path(root) / "demo"
    frames_dir = demo_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    skipped: list[Path] = []

    for step in TIMELINE:
        target = frames_dir / step["frame"]
        if target.exists() and not force:
            skipped.append(target)
            continue
        image = _base_scene(step["label"])
        draw = ImageDraw.Draw(image)
        for zone in ZONES:
            state = int(step["states"][zone["seat_id"]])
            _draw_zone_state(
                draw,
                zone,
                state,
                object_present=zone["seat_id"] in step.get("object_seats", []),
            )
        image.save(target, quality=92)
        generated.append(target)

    _write_text_asset(
        demo_dir / "demo_seats.json",
        json.dumps({"zones": ZONES}, indent=2, ensure_ascii=False) + "\n",
        force=force,
        generated=generated,
        skipped=skipped,
    )
    _write_text_asset(
        demo_dir / "demo_timeline.json",
        json.dumps({"steps": [_timeline_step(step) for step in TIMELINE]}, indent=2, ensure_ascii=False) + "\n",
        force=force,
        generated=generated,
        skipped=skipped,
    )
    return GenerationSummary(generated=tuple(generated), skipped=tuple(skipped))


def _write_text_asset(
    path: Path,
    content: str,
    *,
    force: bool,
    generated: list[Path],
    skipped: list[Path],
) -> None:
    if path.exists() and not force:
        skipped.append(path)
        return
    path.write_text(content, encoding="utf-8", newline="\n")
    generated.append(path)


def _base_scene(label: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#eef2f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 110), fill="#dbeafe")
    draw.text((32, 28), "Homebase Camera PC Demo", fill="#0f172a")
    draw.text((32, 62), label, fill="#334155")
    draw.rectangle((90, 180, 1190, 555), fill="#f8fafc", outline="#94a3b8", width=3)
    draw.rounded_rectangle((120, 315, 1160, 425), radius=18, fill="#e2e8f0", outline="#64748b", width=2)
    draw.text((32, HEIGHT - 44), "Generated demo frame. Status evidence is synthetic ground truth, not real AI detection.", fill="#475569")
    return image


def _draw_zone_state(draw: ImageDraw.ImageDraw, zone: dict, state: int, *, object_present: bool = False) -> None:
    points = [tuple(point) for point in zone["polygon"]]
    x1 = min(x for x, _ in points)
    y1 = min(y for _, y in points)
    x2 = max(x for x, _ in points)
    y2 = max(y for _, y in points)
    colors = {0: "#16a34a", 1: "#dc2626"}
    fills = {0: "#dcfce7", 1: "#fee2e2"}
    labels = {0: "No person", 1: "Person present"}

    draw.polygon(points, fill=fills[state], outline=colors[state])
    draw.line(points + [points[0]], fill=colors[state], width=4)
    draw.text((x1 + 12, y1 + 10), zone["seat_name"], fill="#0f172a")
    draw.text((x1 + 12, y1 + 35), labels[state], fill=colors[state])

    if state == 1:
        cx = (x1 + x2) // 2
        draw.ellipse((cx - 32, y1 + 58, cx + 32, y1 + 122), fill="#60a5fa", outline="#1d4ed8", width=3)
        draw.rounded_rectangle((cx - 58, y1 + 122, cx + 58, y2 - 34), radius=28, fill="#2563eb")
    elif object_present:
        draw.rounded_rectangle((x1 + 82, y1 + 78, x2 - 82, y2 - 70), radius=18, fill="#f59e0b", outline="#92400e", width=3)
        draw.arc((x1 + 118, y1 + 48, x2 - 118, y1 + 118), 180, 360, fill="#92400e", width=5)
        draw.text((x1 + 12, y1 + 60), "Object only", fill="#92400e")
    else:
        draw.rounded_rectangle((x1 + 76, y1 + 95, x2 - 76, y2 - 60), radius=12, outline="#16a34a", width=3)


def _timeline_step(step: dict) -> dict:
    evidence = {}
    for seat_id, status in step["states"].items():
        object_present = seat_id in step.get("object_seats", [])
        evidence[seat_id] = {
            "status": status,
            "diff_changed": status != 0,
            "diff_ratio": 0.0 if status == 0 else 0.25,
            "person_detected": status == 1,
            "person_confidence": 0.92 if status == 1 else 0.0,
            "person_checked": True,
            "object_detected": object_present,
            "object_confidence": 0.86 if object_present else 0.0,
            "object_classes": ["backpack"] if object_present else [],
            "message": "synthetic demo evidence; not real AI detection",
        }
    return {
        "frame": step["frame"],
        "label": step["label"],
        "expected_status": step["states"],
        "evidence": evidence,
    }


if __name__ == "__main__":
    raise SystemExit(main())
