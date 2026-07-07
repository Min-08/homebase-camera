from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homebase_camera.capture import CaptureManager
from homebase_camera.config import load_settings, resolve_path
from homebase_camera.diff_detector import DiffDetector


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a baseline/reference image for pixel-difference detection.")
    parser.add_argument("--mock", action="store_true", help="Use mock mode instead of camera hardware.")
    parser.add_argument("--out", default=None, help="Output path. Defaults to detection.baseline_path.")
    args = parser.parse_args()

    if args.mock:
        os.environ["HOMEBASE_MOCK_MODE"] = "1"

    config = load_settings()
    capture = CaptureManager(config)
    frame_result = capture.read_frame()
    if not frame_result.ok and not config.mock_mode:
        print(frame_result.message)
        print("Try --mock on a development machine, or check the Raspberry Pi camera connection.")
        return 1

    output = args.out or config.detection.baseline_path
    detector = DiffDetector(
        baseline_path=output,
        diff_threshold=config.detection.diff_threshold,
        change_ratio_threshold=config.detection.change_ratio_threshold,
    )
    saved = detector.set_baseline(frame_result.frame, save=True)
    print(f"Baseline saved to {saved}")
    print("Next: run ./run_app.sh, or ./run_mock.sh without camera hardware.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
