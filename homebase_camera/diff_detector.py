from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageFilter

from .config import DetectionConfig, get_project_root, resolve_path
from .state_engine import ZoneEvidence
from .zones import Zone, create_polygon_mask


class DiffDetector:
    def __init__(
        self,
        *,
        baseline_path: str | Path = "data/snapshots/baseline.jpg",
        diff_threshold: int = 30,
        change_ratio_threshold: float = 0.04,
    ) -> None:
        self.baseline_path = resolve_path(baseline_path)
        self.diff_threshold = int(diff_threshold)
        self.change_ratio_threshold = float(change_ratio_threshold)
        self._baseline: np.ndarray | None = None
        self._temporary_baseline = False
        self.warning: str | None = None

    @classmethod
    def from_config(cls, config: DetectionConfig) -> "DiffDetector":
        return cls(
            baseline_path=config.baseline_path,
            diff_threshold=config.diff_threshold,
            change_ratio_threshold=config.change_ratio_threshold,
        )

    def analyze(self, frame: np.ndarray, zones: Iterable[Zone]) -> dict[str, ZoneEvidence]:
        baseline = self._get_baseline(frame)
        if baseline is None:
            self._baseline = frame.copy()
            self._temporary_baseline = True
            baseline_problem = self.warning
            fallback_warning = (
                "No baseline image found. The current frame is being used as a temporary baseline. "
                "Run tools/capture_baseline.py for a stable setup."
            )
            if baseline_problem:
                fallback_warning = (
                    f"{baseline_problem} The current frame is being used as a temporary baseline. "
                    "Run tools/capture_baseline.py to replace the baseline."
                )
            self.warning = fallback_warning
            return {
                zone.seat_id: ZoneEvidence(message="temporary baseline initialized")
                for zone in zones
            }

        current_gray = _to_gray(frame)
        if baseline.shape[:2] != frame.shape[:2]:
            self.warning = (
                f"Baseline resolution {baseline.shape[1]}x{baseline.shape[0]} does not match "
                f"current frame {frame.shape[1]}x{frame.shape[0]}; resizing baseline for this analysis. "
                "Capture a new baseline after changing camera resolution or source."
            )
            if self._temporary_baseline:
                self.warning += " The detector is still using a temporary in-memory baseline."
        elif self._temporary_baseline:
            self.warning = (
                "No saved baseline image is available; the detector is using a temporary in-memory baseline. "
                "Capture an empty baseline from the live zone editor for stable detection after restart."
            )
        else:
            self.warning = None
        baseline_gray = _to_gray(_resize_to_match(baseline, frame))
        diff = np.abs(current_gray.astype(np.int16) - baseline_gray.astype(np.int16)).astype(np.uint8)
        changed = diff > self.diff_threshold

        results: dict[str, ZoneEvidence] = {}
        for zone in zones:
            mask = create_polygon_mask(current_gray.shape, zone.polygon)
            masked_pixels = int(mask.sum())
            if masked_pixels == 0:
                results[zone.seat_id] = ZoneEvidence(message="zone mask is empty")
                continue

            ratio = float(changed[mask].sum() / masked_pixels)
            results[zone.seat_id] = ZoneEvidence(
                diff_changed=ratio >= self.change_ratio_threshold,
                diff_ratio=ratio,
                source="diff",
                message=f"changed-pixel threshold={self.change_ratio_threshold:.3f}",
            )

        return results

    def set_baseline(self, frame: np.ndarray, *, save: bool = True) -> Path | None:
        self._baseline = frame.copy()
        self._temporary_baseline = False
        self.warning = None
        if not save:
            return None
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(_ensure_rgb(frame)).save(self.baseline_path)
        return self.baseline_path

    def _get_baseline(self, frame: np.ndarray) -> np.ndarray | None:
        if self._baseline is not None:
            return self._baseline
        if not self.baseline_path.exists():
            return None
        try:
            self._baseline = np.asarray(Image.open(self.baseline_path).convert("RGB"))
            self._temporary_baseline = False
        except OSError as exc:
            self.warning = f"Could not read baseline image: {exc}"
            return None
        return self._baseline


def _to_gray(frame: np.ndarray) -> np.ndarray:
    image = Image.fromarray(_ensure_rgb(frame)).convert("L").filter(ImageFilter.GaussianBlur(radius=1.2))
    return np.asarray(image)


def _ensure_rgb(frame: np.ndarray) -> np.ndarray:
    array = np.asarray(frame)
    if array.ndim == 2:
        return np.stack([array, array, array], axis=-1).astype(np.uint8)
    if array.shape[-1] == 4:
        return array[:, :, :3].astype(np.uint8)
    return array[:, :, :3].astype(np.uint8)


def _resize_to_match(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    if source.shape[:2] == target.shape[:2]:
        return source
    width, height = int(target.shape[1]), int(target.shape[0])
    return np.asarray(Image.fromarray(_ensure_rgb(source)).resize((width, height), Image.Resampling.BILINEAR))
