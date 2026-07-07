from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homebase_camera.capture import CaptureManager
from homebase_camera.config import load_settings
from homebase_camera.zones import Zone, load_zones, save_zones


def main() -> int:
    parser = argparse.ArgumentParser(description="Click-to-create polygon zone editor using OpenCV.")
    parser.add_argument("--mock", action="store_true", help="Use mock frame instead of camera hardware.")
    parser.add_argument("--image", default="", help="Use a saved image path instead of live capture.")
    args = parser.parse_args()

    try:
        import cv2  # type: ignore
        import numpy as np
        from PIL import Image
    except Exception:
        print("OpenCV editor requires OpenCV. On Raspberry Pi OS run: sudo apt install python3-opencv")
        return 1

    if args.mock:
        os.environ["HOMEBASE_MOCK_MODE"] = "1"

    if args.image:
        bgr_frame = cv2.imread(args.image)
        if bgr_frame is None:
            print(f"Could not read image: {args.image}")
            return 1
        frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
    else:
        config = load_settings()
        frame_result = CaptureManager(config).read_frame()
        frame = frame_result.frame
        if not frame_result.ok:
            print(frame_result.message)
            print("Continuing with the placeholder frame. You can also pass --mock.")

    result = load_zones(include_disabled=True)
    zones = list(result.zones)
    points: list[tuple[int, int]] = []
    window_name = "Homebase Zone Editor"

    def redraw() -> None:
        canvas = frame.copy()
        for zone in zones:
            polygon = np.array(zone.polygon, dtype=np.int32)
            cv2.polylines(canvas, [polygon], isClosed=True, color=(37, 99, 235), thickness=3)
            cv2.putText(canvas, zone.seat_name, tuple(polygon[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (15, 23, 42), 2)
        if points:
            polygon = np.array(points, dtype=np.int32)
            cv2.polylines(canvas, [polygon], isClosed=False, color=(217, 119, 6), thickness=3)
            for point in points:
                cv2.circle(canvas, point, 5, (217, 119, 6), -1)
        cv2.imshow(window_name, cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR))

    def on_mouse(event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((int(x), int(y)))
            redraw()

    print("Click polygon points around one seat.")
    print("Keys: f=finish/save current zone, u=undo point, r=reset points, q=quit")
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, on_mouse)
    redraw()

    while True:
        key = cv2.waitKey(50) & 0xFF
        if key == ord("q"):
            break
        if key == ord("u") and points:
            points.pop()
            redraw()
        if key == ord("r"):
            points.clear()
            redraw()
        if key == ord("f"):
            if len(points) < 3:
                print("Need at least three points before saving a zone.")
                continue
            seat_id = input("seat_id (example seat_004): ").strip()
            seat_name = input("seat_name (example Seat 4): ").strip() or seat_id
            if not seat_id:
                print("seat_id is required.")
                continue
            zones = [zone for zone in zones if zone.seat_id != seat_id]
            zones.append(Zone(seat_id=seat_id, seat_name=seat_name, polygon=tuple(points)))
            target = save_zones(zones)
            print(f"Saved {seat_id} to {target}")
            points.clear()
            redraw()

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
