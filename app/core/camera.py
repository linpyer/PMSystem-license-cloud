from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import cv2


RESOLUTION_MAP: dict[str, tuple[int, int] | None] = {
    "original": None,
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}


@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str


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


def open_camera(camera_index: int) -> cv2.VideoCapture:
    if os.name == "nt":
        capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if capture.isOpened():
            return capture
        capture.release()
    return cv2.VideoCapture(camera_index)


def apply_capture_settings(capture: cv2.VideoCapture, config: dict[str, Any]) -> None:
    resolution = str(config.get("resolution", "original"))
    target_size = RESOLUTION_MAP.get(resolution)
    if target_size:
        width, height = target_size
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    fps = int(config.get("fps", 25) or 25)
    if fps > 0:
        capture.set(cv2.CAP_PROP_FPS, fps)


def get_capture_size(capture: cv2.VideoCapture, fallback: tuple[int, int] = (640, 480)) -> tuple[int, int]:
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        return fallback
    return width, height
