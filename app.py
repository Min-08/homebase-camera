from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import streamlit as st
from PIL import Image

from homebase_camera.capture import CaptureManager
from homebase_camera.config import ConfigError, load_settings, resolve_path
from homebase_camera.diff_detector import DiffDetector
from homebase_camera.state_engine import STATUS_LABELS, SeatStateEngine, ZoneEvidence
from homebase_camera.storage import StatusStore
from homebase_camera.visualization import STATUS_COLORS, STATUS_SHORT_LABELS, draw_zones
from homebase_camera.yolo_detector import YoloDetector
from homebase_camera.zones import Zone, ZoneConfigError, load_zones, save_zones


st.set_page_config(page_title="Homebase Camera", page_icon=":camera:", layout="wide")


def main() -> None:
    try:
        config = load_settings()
    except ConfigError as exc:
        st.error(f"Settings problem: {exc}")
        st.stop()

    _ensure_runtime_dirs(config)

    st.title("Homebase Camera")
    st.caption("Local Raspberry Pi seat occupancy detector: 0 empty, 1 person, 2 temporarily left/object.")

    for warning in config.warnings:
        st.info(warning)

    try:
        zone_result = load_zones()
        zones = list(zone_result.zones)
    except ZoneConfigError as exc:
        zones = []
        st.error(f"Zone configuration problem: {exc}")
        zone_result = None

    if zone_result:
        for warning in zone_result.warnings:
            st.warning(warning)

    runtime_detection = _sidebar_controls(config.detection)
    frame_result = _capture(config)
    frame = frame_result.frame

    if frame_result.ok:
        _capture_manager(config).save_latest_snapshot(frame)
    else:
        st.warning(frame_result.message)

    tab_monitor, tab_editor, tab_logs, tab_settings = st.tabs(["Monitor", "Zone Editor", "Logs", "Settings"])

    with tab_monitor:
        _monitor_tab(config, runtime_detection, frame, frame_result.message, zones)

    with tab_editor:
        _zone_editor_tab(frame, zones)

    with tab_logs:
        _logs_tab(config)

    with tab_settings:
        _settings_tab(config, runtime_detection)


def _sidebar_controls(detection_config):
    st.sidebar.header("Runtime Controls")
    yolo_enabled = st.sidebar.toggle("YOLO correction", value=bool(detection_config.yolo_enabled))
    object_enabled = st.sidebar.toggle(
        "Object occupancy",
        value=bool(detection_config.object_occupancy_enabled),
        help="When disabled, status 2 is never published.",
    )
    conservativeness = st.sidebar.slider(
        "Object conservativeness",
        min_value=0,
        max_value=10,
        value=int(detection_config.object_conservativeness),
        help="0 triggers status 2 easily; 10 requires stronger repeated evidence.",
    )
    st.sidebar.metric("YOLO interval", f"{detection_config.yolo_interval_seconds}s")
    st.sidebar.metric("Diff interval target", f"{detection_config.diff_interval_seconds}s")
    st.sidebar.button("Refresh frame")

    return replace(
        detection_config,
        yolo_enabled=yolo_enabled,
        object_occupancy_enabled=object_enabled,
        object_conservativeness=conservativeness,
    )


def _monitor_tab(config, runtime_detection, frame: np.ndarray, frame_message: str, zones: list[Zone]) -> None:
    if not zones:
        st.info("No enabled zones are configured yet. Open Zone Editor or run tools/zone_editor_cv.py.")
        st.image(Image.fromarray(frame), caption=frame_message, width="stretch")
        return

    diff_detector = _diff_detector(runtime_detection)
    yolo_detector = _yolo_detector(runtime_detection)
    state_engine = _state_engine(runtime_detection)
    store = _store(config)

    evidence_by_seat = diff_detector.analyze(frame, zones)
    yolo_message = yolo_detector.status.message
    if runtime_detection.yolo_enabled:
        yolo_evidence = yolo_detector.detect(frame, zones)
        evidence_by_seat = _merge_evidence(evidence_by_seat, yolo_evidence)

    decisions = state_engine.update_all(zones, evidence_by_seat)
    store.upsert_many(decisions.values())

    status_map = {seat_id: decision.status for seat_id, decision in decisions.items()}
    overlay = draw_zones(frame, zones, status_map)

    left, right = st.columns([1.75, 1], gap="large")
    with left:
        st.subheader("Camera Frame")
        st.image(overlay, caption=frame_message, width="stretch")
        if diff_detector.warning:
            st.warning(diff_detector.warning)
        if runtime_detection.yolo_enabled:
            if yolo_detector.status.available:
                st.success(yolo_message)
            else:
                st.warning(yolo_message)
        else:
            st.info("YOLO correction is disabled. The app is using pixel-difference evidence only.")

    with right:
        st.subheader("Seat Status")
        for decision in decisions.values():
            _status_card(decision)


def _status_card(decision) -> None:
    color = STATUS_COLORS.get(decision.status, "#64748b")
    label = STATUS_SHORT_LABELS.get(decision.status, "Unknown")
    st.markdown(
        f"""
        <div style="border-left: 8px solid {color}; padding: 0.8rem 0.9rem; margin-bottom: 0.7rem;
                    background: #ffffff; border-radius: 8px; border-top: 1px solid #e2e8f0;
                    border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:0.5rem;">
            <strong style="font-size:1.02rem; color:#0f172a;">{decision.seat_name}</strong>
            <span style="font-weight:700; color:{color};">status {decision.status}</span>
          </div>
          <div style="font-size:0.95rem; color:#334155; margin-top:0.25rem;">{label}</div>
          <div style="font-size:0.85rem; color:#64748b; margin-top:0.4rem;">confidence {decision.confidence:.2f}</div>
          <div style="font-size:0.78rem; color:#475569; margin-top:0.45rem;">{decision.evidence}</div>
          <div style="font-size:0.75rem; color:#94a3b8; margin-top:0.45rem;">{decision.updated_at}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _zone_editor_tab(frame: np.ndarray, zones: list[Zone]) -> None:
    st.subheader("Zone Editor")
    st.write("Draw a polygon around one seat, enter a seat id/name, then save it to config/seats.json.")

    display_image, scale_x, scale_y = _display_image_for_canvas(frame)

    canvas_result = None
    try:
        _patch_drawable_canvas_image_helper()
        from streamlit_drawable_canvas import st_canvas  # type: ignore

        canvas_result = st_canvas(
            fill_color="rgba(37, 99, 235, 0.18)",
            stroke_width=3,
            stroke_color="#2563eb",
            background_image=display_image,
            height=display_image.height,
            width=display_image.width,
            drawing_mode="polygon",
            key="zone_canvas",
        )
    except Exception as exc:
        st.warning(
            "Interactive Streamlit drawing is unavailable. Use the fallback command: "
            "python tools/zone_editor_cv.py"
        )
        st.caption(f"Canvas detail: {exc}")
        st.image(draw_zones(frame, zones), width="stretch")

    with st.form("save_zone_form", clear_on_submit=False):
        col_a, col_b = st.columns(2)
        seat_id = col_a.text_input("seat_id", value=_next_seat_id(zones), help="Example: seat_004")
        seat_name = col_b.text_input("seat_name", value=f"Seat {len(zones) + 1}")
        submitted = st.form_submit_button("Save Drawn Zone")

    if submitted:
        polygon = _polygon_from_canvas(canvas_result, scale_x, scale_y) if canvas_result else []
        if len(polygon) < 3:
            st.error("Draw a polygon with at least three points before saving.")
        elif not seat_id.strip():
            st.error("seat_id is required.")
        else:
            updated = [zone for zone in zones if zone.seat_id != seat_id.strip()]
            updated.append(Zone(seat_id=seat_id.strip(), seat_name=seat_name.strip() or seat_id.strip(), polygon=tuple(polygon)))
            target = save_zones(updated)
            st.success(f"Saved {seat_id.strip()} to {target}")
            st.rerun()

    if zones:
        st.divider()
        st.subheader("Existing Zones")
        st.image(draw_zones(frame, zones), width="stretch")
        delete_id = st.selectbox("Delete a zone", [zone.seat_id for zone in zones], index=None, placeholder="Choose a zone")
        if st.button("Delete Selected Zone", disabled=not delete_id):
            updated = [zone for zone in zones if zone.seat_id != delete_id]
            save_zones(updated)
            st.success(f"Deleted {delete_id}")
            st.rerun()


def _logs_tab(config) -> None:
    store = _store(config)
    st.subheader("Current Status")
    current = store.get_current()
    st.dataframe(current, width="stretch", hide_index=True)

    st.subheader("Status Change Log")
    st.dataframe(store.get_log(limit=200), width="stretch", hide_index=True)
    if st.button("Reset Status Log"):
        store.reset_logs()
        st.success("Status log cleared.")
        st.rerun()


def _settings_tab(config, runtime_detection) -> None:
    st.subheader("Loaded Settings")
    st.code(
        f"""
settings_path = {config.settings_path}
camera_source = {config.camera.source}
mock_mode = {config.mock_mode}
database = {config.storage.db_path}
save_snapshots = {config.privacy.save_snapshots}

yolo_enabled = {runtime_detection.yolo_enabled}
yolo_interval_seconds = {runtime_detection.yolo_interval_seconds}
yolo_model = {runtime_detection.yolo_model}
object_occupancy_enabled = {runtime_detection.object_occupancy_enabled}
object_conservativeness = {runtime_detection.object_conservativeness}
required_object_hits = {_state_engine(runtime_detection).required_object_hits}
object_conf_threshold = {_state_engine(runtime_detection).object_conf_threshold:.2f}
""".strip()
    )
    st.info(
        "Privacy default: no raw video is saved. Status, evidence summaries, timestamps, and optional snapshots are stored locally."
    )


def _capture(config) -> Any:
    return _capture_manager(config).read_frame()


def _capture_manager(config) -> CaptureManager:
    key = (config.camera.source, config.mock_mode, config.camera.mock_image_path, config.camera.device_index)
    if st.session_state.get("capture_key") != key:
        old_manager = st.session_state.get("capture_manager")
        if old_manager is not None:
            old_manager.close()
        st.session_state.capture_key = key
        st.session_state.capture_manager = CaptureManager(config)
    return st.session_state.capture_manager


def _diff_detector(detection) -> DiffDetector:
    key = (detection.baseline_path, detection.diff_threshold, detection.change_ratio_threshold)
    if st.session_state.get("diff_key") != key:
        st.session_state.diff_key = key
        st.session_state.diff_detector = DiffDetector.from_config(detection)
    return st.session_state.diff_detector


def _yolo_detector(detection) -> YoloDetector:
    key = (detection.yolo_enabled, detection.yolo_model, detection.yolo_interval_seconds)
    if st.session_state.get("yolo_key") != key:
        st.session_state.yolo_key = key
        st.session_state.yolo_detector = YoloDetector(
            enabled=detection.yolo_enabled,
            model_name=detection.yolo_model,
            interval_seconds=detection.yolo_interval_seconds,
        )
    return st.session_state.yolo_detector


def _state_engine(detection) -> SeatStateEngine:
    key = (
        detection.object_occupancy_enabled,
        detection.object_conservativeness,
        detection.empty_required_hits,
        detection.person_required_hits,
    )
    if st.session_state.get("state_key") != key:
        st.session_state.state_key = key
        st.session_state.state_engine = SeatStateEngine.from_config(detection)
    return st.session_state.state_engine


def _store(config) -> StatusStore:
    key = config.storage.db_path
    if st.session_state.get("store_key") != key:
        st.session_state.store_key = key
        st.session_state.store = StatusStore(config.storage.db_path)
    return st.session_state.store


def _merge_evidence(
    base: dict[str, ZoneEvidence],
    update: dict[str, ZoneEvidence],
) -> dict[str, ZoneEvidence]:
    merged = dict(base)
    for seat_id, evidence in update.items():
        merged[seat_id] = merged.get(seat_id, ZoneEvidence()).merge(evidence)
    return merged


def _display_image_for_canvas(frame: np.ndarray) -> tuple[Image.Image, float, float]:
    image = Image.fromarray(frame)
    max_width = 900
    if image.width <= max_width:
        return image, 1.0, 1.0
    ratio = max_width / image.width
    resized = image.resize((max_width, int(image.height * ratio)))
    return resized, image.width / resized.width, image.height / resized.height


def _polygon_from_canvas(canvas_result: Any, scale_x: float, scale_y: float) -> list[tuple[int, int]]:
    if canvas_result is None or not getattr(canvas_result, "json_data", None):
        return []
    objects = canvas_result.json_data.get("objects", [])
    if not objects:
        return []

    obj = objects[-1]
    points = _extract_points(obj)
    return [(int(round(x * scale_x)), int(round(y * scale_y))) for x, y in points]


def _extract_points(obj: dict) -> list[tuple[float, float]]:
    left = float(obj.get("left", 0) or 0)
    top = float(obj.get("top", 0) or 0)
    scale_x = float(obj.get("scaleX", 1) or 1)
    scale_y = float(obj.get("scaleY", 1) or 1)

    if obj.get("type") == "rect":
        width = float(obj.get("width", 0) or 0) * scale_x
        height = float(obj.get("height", 0) or 0) * scale_y
        return [(left, top), (left + width, top), (left + width, top + height), (left, top + height)]

    if isinstance(obj.get("points"), list):
        return [
            (left + float(point.get("x", 0)) * scale_x, top + float(point.get("y", 0)) * scale_y)
            for point in obj["points"]
        ]

    if isinstance(obj.get("path"), list):
        points = []
        for command in obj["path"]:
            if isinstance(command, list) and len(command) >= 3 and command[0] in {"M", "L"}:
                points.append((left + float(command[1]) * scale_x, top + float(command[2]) * scale_y))
        return points

    return []


def _patch_drawable_canvas_image_helper() -> None:
    """Keep streamlit-drawable-canvas working with newer Streamlit versions."""
    import streamlit.elements.image as st_image

    if hasattr(st_image, "image_to_url"):
        return

    from streamlit.elements.lib.image_utils import image_to_url
    from streamlit.elements.lib.layout_utils import LayoutConfig

    def image_to_url_compat(image, width, clamp, channels, output_format, image_id):
        return image_to_url(
            image,
            LayoutConfig(width=width),
            clamp,
            channels,
            output_format,
            image_id,
        )

    st_image.image_to_url = image_to_url_compat


def _next_seat_id(zones: list[Zone]) -> str:
    used = {zone.seat_id for zone in zones}
    index = len(zones) + 1
    while f"seat_{index:03d}" in used:
        index += 1
    return f"seat_{index:03d}"


def _ensure_runtime_dirs(config) -> None:
    for relative in ("data", "data/snapshots", "config"):
        resolve_path(relative, config.project_root).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    main()
