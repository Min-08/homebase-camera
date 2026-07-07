from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw

from .config import get_project_root, resolve_path


class ZoneConfigError(ValueError):
    """Raised when the seat zone file cannot be used."""


Point = tuple[int, int]


@dataclass(frozen=True)
class Zone:
    seat_id: str
    seat_name: str
    polygon: tuple[Point, ...]
    enabled: bool = True

    def to_json(self) -> dict:
        return {
            "seat_id": self.seat_id,
            "seat_name": self.seat_name,
            "polygon": [[int(x), int(y)] for x, y in self.polygon],
            "enabled": bool(self.enabled),
        }


@dataclass(frozen=True)
class ZoneLoadResult:
    zones: tuple[Zone, ...]
    source_path: Path
    warnings: tuple[str, ...] = ()


def load_zones(
    path: str | Path | None = None,
    fallback_path: str | Path | None = None,
    *,
    include_disabled: bool = False,
) -> ZoneLoadResult:
    root = get_project_root()
    requested = resolve_path(path or "config/seats.json", root)
    fallback = resolve_path(fallback_path or "config/seats.example.json", root)
    warnings: list[str] = []

    source = requested
    if not requested.exists():
        source = fallback
        warnings.append("config/seats.json was not found; using config/seats.example.json.")

    if not source.exists():
        raise ZoneConfigError("No seats.json or seats.example.json file was found.")

    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ZoneConfigError(f"{source} is not valid JSON: {exc}") from exc

    zones = _parse_zones(raw, include_disabled=include_disabled)
    if not zones:
        warnings.append("No enabled zones were found. Use the zone editor to add seats.")

    return ZoneLoadResult(zones=tuple(zones), source_path=source, warnings=tuple(warnings))


def save_zones(zones: Sequence[Zone], path: str | Path | None = None) -> Path:
    target = resolve_path(path or "config/seats.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"zones": [zone.to_json() for zone in zones]}
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def append_zone(zone: Zone, path: str | Path | None = None) -> Path:
    result = load_zones(path, include_disabled=True)
    existing = [z for z in result.zones if z.seat_id != zone.seat_id]
    existing.append(zone)
    return save_zones(existing, path)


def create_polygon_mask(frame_shape: Sequence[int], polygon: Sequence[Sequence[int]]) -> np.ndarray:
    if len(frame_shape) < 2:
        raise ValueError("frame_shape must include height and width.")
    height, width = int(frame_shape[0]), int(frame_shape[1])
    if height <= 0 or width <= 0:
        raise ValueError("frame_shape height and width must be positive.")

    points = [(int(x), int(y)) for x, y in polygon]
    if len(points) < 3:
        return np.zeros((height, width), dtype=bool)

    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.polygon(points, fill=1)
    return np.asarray(image, dtype=bool)


def point_in_polygon(point: Sequence[float], polygon: Sequence[Sequence[float]]) -> bool:
    x, y = float(point[0]), float(point[1])
    inside = False
    points = list(polygon)
    if len(points) < 3:
        return False

    j = len(points) - 1
    for i, current in enumerate(points):
        xi, yi = float(current[0]), float(current[1])
        xj, yj = float(points[j][0]), float(points[j][1])

        if _point_on_segment(x, y, xi, yi, xj, yj):
            return True

        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i

    return inside


def _parse_zones(raw: dict, *, include_disabled: bool) -> list[Zone]:
    if not isinstance(raw, dict) or not isinstance(raw.get("zones"), list):
        raise ZoneConfigError("Zone file must contain a top-level 'zones' list.")

    zones: list[Zone] = []
    seen_ids: set[str] = set()
    errors: list[str] = []

    for index, item in enumerate(raw["zones"]):
        prefix = f"zones[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object.")
            continue

        seat_id = str(item.get("seat_id", "")).strip()
        seat_name = str(item.get("seat_name", "")).strip() or seat_id
        enabled = bool(item.get("enabled", True))
        polygon = item.get("polygon")

        if not seat_id:
            errors.append(f"{prefix}.seat_id is required.")
            continue
        if seat_id in seen_ids:
            errors.append(f"{prefix}.seat_id '{seat_id}' is duplicated.")
            continue
        if not isinstance(polygon, list) or len(polygon) < 3:
            errors.append(f"{prefix}.polygon must contain at least three points.")
            continue

        parsed_points: list[Point] = []
        for point_index, point in enumerate(polygon):
            if (
                not isinstance(point, list | tuple)
                or len(point) != 2
                or not _is_number(point[0])
                or not _is_number(point[1])
            ):
                errors.append(f"{prefix}.polygon[{point_index}] must be [x, y].")
                parsed_points = []
                break
            parsed_points.append((int(round(float(point[0]))), int(round(float(point[1])))))

        if not parsed_points:
            continue

        seen_ids.add(seat_id)
        if enabled or include_disabled:
            zones.append(Zone(seat_id=seat_id, seat_name=seat_name, polygon=tuple(parsed_points), enabled=enabled))

    if errors:
        raise ZoneConfigError("Invalid zone file: " + "; ".join(errors))

    return zones


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _point_on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> bool:
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > 1e-9:
        return False
    dot = (px - ax) * (px - bx) + (py - ay) * (py - by)
    return dot <= 1e-9
