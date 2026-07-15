from __future__ import annotations

from pathlib import Path
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
from typing import Iterable

import numpy as np

from .config import resolve_path
from .state_engine import ZoneEvidence
from .zones import Zone, point_in_polygon


OBJECT_CLASSES = {
    "backpack",
    "handbag",
    "suitcase",
    "laptop",
    "book",
    "cell phone",
    "cup",
    "bottle",
    "umbrella",
}

COCO_NAMES = {
    0: "person",
    24: "backpack",
    25: "umbrella",
    26: "handbag",
    28: "suitcase",
    39: "bottle",
    41: "cup",
    63: "laptop",
    67: "cell phone",
    73: "book",
}


@dataclass
class YoloStatus:
    available: bool
    message: str


@dataclass(frozen=True)
class AsyncYoloResult:
    evidence: dict[str, ZoneEvidence]
    submitted_sequence: int
    submitted_diff_state: tuple[tuple[str, bool], ...]
    submitted_zone_signature: tuple[tuple[str, tuple[tuple[int, int], ...]], ...]
    generation: int
    elapsed_seconds: float


class YoloDetector:
    def __init__(self, *, enabled: bool, model_name: str = "data/models/yolov8n.onnx", interval_seconds: int = 8) -> None:
        self.enabled = bool(enabled)
        self.model_name = model_name
        self.interval_seconds = max(1, int(interval_seconds))
        self._last_run = 0.0
        self._model = None
        self._backend = ""
        self.status = YoloStatus(False, "YOLO is disabled.")

        if self.enabled:
            self._load_model()

    def should_run(self) -> bool:
        return self.enabled and self.status.available and (time.monotonic() - self._last_run) >= self.interval_seconds

    def detect(self, frame: np.ndarray, zones: Iterable[Zone], *, force: bool = False) -> dict[str, ZoneEvidence]:
        if not force and not self.should_run():
            return {}

        self._last_run = time.monotonic()
        if self._model is None:
            return {}

        zone_list = list(zones)
        evidence = {
            zone.seat_id: ZoneEvidence(person_checked=True, source="yolo")
            for zone in zone_list
        }
        if self._backend == "opencv-onnx":
            try:
                return self._detect_onnx(frame, zone_list, evidence)
            except Exception as exc:  # pragma: no cover - depends on optional model runtime
                self.status = YoloStatus(False, f"YOLO ONNX inference failed: {exc}")
                return {}

        try:
            results = self._model(frame, verbose=False)
        except Exception as exc:  # pragma: no cover - depends on optional model runtime
            self.status = YoloStatus(False, f"YOLO inference failed: {exc}")
            return {}

        names = getattr(self._model, "names", {}) or {}
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_idx = int(box.cls[0]) if getattr(box, "cls", None) is not None else -1
                label = str(names.get(cls_idx, cls_idx))
                confidence = float(box.conf[0]) if getattr(box, "conf", None) is not None else 0.0
                xyxy = box.xyxy[0].tolist()
                matched_zone = _best_zone_for_box(xyxy, zone_list)
                if matched_zone is not None and label == "person":
                    current = evidence[matched_zone.seat_id]
                    if confidence > current.person_confidence:
                        evidence[matched_zone.seat_id] = current.merge(
                            ZoneEvidence(
                                person_checked=True,
                                person_detected=True,
                                person_confidence=confidence,
                                source="yolo",
                                message="YOLO person matched to zone",
                            )
                        )
                elif matched_zone is not None and label in OBJECT_CLASSES:
                    current = evidence[matched_zone.seat_id]
                    if confidence > current.object_confidence:
                        evidence[matched_zone.seat_id] = current.merge(
                            ZoneEvidence(
                                object_detected=True,
                                object_confidence=confidence,
                                object_classes=[label],
                                source="yolo",
                                message="YOLO object matched to zone (diagnostic only)",
                            )
                        )

        return evidence

    def _load_model(self) -> None:
        model_path = Path(str(self.model_name))
        if model_path.suffix.lower() == ".onnx":
            self._load_onnx_model(model_path)
            return

        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            self.status = YoloStatus(
                False,
                "YOLO is enabled in settings, but ultralytics is not installed. "
                "Install the configured person detector before trusting occupancy status.",
            )
            return

        try:
            self._model = YOLO(self.model_name)
        except Exception as exc:  # pragma: no cover - optional dependency/model
            self.status = YoloStatus(False, f"Could not load YOLO model '{self.model_name}': {exc}")
            return

        self.status = YoloStatus(True, f"YOLO model loaded: {self.model_name}")

    def _load_onnx_model(self, model_path: Path) -> None:
        resolved = resolve_path(model_path)
        if not resolved.exists():
            self.status = YoloStatus(False, f"YOLO ONNX model was not found: {resolved}")
            return
        try:
            import cv2  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            self.status = YoloStatus(False, f"OpenCV is required for YOLO ONNX inference: {exc}")
            return

        try:
            # OpenCV's filename overload cannot open non-ASCII Windows paths.
            # Loading bytes also makes model access independent of path encoding.
            model_bytes = np.fromfile(resolved, dtype=np.uint8)
            net = cv2.dnn.readNetFromONNX(model_bytes)
            net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            cv2.setNumThreads(min(2, max(1, cv2.getNumberOfCPUs())))
        except Exception as exc:  # pragma: no cover - depends on model/runtime
            self.status = YoloStatus(False, f"Could not load YOLO ONNX model '{resolved}': {exc}")
            return

        self._model = net
        self._backend = "opencv-onnx"
        self.status = YoloStatus(True, f"YOLO ONNX model loaded with OpenCV DNN: {resolved}")

    def _detect_onnx(
        self,
        frame: np.ndarray,
        zones: list[Zone],
        evidence: dict[str, ZoneEvidence],
    ) -> dict[str, ZoneEvidence]:
        import cv2  # type: ignore

        input_size = 640
        image, scale, pad_x, pad_y = _letterbox(frame, input_size)
        blob = cv2.dnn.blobFromImage(image, scalefactor=1 / 255.0, size=(input_size, input_size), swapRB=True)
        self._model.setInput(blob)
        output = self._model.forward()
        predictions = np.asarray(output)
        if predictions.ndim == 3:
            predictions = predictions[0]
        if predictions.shape[0] < predictions.shape[-1]:
            predictions = predictions.T

        boxes: list[list[int]] = []
        confidences: list[float] = []
        class_ids: list[int] = []
        height, width = frame.shape[:2]
        for row in predictions:
            scores = row[4:]
            if scores.size == 0:
                continue
            class_id = int(np.argmax(scores))
            confidence = float(scores[class_id])
            if confidence < 0.25:
                continue
            label = COCO_NAMES.get(class_id, str(class_id))
            if label != "person" and label not in OBJECT_CLASSES:
                continue
            cx, cy, box_w, box_h = [float(value) for value in row[:4]]
            x1 = (cx - box_w / 2 - pad_x) / scale
            y1 = (cy - box_h / 2 - pad_y) / scale
            x2 = (cx + box_w / 2 - pad_x) / scale
            y2 = (cy + box_h / 2 - pad_y) / scale
            x1 = max(0, min(width - 1, x1))
            y1 = max(0, min(height - 1, y1))
            x2 = max(0, min(width - 1, x2))
            y2 = max(0, min(height - 1, y2))
            boxes.append([int(x1), int(y1), int(max(1, x2 - x1)), int(max(1, y2 - y1))])
            confidences.append(confidence)
            class_ids.append(class_id)

        keep = cv2.dnn.NMSBoxes(boxes, confidences, score_threshold=0.25, nms_threshold=0.45)
        for index in np.asarray(keep).reshape(-1):
            x, y, box_w, box_h = boxes[int(index)]
            confidence = confidences[int(index)]
            label = COCO_NAMES.get(class_ids[int(index)], str(class_ids[int(index)]))
            xyxy = (x, y, x + box_w, y + box_h)
            matched_zone = _best_zone_for_box(xyxy, zones)
            if matched_zone is not None and label == "person":
                current = evidence[matched_zone.seat_id]
                if confidence > current.person_confidence:
                    evidence[matched_zone.seat_id] = current.merge(
                        ZoneEvidence(
                            person_checked=True,
                            person_detected=True,
                            person_confidence=confidence,
                            source="yolo",
                            message="YOLO ONNX person matched to zone",
                        )
                    )
            elif matched_zone is not None and label in OBJECT_CLASSES:
                current = evidence[matched_zone.seat_id]
                if confidence > current.object_confidence:
                    evidence[matched_zone.seat_id] = current.merge(
                        ZoneEvidence(
                            object_detected=True,
                            object_confidence=confidence,
                            object_classes=[label],
                            source="yolo",
                            message="YOLO ONNX object matched to zone (diagnostic only)",
                        )
                    )
        return evidence


class AsyncYoloDetector:
    """Runs one latest-frame YOLO inference without blocking diff analysis."""

    def __init__(self, detector: YoloDetector) -> None:
        self.detector = detector
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="homebase-yolo")
        self._future: Future[AsyncYoloResult] | None = None
        self._lock = threading.Lock()
        self._last_submit_monotonic = 0.0
        self._last_elapsed_seconds = 0.0
        self._last_error = ""
        self._generation = 0

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._future is not None and not self._future.done()

    @property
    def last_elapsed_seconds(self) -> float:
        with self._lock:
            return self._last_elapsed_seconds

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def submit(
        self,
        frame: np.ndarray,
        zones: Iterable[Zone],
        *,
        sequence: int,
        diff_state: dict[str, bool],
        urgent: bool = False,
    ) -> bool:
        if not self.detector.enabled or not self.detector.status.available:
            return False
        now = time.monotonic()
        with self._lock:
            if self._future is not None and not self._future.done():
                return False
            if not urgent and now - self._last_submit_monotonic < self.detector.interval_seconds:
                return False
            zone_list = list(zones)
            state_items = tuple(sorted((str(key), bool(value)) for key, value in diff_state.items()))
            zone_signature = _zone_signature(zone_list)
            frame_copy = np.asarray(frame).copy()
            self._last_submit_monotonic = now
            self._future = self._executor.submit(
                self._run,
                frame_copy,
                zone_list,
                int(sequence),
                state_items,
                zone_signature,
                self._generation,
            )
            return True

    def poll(self) -> AsyncYoloResult | None:
        with self._lock:
            future = self._future
            if future is None or not future.done():
                return None
            self._future = None
        try:
            result = future.result()
        except Exception as exc:  # pragma: no cover - defensive executor boundary
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            return None
        with self._lock:
            if result.generation != self._generation:
                return None
            self._last_elapsed_seconds = result.elapsed_seconds
            self._last_error = ""
        return result

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def invalidate(self) -> None:
        """Discard results submitted before a baseline or configuration reset."""
        with self._lock:
            self._generation += 1

    def _run(
        self,
        frame: np.ndarray,
        zones: list[Zone],
        sequence: int,
        diff_state: tuple[tuple[str, bool], ...],
        zone_signature: tuple[tuple[str, tuple[tuple[int, int], ...]], ...],
        generation: int,
    ) -> AsyncYoloResult:
        started = time.monotonic()
        evidence = self.detector.detect(frame, zones, force=True)
        return AsyncYoloResult(
            evidence=evidence,
            submitted_sequence=sequence,
            submitted_diff_state=diff_state,
            submitted_zone_signature=zone_signature,
            generation=generation,
            elapsed_seconds=time.monotonic() - started,
        )


def _zone_signature(zones: Iterable[Zone]) -> tuple[tuple[str, tuple[tuple[int, int], ...]], ...]:
    return tuple(sorted((zone.seat_id, tuple(zone.polygon)) for zone in zones))


def _letterbox(frame: np.ndarray, size: int) -> tuple[np.ndarray, float, float, float]:
    import cv2  # type: ignore

    height, width = frame.shape[:2]
    scale = min(size / width, size / height)
    new_width, new_height = int(round(width * scale)), int(round(height * scale))
    resized = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x = (size - new_width) // 2
    pad_y = (size - new_height) // 2
    canvas[pad_y : pad_y + new_height, pad_x : pad_x + new_width] = resized[:, :, :3]
    return canvas, scale, float(pad_x), float(pad_y)


def _best_zone_for_box(box: Iterable[float], zones: Iterable[Zone]) -> Zone | None:
    values = [float(value) for value in box]
    if len(values) < 4:
        return None
    x1, y1, x2, y2 = values[:4]
    if x2 <= x1 or y2 <= y1:
        return None
    width = x2 - x1
    height = y2 - y1
    anchors = (
        ((x1 + x2) / 2, (y1 + y2) / 2),
        ((x1 + x2) / 2, y1 + height * 0.72),
        ((x1 + x2) / 2, y1 + height * 0.88),
    )

    best: tuple[float, Zone] | None = None
    for zone in zones:
        xs = [float(point[0]) for point in zone.polygon]
        ys = [float(point[1]) for point in zone.polygon]
        if not xs or not ys:
            continue
        zx1, zy1, zx2, zy2 = min(xs), min(ys), max(xs), max(ys)
        intersection = max(0.0, min(x2, zx2) - max(x1, zx1)) * max(0.0, min(y2, zy2) - max(y1, zy1))
        zone_area = max(1.0, (zx2 - zx1) * (zy2 - zy1))
        overlap_score = intersection / zone_area
        anchor_score = sum(1.0 for anchor in anchors if point_in_polygon(anchor, zone.polygon))
        score = anchor_score + overlap_score
        if score < 0.15:
            continue
        if best is None or score > best[0]:
            best = (score, zone)
    return best[1] if best is not None else None
