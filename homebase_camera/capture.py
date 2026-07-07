from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import AppConfig, CameraConfig, resolve_path


@dataclass
class FrameResult:
    frame: np.ndarray
    ok: bool
    message: str


class CaptureManager:
    def __init__(self, config: AppConfig) -> None:
        self.app_config = config
        self.camera_config = config.camera
        self._picamera: Any | None = None
        self._cv_capture: Any | None = None
        self.last_message = ""

    def read_frame(self) -> FrameResult:
        source = self.camera_config.source.lower()
        if self.app_config.mock_mode or source == "mock":
            return self._read_mock_frame()
        if source == "picamera2":
            result = self._read_picamera2()
            if result.ok:
                return result
            return self._placeholder(result.message)
        if source in {"opencv", "usb", "video"}:
            result = self._read_opencv()
            if result.ok:
                return result
            return self._placeholder(result.message)
        return self._placeholder(f"Unknown camera source '{self.camera_config.source}'. Use picamera2, opencv, video, or mock.")

    def save_latest_snapshot(self, frame: np.ndarray) -> Path | None:
        if not self.app_config.privacy.save_snapshots:
            return None
        path = resolve_path("data/snapshots/latest.jpg", self.app_config.project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(_ensure_rgb(frame)).save(path)
        return path

    def close(self) -> None:
        if self._picamera is not None:
            try:
                self._picamera.stop()
            except Exception:
                pass
            self._picamera = None
        if self._cv_capture is not None:
            try:
                self._cv_capture.release()
            except Exception:
                pass
            self._cv_capture = None

    def _read_mock_frame(self) -> FrameResult:
        image_path = resolve_path(self.camera_config.mock_image_path, self.app_config.project_root)
        if image_path.exists():
            try:
                frame = np.asarray(Image.open(image_path).convert("RGB"))
                return FrameResult(frame=frame, ok=True, message=f"Mock image: {image_path}")
            except OSError as exc:
                return self._placeholder(f"Could not read mock image '{image_path}': {exc}", ok=False)

        return FrameResult(
            frame=_synthetic_frame(self.camera_config.frame_width, self.camera_config.frame_height),
            ok=True,
            message="Mock mode is using a generated setup image. Add data/snapshots/mock.jpg to use your own.",
        )

    def _read_picamera2(self) -> FrameResult:
        try:
            from picamera2 import Picamera2  # type: ignore
        except Exception as exc:
            return FrameResult(
                frame=np.empty((1, 1, 3), dtype=np.uint8),
                ok=False,
                message=(
                    "Picamera2 is not available. On Raspberry Pi OS install it with "
                    "sudo apt install python3-picamera2, or run ./run_mock.sh without camera hardware."
                ),
            )

        try:
            if self._picamera is None:
                self._picamera = Picamera2()
                capture_config = self._picamera.create_preview_configuration(
                    main={
                        "size": (self.camera_config.frame_width, self.camera_config.frame_height),
                        "format": "RGB888",
                    }
                )
                self._picamera.configure(capture_config)
                self._picamera.start()
            frame = self._picamera.capture_array()
            return FrameResult(frame=_ensure_rgb(frame), ok=True, message="Picamera2 frame captured.")
        except Exception as exc:
            return FrameResult(
                frame=np.empty((1, 1, 3), dtype=np.uint8),
                ok=False,
                message=f"Camera capture failed: {exc}. Check ribbon cable, camera enablement, and permissions.",
            )

    def _read_opencv(self) -> FrameResult:
        try:
            import cv2  # type: ignore
        except Exception:
            return FrameResult(
                frame=np.empty((1, 1, 3), dtype=np.uint8),
                ok=False,
                message="OpenCV is not installed. Install python3-opencv or use ./run_mock.sh.",
            )

        try:
            if self._cv_capture is None:
                source = self.camera_config.mock_video_path or self.camera_config.device_index
                self._cv_capture = cv2.VideoCapture(source)
                self._cv_capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_config.frame_width)
                self._cv_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_config.frame_height)
            ok, frame = self._cv_capture.read()
            if not ok or frame is None:
                return FrameResult(frame=np.empty((1, 1, 3), dtype=np.uint8), ok=False, message="OpenCV could not read a frame.")
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return FrameResult(frame=frame, ok=True, message="OpenCV frame captured.")
        except Exception as exc:
            return FrameResult(frame=np.empty((1, 1, 3), dtype=np.uint8), ok=False, message=f"OpenCV capture failed: {exc}")

    def _placeholder(self, message: str, *, ok: bool = False) -> FrameResult:
        return FrameResult(
            frame=_placeholder_frame(self.camera_config.frame_width, self.camera_config.frame_height, message),
            ok=ok,
            message=message,
        )


def _ensure_rgb(frame: np.ndarray) -> np.ndarray:
    array = np.asarray(frame)
    if array.ndim == 2:
        return np.stack([array, array, array], axis=-1).astype(np.uint8)
    if array.shape[-1] == 4:
        array = array[:, :, :3]
    return array.astype(np.uint8)


def _synthetic_frame(width: int, height: int) -> np.ndarray:
    image = Image.new("RGB", (width, height), "#eef2f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, int(height * 0.22)), fill="#dbeafe")
    draw.text((32, 28), "Homebase Camera Mock Frame", fill="#0f172a")
    draw.text((32, 58), "Use the zone editor or tools/zone_editor_cv.py to configure seats.", fill="#334155")

    seat_w = max(120, width // 6)
    seat_h = max(90, height // 5)
    top = int(height * 0.38)
    gap = max(24, width // 28)
    start = max(40, (width - (3 * seat_w + 2 * gap)) // 2)
    fills = ["#dcfce7", "#dbeafe", "#fef3c7"]
    labels = ["empty sample", "person sample", "object sample"]
    for index in range(3):
        left = start + index * (seat_w + gap)
        draw.rounded_rectangle((left, top, left + seat_w, top + seat_h), radius=14, fill=fills[index], outline="#64748b", width=3)
        draw.text((left + 16, top + 16), f"Seat {index + 1}", fill="#0f172a")
        draw.text((left + 16, top + 44), labels[index], fill="#334155")
    draw.text((32, height - 44), datetime.now().isoformat(timespec="seconds"), fill="#64748b")
    return np.asarray(image)


def _placeholder_frame(width: int, height: int, message: str) -> np.ndarray:
    image = Image.new("RGB", (width, height), "#fff7ed")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 90), fill="#fed7aa")
    draw.text((32, 30), "Camera is not available", fill="#7c2d12")
    wrapped = _wrap_text(message, max_chars=90)
    y = 130
    for line in wrapped:
        draw.text((32, y), line, fill="#7c2d12")
        y += 28
    draw.text((32, y + 16), "Tip: run ./run_mock.sh to test without Raspberry Pi camera hardware.", fill="#334155")
    return np.asarray(image)


def _wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if sum(len(w) for w in current) + len(current) + len(word) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [text]
