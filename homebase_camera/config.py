from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only used on older Python
    import tomli as tomllib  # type: ignore


class ConfigError(ValueError):
    """Raised when settings are malformed."""


@dataclass(frozen=True)
class UIConfig:
    auto_refresh_enabled: bool = True
    refresh_interval_seconds: int = 3


@dataclass(frozen=True)
class CameraConfig:
    source: str = "picamera2"
    device_index: int = 0
    mock_image_path: str = "data/snapshots/mock.jpg"
    mock_video_path: str = ""
    frame_width: int = 1280
    frame_height: int = 720


@dataclass(frozen=True)
class DetectionConfig:
    diff_interval_seconds: int = 3
    yolo_enabled: bool = True
    yolo_interval_seconds: int = 20
    yolo_model: str = "yolov8n.pt"
    object_occupancy_enabled: bool = True
    object_conservativeness: int = 5
    empty_required_hits: int = 2
    person_required_hits: int = 1
    diff_threshold: int = 30
    change_ratio_threshold: float = 0.04
    baseline_path: str = "data/snapshots/baseline.jpg"


@dataclass(frozen=True)
class StorageConfig:
    db_path: str = "data/status.db"
    timeout_seconds: int = 10
    busy_timeout_ms: int = 5000
    wal_enabled: bool = True


@dataclass(frozen=True)
class PrivacyConfig:
    save_raw_video: bool = False
    save_snapshots: bool = True
    snapshot_interval_seconds: int = 30


@dataclass(frozen=True)
class DemoConfig:
    enabled: bool = False
    timeline_path: str = "demo/demo_timeline.json"
    seats_path: str = "demo/demo_seats.json"
    assets_dir: str = "demo/frames"
    autoplay: bool = True
    show_ground_truth: bool = True
    show_detector_evidence: bool = True


@dataclass(frozen=True)
class StreamingConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8502
    fps: int = 10
    jpeg_quality: int = 75


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    settings_path: Path
    ui: UIConfig
    camera: CameraConfig
    detection: DetectionConfig
    storage: StorageConfig
    privacy: PrivacyConfig
    demo: DemoConfig
    streaming: StreamingConfig
    mock_mode: bool = False
    warnings: tuple[str, ...] = ()


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_path(value: str | Path, root: Path | None = None) -> Path:
    root = root or get_project_root()
    path = Path(value)
    return path if path.is_absolute() else root / path


def load_settings(path: str | Path | None = None) -> AppConfig:
    root = get_project_root()
    env_path = os.getenv("HOMEBASE_SETTINGS_PATH")
    requested_path = resolve_path(path or env_path, root) if (path or env_path) else root / "config" / "settings.toml"
    fallback_path = root / "config" / "settings.example.toml"
    warnings: list[str] = []

    settings_path = requested_path
    if not settings_path.exists():
        settings_path = fallback_path
        warnings.append(
            f"{_display_path(requested_path, root)} was not found; using config/settings.example.toml."
        )

    data: dict[str, Any] = {}
    if settings_path.exists():
        with settings_path.open("rb") as handle:
            data = tomllib.load(handle)
    else:
        warnings.append("No settings file found; using built-in defaults.")

    ui = _build_dataclass(UIConfig(), data.get("app", {}), "app")
    camera = _build_dataclass(CameraConfig(), data.get("camera", {}), "camera")
    detection = _build_dataclass(DetectionConfig(), data.get("detection", {}), "detection")
    storage = _build_dataclass(StorageConfig(), data.get("storage", {}), "storage")
    privacy = _build_dataclass(PrivacyConfig(), data.get("privacy", {}), "privacy")
    demo = _build_dataclass(DemoConfig(), data.get("demo", {}), "demo")
    streaming = _build_dataclass(StreamingConfig(), data.get("streaming", {}), "streaming")

    ui = _validate_ui(ui)
    detection = _validate_detection(detection)
    storage = _validate_storage(storage)
    privacy = _validate_privacy(privacy)
    streaming = _validate_streaming(streaming)

    source_override = os.getenv("HOMEBASE_CAMERA_SOURCE")
    if source_override:
        camera = replace(camera, source=source_override)

    mock_mode = os.getenv("HOMEBASE_MOCK_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    if mock_mode:
        camera = replace(camera, source="mock")
    demo_mode = os.getenv("HOMEBASE_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    if demo_mode:
        demo = replace(demo, enabled=True)
        camera = replace(camera, source="demo")
        detection = replace(detection, yolo_enabled=False)

    return AppConfig(
        project_root=root,
        settings_path=settings_path,
        ui=ui,
        camera=camera,
        detection=detection,
        storage=storage,
        privacy=privacy,
        demo=demo,
        streaming=streaming,
        mock_mode=mock_mode or camera.source == "mock",
        warnings=tuple(warnings),
    )


def _build_dataclass(default_obj: Any, section: dict[str, Any], section_name: str) -> Any:
    if not isinstance(section, dict):
        raise ConfigError(f"[{section_name}] must be a TOML table.")

    allowed = set(default_obj.__dataclass_fields__.keys())
    values = {}
    for key, value in section.items():
        if key not in allowed:
            raise ConfigError(f"Unknown setting [{section_name}].{key}")
        values[key] = value
    return replace(default_obj, **values)


def _validate_detection(config: DetectionConfig) -> DetectionConfig:
    try:
        conservativeness = int(config.object_conservativeness)
    except (TypeError, ValueError) as exc:
        raise ConfigError("object_conservativeness must be an integer from 0 to 10.") from exc

    if not 0 <= conservativeness <= 10:
        raise ConfigError("object_conservativeness must be between 0 and 10.")

    if config.yolo_interval_seconds < 1:
        raise ConfigError("yolo_interval_seconds must be at least 1.")
    if config.diff_interval_seconds < 1:
        raise ConfigError("diff_interval_seconds must be at least 1.")
    if config.empty_required_hits < 1 or config.person_required_hits < 1:
        raise ConfigError("empty_required_hits and person_required_hits must be at least 1.")
    if not 0 < float(config.change_ratio_threshold) <= 1:
        raise ConfigError("change_ratio_threshold must be greater than 0 and less than or equal to 1.")

    return replace(config, object_conservativeness=conservativeness)


def _validate_ui(config: UIConfig) -> UIConfig:
    if int(config.refresh_interval_seconds) < 1:
        raise ConfigError("refresh_interval_seconds must be at least 1.")
    return replace(config, refresh_interval_seconds=int(config.refresh_interval_seconds))


def _validate_storage(config: StorageConfig) -> StorageConfig:
    if int(config.timeout_seconds) < 1:
        raise ConfigError("timeout_seconds must be at least 1.")
    if int(config.busy_timeout_ms) < 100:
        raise ConfigError("busy_timeout_ms must be at least 100.")
    return replace(
        config,
        timeout_seconds=int(config.timeout_seconds),
        busy_timeout_ms=int(config.busy_timeout_ms),
    )


def _validate_privacy(config: PrivacyConfig) -> PrivacyConfig:
    if int(config.snapshot_interval_seconds) < 1:
        raise ConfigError("snapshot_interval_seconds must be at least 1.")
    return replace(config, snapshot_interval_seconds=int(config.snapshot_interval_seconds))


def _validate_streaming(config: StreamingConfig) -> StreamingConfig:
    port = int(config.port)
    fps = int(config.fps)
    jpeg_quality = int(config.jpeg_quality)
    if not 1 <= port <= 65535:
        raise ConfigError("streaming.port must be between 1 and 65535.")
    if not 1 <= fps <= 30:
        raise ConfigError("streaming.fps must be between 1 and 30.")
    if not 40 <= jpeg_quality <= 95:
        raise ConfigError("streaming.jpeg_quality must be between 40 and 95.")
    return replace(config, port=port, fps=fps, jpeg_quality=jpeg_quality)


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
