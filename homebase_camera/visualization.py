from __future__ import annotations

from typing import Mapping

import numpy as np
from PIL import Image, ImageDraw

from .state_engine import STATUS_EMPTY, STATUS_OBJECT, STATUS_PERSON
from .zones import Zone


STATUS_COLORS = {
    STATUS_EMPTY: "#16a34a",
    STATUS_PERSON: "#2563eb",
    STATUS_OBJECT: "#d97706",
}

STATUS_SHORT_LABELS = {
    STATUS_EMPTY: "Empty",
    STATUS_PERSON: "Occupied",
    STATUS_OBJECT: "Temporarily Left",
}


def draw_zones(
    frame: np.ndarray,
    zones: list[Zone] | tuple[Zone, ...],
    statuses: Mapping[str, int] | None = None,
) -> Image.Image:
    image = Image.fromarray(_ensure_rgb(frame)).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    statuses = statuses or {}

    for zone in zones:
        status = int(statuses.get(zone.seat_id, STATUS_EMPTY))
        color = STATUS_COLORS.get(status, "#64748b")
        rgba = _hex_to_rgba(color, 58)
        outline = _hex_to_rgba(color, 230)
        points = [(int(x), int(y)) for x, y in zone.polygon]
        draw.polygon(points, fill=rgba, outline=outline)
        for x, y in points:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=outline)
        if points:
            label_x = min(x for x, _ in points)
            label_y = min(y for _, y in points)
            label = f"{zone.seat_name} ({status})"
            box = draw.textbbox((label_x, max(0, label_y - 22)), label)
            draw.rectangle((box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2), fill=(15, 23, 42, 190))
            draw.text((label_x, max(0, label_y - 22)), label, fill=(255, 255, 255, 255))

    return image


def _ensure_rgb(frame: np.ndarray) -> np.ndarray:
    array = np.asarray(frame)
    if array.ndim == 2:
        return np.stack([array, array, array], axis=-1).astype(np.uint8)
    if array.shape[-1] == 4:
        array = array[:, :, :3]
    return array[:, :, :3].astype(np.uint8)


def _hex_to_rgba(value: str, alpha: int) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)
