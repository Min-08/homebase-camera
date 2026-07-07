from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

from .zones import Zone, create_polygon_mask


@dataclass(frozen=True)
class ZoneWarning:
    seat_id: str
    message: str
    severity: str = "warning"


def polygon_area(polygon: Sequence[Sequence[int]]) -> float:
    if len(polygon) < 3:
        return 0.0
    total = 0.0
    points = [(float(x), float(y)) for x, y in polygon]
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def validate_zones(zones: Sequence[Zone], frame_shape: Sequence[int] | None = None) -> list[ZoneWarning]:
    warnings: list[ZoneWarning] = []
    height = width = None
    if frame_shape and len(frame_shape) >= 2:
        height, width = int(frame_shape[0]), int(frame_shape[1])

    for zone in zones:
        if len(zone.polygon) < 3:
            warnings.append(ZoneWarning(zone.seat_id, "Polygon has fewer than 3 points.", "error"))
            continue
        area = polygon_area(zone.polygon)
        if area < 250:
            warnings.append(ZoneWarning(zone.seat_id, f"Polygon area is very small ({area:.0f}px)."))
        if width is not None and height is not None:
            outside = [
                (x, y)
                for x, y in zone.polygon
                if x < 0 or y < 0 or x >= width or y >= height
            ]
            if outside:
                warnings.append(ZoneWarning(zone.seat_id, "One or more points are outside the image bounds."))

    if width is not None and height is not None:
        for left, right in combinations(zones, 2):
            if len(left.polygon) < 3 or len(right.polygon) < 3:
                continue
            left_mask = create_polygon_mask((height, width), left.polygon)
            right_mask = create_polygon_mask((height, width), right.polygon)
            overlap = int((left_mask & right_mask).sum())
            smaller = max(1, min(int(left_mask.sum()), int(right_mask.sum())))
            ratio = overlap / smaller
            if ratio > 0.50:
                warnings.append(
                    ZoneWarning(
                        f"{left.seat_id}/{right.seat_id}",
                        f"Zones overlap heavily ({ratio:.0%} of the smaller zone).",
                    )
                )

    return warnings
