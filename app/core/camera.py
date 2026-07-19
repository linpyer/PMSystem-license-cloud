from __future__ import annotations

from dataclasses import dataclass
import math
import os
import statistics
import time
from typing import Any, Callable

import cv2
import numpy as np


RESOLUTION_MAP: dict[str, tuple[int, int] | None] = {
    "original": None,
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}
FOLLOW_CAMERA_FPS = 0.0
MIN_REASONABLE_FPS = 1.0
MAX_REASONABLE_FPS = 240.0


class CameraOpenError(RuntimeError):
    pass


class CameraParameterMismatch(CameraOpenError):
    pass


@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str


@dataclass(frozen=True)
class CameraNegotiation:
    backend: str
    width: int
    height: int
    fps: float
    property_width: int
    property_height: int
    property_fps: float
    measured_fps: float | None
    resolution_follows_camera: bool
    fps_follows_camera: bool


@dataclass
class OpenedCamera:
    capture: cv2.VideoCapture
    negotiation: CameraNegotiation


def list_camera_devices(fallback_count: int = 5) -> list[CameraDevice]:
    try:
        from PySide6.QtMultimedia import QMediaDevices

        devices = QMediaDevices.videoInputs()
        if devices:
            return [
                CameraDevice(index=index, name=device.description() or f"摄像头 {index}")
                for index, device in enumerate(devices)
            ]
    except Exception:
        pass

    return [CameraDevice(index=index, name=f"摄像头 {index}") for index in range(fallback_count)]


def is_ivcam(camera_name: str) -> bool:
    normalized = str(camera_name or "").strip().lower()
    return "ivcam" in normalized or "e2esoft" in normalized


def backend_candidates(camera_name: str = "") -> list[tuple[str, int]]:
    if os.name != "nt":
        return [("default", cv2.CAP_ANY)]
    if is_ivcam(camera_name):
        return [("DirectShow", cv2.CAP_DSHOW), ("Media Foundation", cv2.CAP_MSMF)]
    return [
        ("DirectShow", cv2.CAP_DSHOW),
        ("Media Foundation", cv2.CAP_MSMF),
        ("default", cv2.CAP_ANY),
    ]


def open_camera(camera_index: int, camera_name: str = "") -> cv2.VideoCapture:
    """Compatibility helper for callers that do not need negotiated metadata."""
    for _backend_name, backend in backend_candidates(camera_name):
        capture = cv2.VideoCapture(camera_index, backend)
        if capture.isOpened():
            return capture
        capture.release()
    return cv2.VideoCapture()


def requested_fps(config: dict[str, Any]) -> float | None:
    value = config.get("fps", FOLLOW_CAMERA_FPS)
    if value is None or (isinstance(value, str) and value.strip().lower() in {"camera", "follow", "original"}):
        return None
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return None
    return fps if fps > 0 else None


def requested_resolution(config: dict[str, Any]) -> tuple[int, int] | None:
    return RESOLUTION_MAP.get(str(config.get("resolution", "original") or "original"))


def apply_capture_settings(capture: cv2.VideoCapture, config: dict[str, Any]) -> None:
    try:
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    target_size = requested_resolution(config)
    if target_size is not None:
        width, height = target_size
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))

    target_fps = requested_fps(config)
    if target_fps is not None:
        capture.set(cv2.CAP_PROP_FPS, float(target_fps))


def is_trustworthy_fps(value: float | int | None) -> bool:
    try:
        fps = float(value or 0.0)
    except (TypeError, ValueError):
        return False
    return math.isfinite(fps) and MIN_REASONABLE_FPS <= fps <= MAX_REASONABLE_FPS


def measured_fps_from_timestamps(timestamps: list[float]) -> float | None:
    if len(timestamps) < 4:
        return None
    intervals = [later - earlier for earlier, later in zip(timestamps, timestamps[1:]) if later > earlier]
    if len(intervals) < 3:
        return None
    median_interval = statistics.median(intervals)
    if median_interval <= 0:
        return None
    measured = 1.0 / median_interval
    return measured if is_trustworthy_fps(measured) else None


def select_effective_fps(property_fps: float, measured_fps: float | None) -> float:
    property_valid = is_trustworthy_fps(property_fps)
    measured_valid = is_trustworthy_fps(measured_fps)
    if property_valid and measured_valid:
        assert measured_fps is not None
        difference_ratio = abs(float(property_fps) - measured_fps) / max(float(property_fps), measured_fps)
        if difference_ratio > 0.15:
            return float(measured_fps)
    if property_valid:
        return float(property_fps)
    return float(measured_fps or 0.0)


def _read_stable_frames(
    capture: cv2.VideoCapture,
    *,
    timeout_seconds: float = 4.0,
    stable_frame_count: int = 5,
    clock: Callable[[], float] = time.perf_counter,
    frame_validator: Callable[[np.ndarray], bool] | None = None,
) -> tuple[np.ndarray, float | None]:
    deadline = clock() + max(0.5, timeout_seconds)
    stable_shape: tuple[int, int, int] | None = None
    stable_count = 0
    timestamps: list[float] = []
    last_frame: np.ndarray | None = None

    while clock() < deadline:
        ok, frame = capture.read()
        captured_at = clock()
        if not ok or frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.size == 0:
            continue
        shape = tuple(int(part) for part in frame.shape)
        if shape[0] <= 1 or shape[1] <= 1 or shape[2] < 3:
            continue
        if frame_validator is not None and not frame_validator(frame):
            continue
        if shape != stable_shape:
            stable_shape = shape
            stable_count = 1
            timestamps = [captured_at]
        else:
            stable_count += 1
            timestamps.append(captured_at)
        last_frame = frame
        if stable_count >= stable_frame_count:
            return last_frame, measured_fps_from_timestamps(timestamps)

    raise CameraOpenError("摄像头打开后未能获得连续稳定的有效画面")


def _format_fps(fps: float) -> str:
    text = f"{fps:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def parameter_mismatch_message(width: int, height: int, fps: float) -> str:
    return (
        "摄像头实际输出参数与当前录制设置不一致。\n"
        f"当前实际输出：{width}×{height}，{_format_fps(fps)}FPS。\n"
        "请检查摄像头设置后重试，或改为“跟随摄像头输出”。"
    )


def _validate_requested_parameters(
    config: dict[str, Any],
    *,
    width: int,
    height: int,
    fps: float,
) -> None:
    target_size = requested_resolution(config)
    target_fps = requested_fps(config)
    resolution_matches = target_size is None or target_size == (width, height)
    fps_tolerance = max(0.75, (target_fps or fps) * 0.025)
    fps_matches = target_fps is None or abs(fps - target_fps) <= fps_tolerance
    if not resolution_matches or not fps_matches:
        raise CameraParameterMismatch(parameter_mismatch_message(width, height, fps))


def open_and_negotiate_camera(
    camera_index: int,
    camera_name: str,
    config: dict[str, Any],
    *,
    capture_factory: Callable[[int, int], cv2.VideoCapture] = cv2.VideoCapture,
    frame_validator: Callable[[np.ndarray], bool] | None = None,
) -> OpenedCamera:
    errors: list[str] = []
    mismatch: CameraParameterMismatch | None = None
    for backend_name, backend in backend_candidates(camera_name):
        capture = capture_factory(camera_index, backend)
        if not capture.isOpened():
            errors.append(f"{backend_name}: 无法打开")
            capture.release()
            continue
        try:
            apply_capture_settings(capture, config)
            frame, measured_fps = _read_stable_frames(capture, frame_validator=frame_validator)
            height, width = frame.shape[:2]
            property_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            property_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            property_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            actual_fps = select_effective_fps(property_fps, measured_fps)
            if not is_trustworthy_fps(actual_fps):
                raise CameraOpenError("无法确定摄像头实际帧率")
            _validate_requested_parameters(config, width=width, height=height, fps=actual_fps)
            return OpenedCamera(
                capture=capture,
                negotiation=CameraNegotiation(
                    backend=backend_name,
                    width=width,
                    height=height,
                    fps=actual_fps,
                    property_width=property_width,
                    property_height=property_height,
                    property_fps=property_fps,
                    measured_fps=measured_fps,
                    resolution_follows_camera=requested_resolution(config) is None,
                    fps_follows_camera=requested_fps(config) is None,
                ),
            )
        except CameraParameterMismatch as exc:
            mismatch = exc
            errors.append(f"{backend_name}: {exc}")
            capture.release()
        except Exception as exc:
            errors.append(f"{backend_name}: {exc}")
            capture.release()

    if mismatch is not None:
        raise mismatch
    detail = "; ".join(errors) or "没有可用采集后端"
    raise CameraOpenError(f"摄像头打开失败：{detail}")


def get_capture_size(capture: cv2.VideoCapture, fallback: tuple[int, int] = (640, 480)) -> tuple[int, int]:
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        return fallback
    return width, height
