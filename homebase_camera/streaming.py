from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import socket
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from PIL import Image

from .capture import CaptureManager
from .config import AppConfig, resolve_path
from .diff_detector import DiffDetector
from .state_engine import SeatDecision, SeatStateEngine, ZoneEvidence
from .storage import StatusStore
from .validation import validate_zones
from .visualization import draw_zones
from .yolo_detector import YoloDetector
from .zones import Zone, ZoneConfigError, load_zones, save_zones


_SERVER_LOCK = threading.Lock()
_ZONE_WRITE_LOCK = threading.Lock()
_SERVER: LiveStreamServer | None = None


@dataclass(frozen=True)
class StreamServerInfo:
    base_url: str
    stream_url: str
    zone_editor_url: str
    status_panel_url: str


class LiveStreamServer:
    def __init__(self, config: AppConfig, capture: CaptureManager) -> None:
        self.config = config
        self.capture = capture
        self.httpd = _HomebaseHTTPServer(
            (config.streaming.host, config.streaming.port),
            _StreamHandler,
            config,
            capture,
        )
        self.httpd.analyzer = LiveAnalysisWorker(config, capture)
        self.httpd.stream_frames = LiveFrameProducer(config, capture, self.httpd.analyzer)
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="homebase-camera-stream-server",
            daemon=True,
        )

    def start(self) -> None:
        self.httpd.analyzer.start()
        self.httpd.stream_frames.start()
        if not self.thread.is_alive():
            self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd.stream_frames.stop()
        self.httpd.analyzer.stop()

    @property
    def info(self) -> StreamServerInfo:
        base_url = public_base_url(self.config)
        return StreamServerInfo(
            base_url=base_url,
            stream_url=f"{base_url}/stream.mjpg",
            zone_editor_url=f"{base_url}/zone-editor",
            status_panel_url=f"{base_url}/status-panel",
        )


class _HomebaseHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        config: AppConfig,
        capture: CaptureManager,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.config = config
        self.capture = capture
        self.analyzer: LiveAnalysisWorker
        self.stream_frames: LiveFrameProducer


class _StreamHandler(BaseHTTPRequestHandler):
    server: _HomebaseHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/zone-editor"}:
            self._send_html(_zone_editor_html())
            return
        if parsed.path == "/status-panel":
            self._send_html(_status_panel_html())
            return
        if parsed.path == "/health":
            self._send_json(
                {
                    "ok": True,
                    "fps": self.server.config.streaming.fps,
                    "frame_age_seconds": self.server.capture.frame_age_seconds(),
                    "frame_ok": self.server.capture.latest_ok(),
                    "frame_message": self.server.capture.latest_message(),
                    "capture": self.server.capture.background_status(),
                    "stream": self.server.stream_frames.status(),
                    "analysis": self.server.analyzer.status(),
                }
            )
            return
        if parsed.path == "/snapshot.jpg":
            self._send_snapshot()
            return
        if parsed.path == "/stream.mjpg":
            self._send_mjpeg_stream()
            return
        if parsed.path == "/api/zones":
            target = parse_qs(parsed.query).get("target", ["config"])[0]
            self._send_json(_load_zone_payload(self.server.config, target))
            return
        if parsed.path == "/api/status":
            self._send_json(
                {
                    "ok": True,
                    "analysis": self.server.analyzer.status(),
                    "current": self.server.analyzer.current_rows(),
                }
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({"ok": False, "error": f"Invalid JSON request: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/zones":
            self._send_api_result(_save_zone_payload(self.server.config, payload))
            return
        if parsed.path == "/api/delete-zone":
            self._send_api_result(_delete_zone_payload(self.server.config, payload))
            return
        if parsed.path == "/api/baseline":
            self._send_api_result(self.server.analyzer.capture_baseline())
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.end_headers()

    def _send_mjpeg_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        last_sequence = -1
        while True:
            try:
                packet = self.server.stream_frames.wait_for_frame(last_sequence, timeout=5.0)
                if packet is None:
                    continue
                last_sequence, jpeg = packet
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            except OSError:
                return

    def _send_snapshot(self) -> None:
        packet = self.server.stream_frames.wait_for_frame(-1, timeout=5.0)
        if packet is None:
            self._send_json({"ok": False, "error": "No encoded camera frame is available."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        _, jpeg = packet
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > 1_000_000:
            raise ValueError("request body must be between 0 and 1000000 bytes")
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _send_api_result(self, payload: dict[str, Any]) -> None:
        status = HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_REQUEST
        self._send_json(payload, status)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")


def ensure_streaming_server(config: AppConfig, capture: CaptureManager) -> StreamServerInfo | None:
    if not config.streaming.enabled:
        return None
    global _SERVER
    with _SERVER_LOCK:
        if _SERVER is None:
            capture.start_background(config.streaming.fps)
            _SERVER = LiveStreamServer(config, capture)
            _SERVER.start()
        return _SERVER.info


class LiveAnalysisWorker:
    def __init__(self, config: AppConfig, capture: CaptureManager) -> None:
        self.config = config
        self.capture = capture
        self.store = StatusStore(
            config.storage.db_path,
            timeout_seconds=config.storage.timeout_seconds,
            busy_timeout_ms=config.storage.busy_timeout_ms,
            wal_enabled=config.storage.wal_enabled,
        )
        self.detector = DiffDetector.from_config(config.detection)
        self.yolo = YoloDetector(
            enabled=config.detection.yolo_enabled,
            model_name=config.detection.yolo_model,
            interval_seconds=config.detection.yolo_interval_seconds,
        )
        self.engine = SeatStateEngine.from_config(config.detection)
        self.engine.restore_statuses(self.store.get_current())
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_run = "never"
        self._last_error = ""
        self._last_warning = ""
        self._last_zone_count = 0
        self._last_yolo_run = "never"
        self._zones: list[Zone] = []
        self._decisions: dict[str, SeatDecision] = {}
        self._evidence: dict[str, ZoneEvidence] = {}
        self._last_yolo_evidence: dict[str, ZoneEvidence] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="homebase-camera-analysis", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "running": self._thread is not None and self._thread.is_alive(),
                "last_run": self._last_run,
                "last_error": self._last_error,
                "last_warning": self._last_warning,
                "zone_count": self._last_zone_count,
                "last_yolo_run": self._last_yolo_run,
                "yolo_available": self.yolo.status.available,
                "yolo_message": self.yolo.status.message,
            }

    def current_rows(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "seat_id": decision.seat_id,
                    "seat_name": decision.seat_name,
                    "status": decision.status,
                    "confidence": decision.confidence,
                    "evidence": decision.evidence,
                    "updated_at": decision.updated_at,
                }
                for decision in self._decisions.values()
            ]

    def current_status_map(self) -> dict[str, int]:
        with self._lock:
            return {seat_id: decision.status for seat_id, decision in self._decisions.items()}

    def current_zones(self) -> list[Zone]:
        with self._lock:
            return list(self._zones)

    def capture_baseline(self) -> dict[str, Any]:
        frame_result = self.capture.latest_frame()
        if not frame_result.ok:
            return {"ok": False, "error": frame_result.message}
        with self._run_lock:
            saved = self.detector.set_baseline(frame_result.frame, save=True)
            self.engine.reset()
            self._last_yolo_evidence = {}
            with self._lock:
                self._last_warning = ""
        return {
            "ok": True,
            "path": str(saved) if saved is not None else str(self.detector.baseline_path),
            "message": "Saved the current empty camera view as the detection baseline.",
        }

    def _loop(self) -> None:
        interval = max(0.5, float(self.config.detection.diff_interval_seconds))
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._run_once()
            except Exception as exc:
                with self._lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.1, interval - elapsed))

    def _run_once(self) -> None:
        with self._run_lock:
            zones = _load_enabled_zones(self.config)
            frame_result = self.capture.latest_frame()
            if not zones or not frame_result.ok:
                with self._lock:
                    self._zones = zones
                    self._decisions = {} if not zones else self._decisions
                    self._last_zone_count = len(zones)
                    self._last_error = "" if frame_result.ok else frame_result.message
                    self._last_run = _now_label()
                return

            diff_evidence = self.detector.analyze(frame_result.frame, zones)
            if self.yolo.should_run():
                self._last_yolo_evidence = self.yolo.detect(frame_result.frame, zones, force=True)
                self._last_yolo_run = _now_label()
            evidence = _merge_zone_evidence(diff_evidence, self._last_yolo_evidence)
            decisions = self.engine.update_all(zones, evidence)
            self.store.upsert_many(decisions.values())
            with self._lock:
                self._zones = zones
                self._decisions = decisions
                self._evidence = evidence
                self._last_zone_count = len(zones)
                self._last_error = ""
                self._last_warning = self.detector.warning or ""
                self._last_run = _now_label()


class LiveFrameProducer:
    def __init__(self, config: AppConfig, capture: CaptureManager, analyzer: LiveAnalysisWorker) -> None:
        self.config = config
        self.capture = capture
        self.analyzer = analyzer
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._jpeg: bytes | None = None
        self._sequence = 0
        self._last_capture_sequence = -1
        self._last_frame_monotonic = 0.0
        self._last_encode_ms = 0.0
        self._last_error = ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="homebase-camera-jpeg", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)

    def status(self) -> dict[str, object]:
        with self._condition:
            age = None
            if self._last_frame_monotonic > 0:
                age = max(0.0, time.monotonic() - self._last_frame_monotonic)
            return {
                "running": self._thread is not None and self._thread.is_alive(),
                "sequence": self._sequence,
                "frame_age_seconds": age,
                "last_encode_ms": round(self._last_encode_ms, 1),
                "last_error": self._last_error,
            }

    def wait_for_frame(self, after_sequence: int, *, timeout: float) -> tuple[int, bytes] | None:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self._jpeg is None or self._sequence <= after_sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stop.is_set():
                    return None
                self._condition.wait(remaining)
            return self._sequence, self._jpeg

    def _loop(self) -> None:
        interval = 1.0 / max(1, int(self.config.streaming.fps))
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                if not self.capture.background_running():
                    self.capture.start_background(self.config.streaming.fps)
                frame_result = self.capture.latest_frame()
                capture_sequence = self.capture.latest_sequence()
                if capture_sequence != self._last_capture_sequence:
                    zones = self.analyzer.current_zones()
                    status_map = self.analyzer.current_status_map()
                    frame = draw_zones(frame_result.frame, zones, status_map) if zones else frame_result.frame
                    jpeg = _jpeg_bytes(frame, quality=self.config.streaming.jpeg_quality)
                    encode_ms = (time.monotonic() - started) * 1000
                    with self._condition:
                        self._jpeg = jpeg
                        self._sequence += 1
                        self._last_capture_sequence = capture_sequence
                        self._last_frame_monotonic = time.monotonic()
                        self._last_encode_ms = encode_ms
                        self._last_error = ""
                        self._condition.notify_all()
            except Exception as exc:
                with self._condition:
                    self._last_error = f"{type(exc).__name__}: {exc}"
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.01, interval - elapsed))


def _merge_zone_evidence(
    base: dict[str, ZoneEvidence],
    update: dict[str, ZoneEvidence],
) -> dict[str, ZoneEvidence]:
    merged = dict(base)
    for seat_id, evidence in update.items():
        merged[seat_id] = merged.get(seat_id, ZoneEvidence()).merge(evidence)
    return merged


def _now_label() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def public_base_url(config: AppConfig) -> str:
    configured = socket.getfqdn()
    if configured in {"localhost", "localhost.localdomain"}:
        configured = _guess_lan_ip()
    host = _guess_lan_ip() if configured.startswith("127.") else configured
    host = _guess_lan_ip() if not host or "." not in host else host
    return f"http://{host}:{config.streaming.port}"


def _guess_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _jpeg_bytes(frame: Any, *, quality: int) -> bytes:
    image = frame.convert("RGB") if isinstance(frame, Image.Image) else Image.fromarray(frame).convert("RGB")
    output = BytesIO()
    image.save(output, format="JPEG", quality=int(quality), optimize=False)
    return output.getvalue()


def _load_enabled_zones(config: AppConfig) -> list[Zone]:
    try:
        return list(load_zones("config/seats.json", fallback_path="config/seats.example.json").zones)
    except ZoneConfigError:
        return []


def _target_path(config: AppConfig, target: str) -> str:
    if target == "demo":
        return config.demo.seats_path
    return "config/seats.json"


def _load_zone_payload(config: AppConfig, target: str) -> dict[str, Any]:
    try:
        result = load_zones(_target_path(config, target), include_disabled=True)
        return {
            "ok": True,
            "target": target,
            "path": str(result.source_path),
            "zones": [zone.to_json() for zone in result.zones],
            "warnings": list(result.warnings),
        }
    except ZoneConfigError as exc:
        return {"ok": False, "target": target, "error": str(exc), "zones": []}


def _save_zone_payload(config: AppConfig, payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload.get("target", "config"))
    seat_id = str(payload.get("seat_id", "")).strip()
    seat_name = str(payload.get("seat_name", "")).strip() or seat_id
    enabled = bool(payload.get("enabled", True))
    try:
        polygon = _parse_polygon(payload.get("polygon"))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not seat_id:
        return {"ok": False, "error": "seat_id is required."}
    if len(polygon) < 3:
        return {"ok": False, "error": "polygon must contain at least three points."}

    target_path = _target_path(config, target)
    try:
        with _ZONE_WRITE_LOCK:
            existing = _load_existing_zones(config, target)
            updated = [zone for zone in existing if zone.seat_id != seat_id]
            updated.append(Zone(seat_id=seat_id, seat_name=seat_name, polygon=tuple(polygon), enabled=enabled))
            saved = save_zones(updated, target_path)
    except (OSError, ZoneConfigError) as exc:
        return {"ok": False, "error": f"Could not save zones: {exc}"}
    warnings = validate_zones(
        updated,
        (config.camera.frame_height, config.camera.frame_width, 3),
    )
    return {
        "ok": True,
        "path": str(saved),
        "zones": [zone.to_json() for zone in updated],
        "warnings": [f"{warning.seat_id}: {warning.message}" for warning in warnings],
    }


def _delete_zone_payload(config: AppConfig, payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload.get("target", "config"))
    seat_id = str(payload.get("seat_id", "")).strip()
    if not seat_id:
        return {"ok": False, "error": "seat_id is required."}
    target_path = _target_path(config, target)
    try:
        with _ZONE_WRITE_LOCK:
            existing = _load_existing_zones(config, target)
            if not any(zone.seat_id == seat_id for zone in existing):
                return {"ok": False, "error": f"Zone '{seat_id}' was not found."}
            updated = [zone for zone in existing if zone.seat_id != seat_id]
            saved = save_zones(updated, target_path)
    except (OSError, ZoneConfigError) as exc:
        return {"ok": False, "error": f"Could not delete zone: {exc}"}
    return {"ok": True, "path": str(saved), "zones": [zone.to_json() for zone in updated]}


def _load_existing_zones(config: AppConfig, target: str) -> list[Zone]:
    path = _target_path(config, target)
    resolved = resolve_path(path, config.project_root)
    if not resolved.exists():
        return []
    return list(load_zones(path, include_disabled=True).zones)


def _parse_polygon(value: Any) -> list[tuple[int, int]]:
    if not isinstance(value, list):
        raise ValueError("polygon must be a list of [x, y] points.")
    points: list[tuple[int, int]] = []
    for index, item in enumerate(value):
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise ValueError(f"polygon[{index}] must be [x, y].")
        try:
            points.append((int(round(float(item[0]))), int(round(float(item[1])))))
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(f"polygon[{index}] must contain finite numbers.") from exc
    return points


def _status_panel_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Homebase Live Status</title>
<style>
:root { color-scheme: light; font-family: Arial, sans-serif; }
body { margin: 0; color: #0f172a; background: white; }
header { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-bottom: 1px solid #cbd5e1; }
#health { font-size: 12px; color: #475569; }
#warning { display: none; margin: 10px 12px 0; padding: 8px; background: #fff7ed; color: #9a3412; border: 1px solid #fdba74; font-size: 12px; }
#rows { display: grid; gap: 8px; padding: 10px 12px 12px; }
.seat { border: 1px solid #cbd5e1; border-left: 7px solid #64748b; padding: 9px 10px; }
.seat-top { display: flex; justify-content: space-between; gap: 10px; font-weight: 700; }
.label { margin-top: 3px; color: #334155; font-size: 13px; }
.meta { margin-top: 4px; color: #64748b; font-size: 11px; overflow-wrap: anywhere; }
.empty { color: #64748b; padding: 12px; }
</style>
</head>
<body>
<header><strong>Live Seat Status</strong><span id="health">connecting</span></header>
<div id="warning"></div>
<div id="rows"><div class="empty">Waiting for analysis...</div></div>
<script>
const colors = {0:'#16a34a', 1:'#dc2626', 2:'#d97706'};
const labels = {0:'Empty', 1:'Person', 2:'Temporarily left / object'};

async function refresh() {
  try {
    const [statusRes, healthRes] = await Promise.all([fetch('/api/status'), fetch('/health')]);
    if (!statusRes.ok || !healthRes.ok) throw new Error(`HTTP ${statusRes.status}/${healthRes.status}`);
    const data = await statusRes.json();
    const health = await healthRes.json();
    const rows = data.current || [];
    const container = document.getElementById('rows');
    container.textContent = '';
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'No enabled seat zones.';
      container.appendChild(empty);
    }
    rows.forEach(row => {
      const seat = document.createElement('div');
      seat.className = 'seat';
      seat.style.borderLeftColor = colors[row.status] || '#64748b';
      const top = document.createElement('div');
      top.className = 'seat-top';
      const name = document.createElement('span');
      name.textContent = row.seat_name || row.seat_id;
      const value = document.createElement('span');
      value.textContent = `status ${row.status}`;
      value.style.color = colors[row.status] || '#64748b';
      top.append(name, value);
      const label = document.createElement('div');
      label.className = 'label';
      label.textContent = `${labels[row.status] || 'Unknown'} / confidence ${Number(row.confidence || 0).toFixed(2)}`;
      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.textContent = row.evidence || '';
      seat.append(top, label, meta);
      container.appendChild(seat);
    });
    const captureAge = Number(health.frame_age_seconds || 0);
    document.getElementById('health').textContent = `frame ${captureAge.toFixed(2)}s / analysis ${data.analysis.last_run || 'never'}`;
    const warning = document.getElementById('warning');
    const message = data.analysis.last_error || data.analysis.last_warning || health.stream.last_error || health.capture.last_error || '';
    warning.textContent = message;
    warning.style.display = message ? 'block' : 'none';
  } catch (err) {
    document.getElementById('health').textContent = 'disconnected';
    const warning = document.getElementById('warning');
    warning.textContent = `Live status unavailable: ${err}`;
    warning.style.display = 'block';
  }
}
setInterval(refresh, 1000);
refresh();
</script>
</body>
</html>
"""


def _zone_editor_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Homebase Live Zone Editor</title>
<style>
:root { color-scheme: light; font-family: Arial, sans-serif; }
body { margin: 0; background: #f8fafc; color: #0f172a; }
header { padding: 14px 18px; background: #0f172a; color: white; }
main { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 14px; padding: 14px; }
.stage { position: relative; background: #111827; overflow: hidden; border: 1px solid #cbd5e1; }
#stream { display: block; max-width: 100%; width: 100%; height: auto; }
#draw { position: absolute; inset: 0; cursor: crosshair; }
.panel { background: white; border: 1px solid #cbd5e1; padding: 12px; }
label { display: block; font-size: 13px; margin: 10px 0 4px; color: #334155; }
input, select { width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #94a3b8; }
button { padding: 9px 10px; border: 1px solid #0f172a; background: #0f172a; color: white; cursor: pointer; }
button.secondary { background: white; color: #0f172a; }
button.danger { background: #991b1b; border-color: #991b1b; }
.row { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
#status { min-height: 20px; margin-top: 10px; font-size: 13px; color: #334155; }
#zones { font-size: 13px; max-height: 240px; overflow: auto; border-top: 1px solid #e2e8f0; margin-top: 12px; padding-top: 8px; }
.zone { display: flex; justify-content: space-between; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f1f5f9; }
.statuses { font-size: 13px; max-height: 180px; overflow: auto; border-top: 1px solid #e2e8f0; margin-top: 12px; padding-top: 8px; }
.status-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #f8fafc; }
@media (max-width: 900px) { main { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header><strong>Homebase Live Zone Editor</strong></header>
<main>
  <section class="stage" id="stage">
    <img id="stream" src="/stream.mjpg" alt="Live camera stream">
    <canvas id="draw"></canvas>
  </section>
  <aside class="panel">
    <label for="target">Save target</label>
    <select id="target">
      <option value="config" selected>Normal config/seats.json</option>
      <option value="demo">Demo seats file</option>
    </select>
    <label for="seatId">seat_id</label>
    <input id="seatId" value="seat_001">
    <label for="seatName">seat_name</label>
    <input id="seatName" value="Seat 1">
    <label><input id="enabled" type="checkbox" checked style="width:auto"> Enabled</label>
    <div class="row">
      <button id="save">Save polygon</button>
      <button class="secondary" id="undo">Undo point</button>
      <button class="secondary" id="clear">Clear</button>
    </div>
    <div class="row">
      <button class="secondary" id="baseline">Set empty baseline</button>
    </div>
    <div id="status"></div>
    <div id="currentStatus" class="statuses"></div>
    <div id="zones"></div>
  </aside>
</main>
<script>
const img = document.getElementById('stream');
const canvas = document.getElementById('draw');
const ctx = canvas.getContext('2d');
const stage = document.getElementById('stage');
let points = [];
let zones = [];

function resizeCanvas() {
  const rect = img.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width));
  canvas.height = Math.max(1, Math.round(rect.height));
  draw();
}

function toImagePoint(event) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = (img.naturalWidth || canvas.width) / rect.width;
  const scaleY = (img.naturalHeight || canvas.height) / rect.height;
  return [
    Math.round((event.clientX - rect.left) * scaleX),
    Math.round((event.clientY - rect.top) * scaleY)
  ];
}

function toCanvasPoint(point) {
  const scaleX = canvas.width / (img.naturalWidth || canvas.width);
  const scaleY = canvas.height / (img.naturalHeight || canvas.height);
  return [point[0] * scaleX, point[1] * scaleY];
}

function drawPolygon(poly, stroke, fill, close) {
  if (!poly.length) return;
  ctx.beginPath();
  const first = toCanvasPoint(poly[0]);
  ctx.moveTo(first[0], first[1]);
  for (const point of poly.slice(1)) {
    const p = toCanvasPoint(point);
    ctx.lineTo(p[0], p[1]);
  }
  if (close && poly.length >= 3) ctx.closePath();
  ctx.fillStyle = fill;
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 2;
  if (close && poly.length >= 3) ctx.fill();
  ctx.stroke();
  for (const point of poly) {
    const p = toCanvasPoint(point);
    ctx.beginPath();
    ctx.arc(p[0], p[1], 4, 0, Math.PI * 2);
    ctx.fillStyle = stroke;
    ctx.fill();
  }
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (const zone of zones) {
    drawPolygon(zone.polygon || [], '#16a34a', 'rgba(22, 163, 74, 0.14)', true);
  }
  drawPolygon(points, '#2563eb', 'rgba(37, 99, 235, 0.18)', false);
}

function setStatus(text) {
  document.getElementById('status').textContent = text;
}

async function loadZones() {
  try {
    const target = document.getElementById('target').value;
    const res = await fetch(`/api/zones?target=${encodeURIComponent(target)}`);
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    zones = data.zones || [];
    renderZones();
    draw();
  } catch (err) {
    setStatus(`Could not load zones: ${err}`);
  }
}

async function loadStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    const el = document.getElementById('currentStatus');
    const rows = data.current || [];
    const analysis = data.analysis || {};
    el.innerHTML = '<strong>Current status</strong>';
    const meta = document.createElement('div');
    meta.style.color = '#64748b';
    meta.style.margin = '4px 0 8px';
    meta.textContent = `analysis: ${analysis.last_run || 'never'} ${analysis.last_error ? '(' + analysis.last_error + ')' : ''}`;
    el.appendChild(meta);
    rows.forEach(row => {
      const div = document.createElement('div');
      div.className = 'status-row';
      const left = document.createElement('span');
      left.textContent = row.seat_id;
      const right = document.createElement('span');
      right.textContent = `${row.status} / ${Number(row.confidence || 0).toFixed(2)}`;
      div.append(left, right);
      el.appendChild(div);
    });
  } catch (err) {
    document.getElementById('currentStatus').textContent = `status unavailable: ${err}`;
  }
}

function renderZones() {
  const el = document.getElementById('zones');
  el.innerHTML = '<strong>Existing zones</strong>';
  zones.forEach((zone, idx) => {
    const row = document.createElement('div');
    row.className = 'zone';
    const name = document.createElement('span');
    name.textContent = `${zone.seat_id} (${(zone.polygon || []).length} pts)`;
    const actions = document.createElement('span');
    const edit = document.createElement('button');
    edit.className = 'secondary';
    edit.textContent = 'Load';
    edit.onclick = () => {
      points = (zone.polygon || []).map(p => [p[0], p[1]]);
      document.getElementById('seatId').value = zone.seat_id;
      document.getElementById('seatName').value = zone.seat_name || zone.seat_id;
      document.getElementById('enabled').checked = zone.enabled !== false;
      draw();
    };
    const del = document.createElement('button');
    del.className = 'danger';
    del.textContent = 'Delete';
    del.onclick = async () => {
      if (!window.confirm(`Delete ${zone.seat_id}?`)) return;
      try {
        const res = await fetch('/api/delete-zone', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({target: document.getElementById('target').value, seat_id: zone.seat_id})
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
        setStatus(`Deleted ${zone.seat_id}`);
        await loadZones();
      } catch (err) {
        setStatus(`Delete failed: ${err}`);
      }
    };
    actions.append(edit, del);
    row.append(name, actions);
    el.appendChild(row);
  });
}

canvas.addEventListener('click', event => {
  points.push(toImagePoint(event));
  draw();
});
document.getElementById('undo').onclick = () => { points.pop(); draw(); };
document.getElementById('clear').onclick = () => { points = []; draw(); };
document.getElementById('target').onchange = loadZones;
document.getElementById('baseline').onclick = async () => {
  if (!window.confirm('Use the current empty camera view as the detection baseline?')) return;
  try {
    const res = await fetch('/api/baseline', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}'
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    setStatus(data.message || 'Baseline saved.');
  } catch (err) {
    setStatus(`Baseline save failed: ${err}`);
  }
};
document.getElementById('save').onclick = async () => {
  if (points.length < 3) {
    setStatus('Draw at least three points.');
    return;
  }
  const payload = {
    target: document.getElementById('target').value,
    seat_id: document.getElementById('seatId').value,
    seat_name: document.getElementById('seatName').value,
    enabled: document.getElementById('enabled').checked,
    polygon: points
  };
  try {
    const res = await fetch('/api/zones', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const warnings = (data.warnings || []).join(' ');
    setStatus(`Saved ${payload.seat_id}${warnings ? '. ' + warnings : ''}`);
    await loadZones();
  } catch (err) {
    setStatus(`Save failed: ${err}`);
  }
};
img.onload = resizeCanvas;
window.addEventListener('resize', resizeCanvas);
setInterval(resizeCanvas, 1000);
setInterval(loadStatus, 1000);
loadZones();
loadStatus();
</script>
</body>
</html>
"""
