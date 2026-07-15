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
        self._baseline_invalid = False

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
            if self._baseline_invalid:
                self.warning = (
                    "The saved baseline image is not usable for detection. "
                    "Capture a real empty camera view from the live zone editor."
                )
                return {
                    zone.seat_id: ZoneEvidence(valid=False, message="invalid baseline; capture an empty baseline")
                    for zone in zones
                }
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
                zone.seat_id: ZoneEvidence(valid=False, message="temporary baseline initialized")
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

        zone_ratios: list[tuple[Zone, float | None]] = []
        combined_mask = np.zeros(current_gray.shape, dtype=bool)
        for zone in zones:
            mask = create_polygon_mask(current_gray.shape, zone.polygon)
            masked_pixels = int(mask.sum())
            if masked_pixels == 0:
                zone_ratios.append((zone, None))
                continue

            combined_mask |= mask
            ratio = float(changed[mask].sum() / masked_pixels)
            zone_ratios.append((zone, ratio))

        valid_ratios = [ratio for _, ratio in zone_ratios if ratio is not None]
        background_ratio = _background_change_ratio(changed, combined_mask)
        if _looks_like_scene_mismatch(valid_ratios, background_ratio, self.change_ratio_threshold):
            self.warning = (
                "All seat zones changed heavily compared with the baseline. "
                "The camera may have moved or the baseline was captured from a different scene. "
                "Capture a new empty baseline before trusting occupancy status."
            )
            return {
                zone.seat_id: ZoneEvidence(
                    valid=False,
                    diff_ratio=float(ratio or 0.0),
                    source="diff",
                    message="baseline mismatch; capture a new empty baseline",
                )
                for zone, ratio in zone_ratios
            }

        results: dict[str, ZoneEvidence] = {}
        for zone, ratio in zone_ratios:
            if ratio is None:
                results[zone.seat_id] = ZoneEvidence(valid=False, message="zone mask is empty")
                continue
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
        self._baseline_invalid = False
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
            baseline = np.asarray(Image.open(self.baseline_path).convert("RGB"))
            self._temporary_baseline = False
        except OSError as exc:
            self.warning = f"Could not read baseline image: {exc}"
            return None
        quality_warning = _baseline_quality_warning(baseline)
        if quality_warning:
            self._baseline_invalid = True
            self.warning = quality_warning
            return None
        self._baseline = baseline
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


def _background_change_ratio(changed: np.ndarray, combined_zone_mask: np.ndarray) -> float:
    background = ~combined_zone_mask
    count = int(background.sum())
    if count == 0:
        return 0.0
    return float(changed[background].sum() / count)


def _looks_like_scene_mismatch(ratios: list[float], background_ratio: float, change_ratio_threshold: float) -> bool:
    if len(ratios) < 2:
        return False
    moderate_zone_threshold = max(0.08, change_ratio_threshold * 2.0)
    background_threshold = max(0.03, change_ratio_threshold * 0.75)
    if background_ratio < background_threshold:
        return False
    if all(ratio >= 0.25 for ratio in ratios):
        return True
    changed_zones = sum(ratio >= moderate_zone_threshold for ratio in ratios)
    return changed_zones >= max(2, len(ratios) - 1)


def _baseline_quality_warning(frame: np.ndarray) -> str | None:
    gray = _to_gray(frame)
    mean = float(gray.mean())
    stddev = float(gray.std())
    if mean <= 5.0:
        return "Saved baseline image is nearly black; it looks like a blank file, not an empty camera view."
    if mean >= 250.0:
        return "Saved baseline image is nearly white; it looks like a blank file, not an empty camera view."
    if stddev <= 2.0:
        return "Saved baseline image has almost no visual detail; capture a real empty camera view."
    return None
