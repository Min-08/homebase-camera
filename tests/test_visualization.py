from __future__ import annotations

import numpy as np
from PIL import Image

from homebase_camera.visualization import draw_zones
from homebase_camera.zones import Zone


def test_draw_zones_returns_rgb_image_without_changing_frame_shape():
    frame = np.full((60, 80, 3), 255, dtype=np.uint8)
    zone = Zone("seat_001", "Seat 1", ((10, 10), (70, 10), (70, 50), (10, 50)))

    result = draw_zones(frame, [zone], {"seat_001": 2})

    assert isinstance(result, Image.Image)
    assert result.mode == "RGB"
    assert result.size == (80, 60)
    assert result.getpixel((20, 20)) != (255, 255, 255)
