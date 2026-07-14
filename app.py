from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Any

import numpy as np
import streamlit as st
from PIL import Image

from homebase_camera.capture import CaptureManager, FrameResult
from homebase_camera.config import AppConfig, ConfigError, load_settings, resolve_path
from homebase_camera.demo import (
    DemoError,
    DemoStep,
    demo_evidence_for_step,
    is_demo_mode,
    load_demo_frame,
    load_demo_timeline,
)
from homebase_camera.diff_detector import DiffDetector
from homebase_camera.scheduler import IntervalGate, RuntimeSnapshot
from homebase_camera.state_engine import SeatDecision, SeatStateEngine, ZoneEvidence
from homebase_camera.storage import StatusStore
from homebase_camera.streaming import StreamServerInfo, ensure_streaming_server
from homebase_camera.validation import polygon_area, validate_zones
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
    demo_mode = is_demo_mode(config)
    st.title("Homebase Camera")
    if demo_mode:
        st.caption("PC demo mode: generated frames and demo evidence. This is for presentation and mapping practice.")
    else:
        st.caption("Local Raspberry Pi seat occupancy detector: 0 empty, 1 person, 2 temporarily left/object.")

    for warning in config.warnings:
        st.info(warning)

    runtime_detection, ui_state = _sidebar_controls(config, demo_mode)
    stream_info = _start_live_stream(config, demo_mode)
    refresh_count = _auto_refresh(ui_state)
    demo_step = _demo_controls(config, demo_mode, refresh_count, ui_state)

    zones, editor_zones, zone_source = _load_zone_sets(config, demo_mode)
    frame_result = _get_frame(config, demo_mode, demo_step)
    frame = frame_result.frame

    if frame_result.ok and not demo_mode:
        _capture_manager(config).save_latest_snapshot(frame)
    elif not frame_result.ok:
        st.warning(frame_result.message)

    if zone_source:
        st.caption(f"Zone source: `{_display_path(zone_source, config.project_root)}`")
    _show_zone_warnings(editor_zones, frame.shape)

    tab_monitor, tab_editor, tab_logs, tab_settings = st.tabs(["Monitor", "Zone Editor", "Logs", "Settings"])

    with tab_monitor:
        _monitor_tab(config, runtime_detection, frame, frame_result.message, zones, demo_step, stream_info)

    with tab_editor:
        _zone_editor_tab(config, frame, editor_zones, demo_mode, stream_info)

    with tab_logs:
        _logs_tab(config)

    with tab_settings:
        _settings_tab(config, runtime_detection, ui_state, demo_mode)


def _sidebar_controls(config: AppConfig, demo_mode: bool):
    st.sidebar.header("Runtime Controls")
    auto_refresh = st.sidebar.toggle("Auto-refresh", value=bool(config.ui.auto_refresh_enabled))
    refresh_interval = st.sidebar.slider(
        "Refresh interval seconds",
        min_value=1,
        max_value=30,
        value=int(config.ui.refresh_interval_seconds),
    )
    manual_refresh = st.sidebar.button("Manual refresh")
    if manual_refresh:
        st.rerun()

    st.sidebar.divider()
    yolo_enabled = st.sidebar.toggle(
        "YOLO correction",
        value=False if demo_mode else bool(config.detection.yolo_enabled),
        disabled=demo_mode,
        help="Disabled in PC demo mode. Demo evidence is generated, not YOLO output.",
    )
    object_enabled = st.sidebar.toggle(
        "Object occupancy",
        value=bool(config.detection.object_occupancy_enabled),
        help="When disabled, status 2 is never published.",
    )
    conservativeness = st.sidebar.slider(
        "Object conservativeness",
        min_value=0,
        max_value=10,
        value=int(config.detection.object_conservativeness),
        help="0 triggers status 2 easily; 10 requires stronger repeated evidence.",
    )
    st.sidebar.metric("YOLO interval", f"{config.detection.yolo_interval_seconds}s")
    st.sidebar.metric("Diff interval target", f"{config.detection.diff_interval_seconds}s")

    runtime_detection = replace(
        config.detection,
        yolo_enabled=yolo_enabled,
        object_occupancy_enabled=object_enabled,
        object_conservativeness=conservativeness,
    )
    ui_state = {
        "auto_refresh": auto_refresh,
        "refresh_interval": refresh_interval,
        "manual_refresh": manual_refresh,
    }
    return runtime_detection, ui_state


def _auto_refresh(ui_state: dict[str, Any]) -> int:
    if not ui_state["auto_refresh"]:
        return int(st.session_state.get("auto_refresh_count", 0))
    try:
        from streamlit_autorefresh import st_autorefresh  # type: ignore
    except Exception as exc:
        st.sidebar.warning(f"Auto-refresh package is unavailable: {exc}")
        return int(st.session_state.get("auto_refresh_count", 0))

    try:
        count = int(
            st_autorefresh(
                interval=max(1, int(ui_state["refresh_interval"])) * 1000,
                key="homebase_auto_refresh",
            )
        )
    except Exception as exc:
        st.sidebar.warning(f"Auto-refresh component is unavailable: {exc}")
        return int(st.session_state.get("auto_refresh_count", 0))
    st.session_state.auto_refresh_count = count
    return count


def _start_live_stream(config: AppConfig, demo_mode: bool) -> StreamServerInfo | None:
    if demo_mode or not config.streaming.enabled:
        return None
    try:
        return ensure_streaming_server(config, _capture_manager(config))
    except Exception as exc:
        st.warning(f"Live stream server is unavailable: {exc}")
        return None


def _demo_controls(config: AppConfig, demo_mode: bool, refresh_count: int, ui_state: dict[str, Any]) -> DemoStep | None:
    if not demo_mode:
        return None

    st.sidebar.divider()
    st.sidebar.header("Demo Playback")
    try:
        timeline = load_demo_timeline(config.demo)
    except DemoError as exc:
        st.error(str(exc))
        st.stop()

    step_count = len(timeline.steps)
    st.session_state.setdefault("demo_index", 0)
    st.session_state.setdefault("last_demo_refresh_count", refresh_count)
    st.session_state.setdefault("demo_autoplay", bool(config.demo.autoplay))
    st.session_state.setdefault("demo_show_ground_truth", bool(config.demo.show_ground_truth))
    st.session_state.setdefault("demo_show_detector_evidence", bool(config.demo.show_detector_evidence))

    autoplay = st.sidebar.toggle("Autoplay demo", key="demo_autoplay")
    st.sidebar.toggle("Show ground truth", key="demo_show_ground_truth")
    st.sidebar.toggle("Show detector evidence", key="demo_show_detector_evidence")

    col_prev, col_next = st.sidebar.columns(2)
    if col_prev.button("Previous frame"):
        st.session_state.demo_index = (int(st.session_state.demo_index) - 1) % step_count
        st.rerun()
    if col_next.button("Next frame"):
        st.session_state.demo_index = (int(st.session_state.demo_index) + 1) % step_count
        st.rerun()
    if st.sidebar.button("Reset demo"):
        st.session_state.demo_index = 0
        st.rerun()

    if autoplay and ui_state["auto_refresh"] and refresh_count != st.session_state.last_demo_refresh_count:
        st.session_state.demo_index = (int(st.session_state.demo_index) + 1) % step_count
    st.session_state.last_demo_refresh_count = refresh_count

    step = timeline.step_at(int(st.session_state.demo_index))
    st.sidebar.caption(f"Frame {int(st.session_state.demo_index) + 1}/{step_count}: {step.label}")
    return step


def _load_zone_sets(config: AppConfig, demo_mode: bool) -> tuple[list[Zone], list[Zone], Path | None]:
    zone_path = config.demo.seats_path if demo_mode else "config/seats.json"
    fallback_path = config.demo.seats_path if demo_mode else "config/seats.example.json"
    try:
        monitor_result = load_zones(zone_path, fallback_path=fallback_path, include_disabled=False)
        editor_result = load_zones(zone_path, fallback_path=fallback_path, include_disabled=True)
    except ZoneConfigError as exc:
        st.error(f"Zone configuration problem: {exc}")
        return [], [], None

    for warning in monitor_result.warnings:
        st.warning(warning)
    return list(monitor_result.zones), list(editor_result.zones), monitor_result.source_path


def _get_frame(config: AppConfig, demo_mode: bool, demo_step: DemoStep | None) -> FrameResult:
    if demo_mode and demo_step is not None:
        try:
            frame = load_demo_frame(demo_step, config.demo)
            return FrameResult(frame=frame, ok=True, message=f"Demo frame: {demo_step.label}")
        except DemoError as exc:
            st.error(str(exc))
            st.stop()
    return _capture_manager(config).read_frame()


def _monitor_tab(
    config: AppConfig,
    runtime_detection,
    frame: np.ndarray,
    frame_message: str,
    zones: list[Zone],
    demo_step: DemoStep | None,
    stream_info: StreamServerInfo | None,
) -> None:
    if stream_info is not None:
        _live_stream_panel(stream_info)

    if not zones:
        st.info("No enabled zones are configured yet. Open Zone Editor or run tools/zone_editor_cv.py.")
        st.image(Image.fromarray(frame), caption=frame_message, width="stretch")
        return

    if demo_step is not None:
        st.info("Demo mode is using generated frames and injected demo evidence. This is not real AI detection.")

    decisions, evidence_by_seat, runtime = _run_analysis(config, runtime_detection, frame, zones, demo_step)
    status_map = {seat_id: decision.status for seat_id, decision in decisions.items()}
    overlay = draw_zones(frame, zones, status_map)

    left, right = st.columns([1.7, 1], gap="large")
    with left:
        st.subheader("Camera Frame")
        st.image(overlay, caption=frame_message, width="stretch")
        _runtime_metrics(runtime, runtime_detection, demo_step is not None)
        if st.session_state.get("last_diff_warning"):
            st.warning(st.session_state.last_diff_warning)
        if runtime_detection.yolo_enabled:
            yolo_detector = _yolo_detector(runtime_detection)
            if yolo_detector.status.available:
                st.success(yolo_detector.status.message)
            else:
                st.warning(yolo_detector.status.message)
        else:
            st.info("YOLO correction is disabled. The app is using pixel-difference and/or demo evidence only.")

        if demo_step is not None and st.session_state.get("demo_show_ground_truth", True):
            st.subheader("Demo Ground Truth")
            st.json(demo_step.expected_status, expanded=False)
        if st.session_state.get("demo_show_detector_evidence", True):
            with st.expander("Detector / demo evidence", expanded=False):
                st.json({seat_id: evidence.__dict__ for seat_id, evidence in evidence_by_seat.items()}, expanded=False)

    with right:
        st.subheader("Seat Status")
        for decision in decisions.values():
            _status_card(decision)


def _live_stream_panel(stream_info: StreamServerInfo) -> None:
    st.subheader("Live Camera Stream")
    st.markdown(
        f"""
        <img
          src="{stream_info.stream_url}"
          style="width:100%;max-height:72vh;object-fit:contain;background:#111827;border:1px solid #cbd5e1"
          alt="Live camera stream">
        """,
        unsafe_allow_html=True,
    )
    st.caption(f"Live stream: {stream_info.stream_url}")
    st.link_button("Open live zone editor", stream_info.zone_editor_url)


def _run_analysis(
    config: AppConfig,
    runtime_detection,
    frame: np.ndarray,
    zones: list[Zone],
    demo_step: DemoStep | None,
) -> tuple[dict[str, SeatDecision], dict[str, ZoneEvidence], RuntimeSnapshot]:
    now = time.monotonic()
    now_dt = datetime.now(UTC)
    diff_gate = _interval_gate("diff", runtime_detection.diff_interval_seconds)
    yolo_gate = _interval_gate("yolo", runtime_detection.yolo_interval_seconds)
    store = _store(config)
    state_engine = _state_engine(runtime_detection, store, config.storage.db_path)

    diff_ran = False
    if diff_gate.should_run(now) or "last_diff_evidence" not in st.session_state:
        diff_detector = _diff_detector(runtime_detection)
        diff_evidence = diff_detector.analyze(frame, zones)
        st.session_state.last_diff_evidence = diff_evidence
        st.session_state.last_diff_warning = diff_detector.warning
        diff_gate.mark_run(now, now_dt)
        diff_ran = True
    else:
        diff_evidence = st.session_state.get("last_diff_evidence", {})

    yolo_ran = False
    if runtime_detection.yolo_enabled:
        yolo_detector = _yolo_detector(runtime_detection)
        if yolo_gate.should_run(now) or "last_yolo_evidence" not in st.session_state:
            yolo_evidence = yolo_detector.detect(frame, zones, force=True)
            st.session_state.last_yolo_evidence = yolo_evidence
            yolo_gate.mark_run(now, now_dt)
            yolo_ran = True
        else:
            yolo_evidence = st.session_state.get("last_yolo_evidence", {})
    else:
        yolo_evidence = {}
        st.session_state.last_yolo_evidence = {}

    evidence_by_seat = _merge_evidence(diff_evidence, yolo_evidence)
    demo_index = st.session_state.get("demo_index")
    demo_changed = demo_step is not None and demo_index != st.session_state.get("last_demo_analysis_index")
    if demo_step is not None:
        demo_evidence = demo_evidence_for_step(demo_step)
        evidence_by_seat = {**evidence_by_seat, **demo_evidence}

    should_update_status = (
        diff_ran
        or yolo_ran
        or demo_changed
        or "last_decisions" not in st.session_state
        or set(st.session_state.get("last_decisions", {}).keys()) != {zone.seat_id for zone in zones}
    )
    if should_update_status:
        decisions = state_engine.update_all(zones, evidence_by_seat)
        store.upsert_many(decisions.values())
        st.session_state.last_decisions = decisions
        st.session_state.last_evidence_by_seat = evidence_by_seat
        st.session_state.last_demo_analysis_index = demo_index
    else:
        decisions = st.session_state.get("last_decisions", {})
        evidence_by_seat = st.session_state.get("last_evidence_by_seat", evidence_by_seat)

    runtime = RuntimeSnapshot(
        diff_ran=diff_ran,
        yolo_ran=yolo_ran,
        last_diff_run=diff_gate.last_run_label,
        last_yolo_run=yolo_gate.last_run_label,
        next_diff_seconds=diff_gate.seconds_until_next(now),
        next_yolo_seconds=yolo_gate.seconds_until_next(now),
    )
    return decisions, evidence_by_seat, runtime


def _runtime_metrics(runtime: RuntimeSnapshot, runtime_detection, demo_mode: bool) -> None:
    st.subheader("Analysis Timing")
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Last diff run", runtime.last_diff_run, "ran now" if runtime.diff_ran else None)
    col_b.metric("Next diff", f"{runtime.next_diff_seconds:.1f}s")
    if runtime_detection.yolo_enabled:
        col_c.metric("Last YOLO run", runtime.last_yolo_run, "ran now" if runtime.yolo_ran else None)
        col_d.metric("Next YOLO", f"{runtime.next_yolo_seconds:.1f}s")
    else:
        col_c.metric("YOLO", "disabled")
        col_d.metric("Mode", "demo" if demo_mode else "diff-only")


def _status_card(decision: SeatDecision) -> None:
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


def _zone_editor_tab(
    config: AppConfig,
    frame: np.ndarray,
    zones: list[Zone],
    demo_mode: bool,
    stream_info: StreamServerInfo | None,
) -> None:
    st.subheader("Zone Editor")
    if stream_info is not None:
        st.info("Use the live editor below to draw zones directly on the camera stream.")
        st.link_button("Open live zone editor in a new tab", stream_info.zone_editor_url)
        st.markdown(
            f"""
            <iframe
              src="{stream_info.zone_editor_url}"
              style="width:100%;height:760px;border:1px solid #cbd5e1;background:white"
              title="Homebase live zone editor"></iframe>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

    if not zones:
        st.warning("No zones are configured. Draw a polygon and save the first seat zone.")
    st.write("Draw a polygon around one seat, enter a seat id/name, then save. Existing zones can be renamed, disabled, duplicated, or deleted below.")

    target_options = {
        "Demo seats file": config.demo.seats_path,
        "Normal config/seats.json": "config/seats.json",
    }
    default_index = 0 if demo_mode else 1
    target_label = st.radio("Save target", list(target_options.keys()), index=default_index, horizontal=True)
    target_path = target_options[target_label]

    display_image, scale_x, scale_y = _display_image_for_canvas(_editor_background(config, frame))

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
        st.warning("Interactive Streamlit drawing is unavailable. Use the fallback command: python tools/zone_editor_cv.py")
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
            target = save_zones(updated, target_path)
            st.success(f"Saved {seat_id.strip()} to {target}")
            st.rerun()

    st.divider()
    st.subheader("Existing Zones")
    st.image(draw_zones(frame, zones), width="stretch")
    _existing_zone_editor(zones, target_path)
    st.subheader("Zone JSON Preview")
    st.json({"zones": [zone.to_json() for zone in zones]}, expanded=False)


def _editor_background(config: AppConfig, frame: np.ndarray) -> np.ndarray:
    choices = ["Current frame"]
    latest = resolve_path("data/snapshots/latest.jpg", config.project_root)
    if latest.exists():
        choices.append("Latest snapshot")
    if is_demo_mode(config):
        choices.append("Demo mapping frame")
    selected = st.selectbox("Editor background", choices)
    if selected == "Latest snapshot":
        return np.asarray(Image.open(latest).convert("RGB"))
    if selected == "Demo mapping frame":
        timeline = load_demo_timeline(config.demo)
        return load_demo_frame(timeline.step_at(0), config.demo)
    return frame


def _existing_zone_editor(zones: list[Zone], target_path: str | Path) -> None:
    if not zones:
        return
    selected_id = st.selectbox("Select a zone", [zone.seat_id for zone in zones])
    selected = next(zone for zone in zones if zone.seat_id == selected_id)
    st.code("\n".join(f"{index + 1}: ({x}, {y})" for index, (x, y) in enumerate(selected.polygon)))
    st.caption(f"Polygon area: {polygon_area(selected.polygon):.0f} px")

    with st.form("edit_existing_zone"):
        new_name = st.text_input("Seat name", selected.seat_name)
        enabled = st.checkbox("Enabled", selected.enabled)
        action = st.radio("Action", ["Save changes", "Duplicate zone", "Delete zone"], horizontal=True)
        submitted = st.form_submit_button("Apply")

    if not submitted:
        return
    if action == "Delete zone":
        updated = [zone for zone in zones if zone.seat_id != selected.seat_id]
    elif action == "Duplicate zone":
        copy_id = _copy_zone_id(zones, selected.seat_id)
        offset_polygon = tuple((x + 20, y + 20) for x, y in selected.polygon)
        updated = list(zones) + [
            Zone(seat_id=copy_id, seat_name=f"{selected.seat_name} copy", polygon=offset_polygon, enabled=enabled)
        ]
    else:
        updated = [
            Zone(zone.seat_id, new_name if zone.seat_id == selected.seat_id else zone.seat_name, zone.polygon, enabled if zone.seat_id == selected.seat_id else zone.enabled)
            for zone in zones
        ]
    save_zones(updated, target_path)
    st.success(f"Updated {target_path}")
    st.rerun()


def _logs_tab(config: AppConfig) -> None:
    store = _store(config)
    st.subheader("Current Status")
    _safe_dataframe(store.get_current(), empty_message="No current status has been recorded yet.")

    st.subheader("Status Change Log")
    _safe_dataframe(store.get_log(limit=200), empty_message="No status changes have been recorded yet.")
    if st.button("Reset Status Log"):
        store.reset_logs()
        st.success("Status log cleared.")
        st.rerun()


def _safe_dataframe(records: list[dict], *, empty_message: str) -> None:
    if not records:
        st.caption(empty_message)
        return
    try:
        st.dataframe(records, width="stretch", hide_index=True)
    except Exception as exc:
        if not _is_pyarrow_unavailable(exc):
            raise
        st.warning("Table view requires PyArrow on this platform. Showing JSON fallback.")
        st.json(records, expanded=False)


def _is_pyarrow_unavailable(exc: Exception) -> bool:
    if isinstance(exc, ModuleNotFoundError) and exc.name == "pyarrow":
        return True
    return "pyarrow" in str(exc).lower()


def _settings_tab(config: AppConfig, runtime_detection, ui_state: dict[str, Any], demo_mode: bool) -> None:
    st.subheader("Loaded Settings")
    st.code(
        f"""
settings_path = {config.settings_path}
demo_mode = {demo_mode}
camera_source = {config.camera.source}
mock_mode = {config.mock_mode}
database = {config.storage.db_path}
sqlite_timeout_seconds = {config.storage.timeout_seconds}
sqlite_busy_timeout_ms = {config.storage.busy_timeout_ms}
sqlite_wal_enabled = {config.storage.wal_enabled}
save_snapshots = {config.privacy.save_snapshots}
snapshot_interval_seconds = {config.privacy.snapshot_interval_seconds}

auto_refresh_enabled = {ui_state["auto_refresh"]}
refresh_interval_seconds = {ui_state["refresh_interval"]}
diff_interval_seconds = {runtime_detection.diff_interval_seconds}
yolo_enabled = {runtime_detection.yolo_enabled}
yolo_interval_seconds = {runtime_detection.yolo_interval_seconds}
yolo_model = {runtime_detection.yolo_model}
object_occupancy_enabled = {runtime_detection.object_occupancy_enabled}
object_conservativeness = {runtime_detection.object_conservativeness}
required_object_hits = {_state_engine(runtime_detection, _store(config), config.storage.db_path).required_object_hits}
object_conf_threshold = {_state_engine(runtime_detection, _store(config), config.storage.db_path).object_conf_threshold:.2f}
""".strip()
    )
    st.info("Privacy default: no raw video is saved. Status, evidence summaries, timestamps, and optional throttled snapshots are stored locally.")
    if config.camera.source == "picamera2":
        st.warning("Multi-session note: capture resources are cached to reduce duplicate camera opens, but one dashboard operator is still recommended on Raspberry Pi.")


@st.cache_resource
def _cached_capture_manager(config: AppConfig) -> CaptureManager:
    return CaptureManager(config)


def _capture_manager(config: AppConfig) -> CaptureManager:
    return _cached_capture_manager(config)


def _diff_detector(detection) -> DiffDetector:
    key = (detection.baseline_path, detection.diff_threshold, detection.change_ratio_threshold)
    if st.session_state.get("diff_key") != key:
        st.session_state.diff_key = key
        st.session_state.diff_detector = DiffDetector.from_config(detection)
        st.session_state.pop("last_diff_evidence", None)
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
        st.session_state.pop("last_yolo_evidence", None)
    return st.session_state.yolo_detector


def _state_engine(detection, store: StatusStore, store_key: str) -> SeatStateEngine:
    key = (
        detection.object_occupancy_enabled,
        detection.object_conservativeness,
        detection.empty_required_hits,
        detection.person_required_hits,
        store_key,
    )
    if st.session_state.get("state_key") != key:
        st.session_state.state_key = key
        engine = SeatStateEngine.from_config(detection)
        engine.restore_statuses(store.get_current())
        st.session_state.state_engine = engine
        st.session_state.pop("last_decisions", None)
    return st.session_state.state_engine


def _store(config: AppConfig) -> StatusStore:
    key = (
        config.storage.db_path,
        config.storage.timeout_seconds,
        config.storage.busy_timeout_ms,
        config.storage.wal_enabled,
    )
    if st.session_state.get("store_key") != key:
        st.session_state.store_key = key
        st.session_state.store = StatusStore(
            config.storage.db_path,
            timeout_seconds=config.storage.timeout_seconds,
            busy_timeout_ms=config.storage.busy_timeout_ms,
            wal_enabled=config.storage.wal_enabled,
        )
    return st.session_state.store


def _interval_gate(name: str, interval_seconds: int) -> IntervalGate:
    key = f"{name}_gate_key"
    gate_name = f"{name}_gate"
    current_key = (int(interval_seconds),)
    if st.session_state.get(key) != current_key:
        st.session_state[key] = current_key
        st.session_state[gate_name] = IntervalGate(interval_seconds=int(interval_seconds))
    return st.session_state[gate_name]


def _merge_evidence(base: dict[str, ZoneEvidence], update: dict[str, ZoneEvidence]) -> dict[str, ZoneEvidence]:
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
    points = _extract_points(objects[-1])
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
        return [
            (left + float(command[1]) * scale_x, top + float(command[2]) * scale_y)
            for command in obj["path"]
            if isinstance(command, list) and len(command) >= 3 and command[0] in {"M", "L"}
        ]
    return []


def _patch_drawable_canvas_image_helper() -> None:
    """Keep streamlit-drawable-canvas working with newer Streamlit versions."""
    import streamlit.elements.image as st_image

    if hasattr(st_image, "image_to_url"):
        return

    from streamlit.elements.lib.image_utils import image_to_url
    from streamlit.elements.lib.layout_utils import LayoutConfig

    def image_to_url_compat(image, width, clamp, channels, output_format, image_id):
        return image_to_url(image, LayoutConfig(width=width), clamp, channels, output_format, image_id)

    st_image.image_to_url = image_to_url_compat


def _next_seat_id(zones: list[Zone]) -> str:
    used = {zone.seat_id for zone in zones}
    index = len(zones) + 1
    while f"seat_{index:03d}" in used:
        index += 1
    return f"seat_{index:03d}"


def _copy_zone_id(zones: list[Zone], base_id: str) -> str:
    used = {zone.seat_id for zone in zones}
    index = 1
    while f"{base_id}_copy{index}" in used:
        index += 1
    return f"{base_id}_copy{index}"


def _show_zone_warnings(zones: list[Zone], frame_shape: tuple[int, ...]) -> None:
    for warning in validate_zones(zones, frame_shape):
        if warning.severity == "error":
            st.error(f"{warning.seat_id}: {warning.message}")
        else:
            st.warning(f"{warning.seat_id}: {warning.message}")


def _ensure_runtime_dirs(config: AppConfig) -> None:
    for relative in ("data", "data/snapshots", "config", "demo", "demo/frames"):
        resolve_path(relative, config.project_root).mkdir(parents=True, exist_ok=True)


def _display_path(path: str | Path, root: Path) -> str:
    path = Path(path)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
