from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import DemoConfig, get_project_root, resolve_path
from .state_engine import STATUS_EMPTY, STATUS_OCCUPIED, ZoneEvidence
from .zones import Zone, load_zones


@dataclass(frozen=True)
class DemoStep:
    frame: str
    label: str
    evidence: dict[str, ZoneEvidence]
    expected_status: dict[str, int]


@dataclass(frozen=True)
class DemoTimeline:
    steps: tuple[DemoStep, ...]
    source_path: Path

    def step_at(self, index: int) -> DemoStep:
        if not self.steps:
            raise DemoError("Demo timeline has no steps.")
        return self.steps[index % len(self.steps)]


class DemoError(ValueError):
    """Raised when demo assets are missing or malformed."""


def is_demo_mode(config: Any) -> bool:
    return bool(getattr(config.demo, "enabled", False) or str(getattr(config.camera, "source", "")).lower() == "demo")


def load_demo_timeline(config: DemoConfig) -> DemoTimeline:
    path = resolve_path(config.timeline_path)
    if not path.exists():
        raise DemoError(f"Demo timeline was not found: {path}. Run python tools/generate_demo_assets.py")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DemoError(f"Demo timeline is invalid JSON: {exc}") from exc

    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise DemoError("Demo timeline must contain a non-empty 'steps' list.")

    steps: list[DemoStep] = []
    for index, item in enumerate(raw_steps):
        if not isinstance(item, dict):
            raise DemoError(f"steps[{index}] must be an object.")
        frame = str(item.get("frame", "")).strip()
        if not frame:
            raise DemoError(f"steps[{index}].frame is required.")
        label = str(item.get("label", f"Step {index + 1}"))
        evidence = _parse_evidence(item.get("evidence", {}), index)
        expected_status = {
            str(seat_id): _normalize_status(status)
            for seat_id, status in dict(item.get("expected_status", {})).items()
        }
        steps.append(DemoStep(frame=frame, label=label, evidence=evidence, expected_status=expected_status))

    return DemoTimeline(steps=tuple(steps), source_path=path)


def load_demo_zones(config: DemoConfig) -> tuple[Zone, ...]:
    return load_zones(config.seats_path, fallback_path=config.seats_path).zones


def load_demo_frame(step: DemoStep, config: DemoConfig) -> np.ndarray:
    assets_dir = resolve_path(config.assets_dir)
    path = resolve_path(step.frame, assets_dir)
    if not path.exists():
        raise DemoError(f"Demo frame is missing: {path}. Run python tools/generate_demo_assets.py")
    return np.asarray(Image.open(path).convert("RGB"))


def demo_evidence_for_step(step: DemoStep) -> dict[str, ZoneEvidence]:
    return {
        seat_id: ZoneEvidence(
            valid=evidence.valid,
            diff_changed=evidence.diff_changed,
            diff_ratio=evidence.diff_ratio,
            person_checked=evidence.person_checked,
            person_detected=evidence.person_detected,
            person_confidence=evidence.person_confidence,
            object_detected=evidence.object_detected,
            object_confidence=evidence.object_confidence,
            object_classes=list(evidence.object_classes),
            source="demo",
            message=f"demo evidence: {step.label}; {evidence.message}".strip("; "),
        )
        for seat_id, evidence in step.evidence.items()
    }


def _parse_evidence(raw: Any, step_index: int) -> dict[str, ZoneEvidence]:
    if not isinstance(raw, dict):
        raise DemoError(f"steps[{step_index}].evidence must be an object keyed by seat_id.")
    parsed: dict[str, ZoneEvidence] = {}
    for seat_id, item in raw.items():
        if not isinstance(item, dict):
            raise DemoError(f"steps[{step_index}].evidence.{seat_id} must be an object.")
        status = _normalize_status(item.get("status", STATUS_EMPTY))
        parsed[str(seat_id)] = ZoneEvidence(
            person_checked=True,
            diff_changed=bool(item.get("diff_changed", status != STATUS_EMPTY)),
            diff_ratio=float(item.get("diff_ratio", 0.0 if status == STATUS_EMPTY else 0.22)),
            person_detected=bool(item.get("person_detected", False)),
            person_confidence=float(item.get("person_confidence", 0.0)),
            object_detected=bool(item.get("object_detected", False)),
            object_confidence=float(item.get("object_confidence", 0.0)),
            object_classes=list(item.get("object_classes", [])),
            source="demo",
            message=str(item.get("message", "synthetic ground truth; not real AI detection")),
        )
    return parsed


def _normalize_status(value: Any) -> int:
    return STATUS_EMPTY if int(value) == STATUS_EMPTY else STATUS_OCCUPIED
