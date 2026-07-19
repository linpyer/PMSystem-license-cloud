from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np
import pytest

from app.core import camera
from app.core.ffmpeg_tools import inspect_ffmpeg_toolchain, resolve_ffmpeg_tool
from app.core.video_encoder import (
    COMPATIBILITY_MODE_MESSAGE,
    FFmpegH264Encoder,
    OpenCvCompatibilityEncoder,
    QUALITY_PROFILES,
    create_video_encoder,
    prepare_recording_frame,
    recording_output_size,
)
from app.core.recorder import RecordingWriterWorker, WatermarkRenderer
from app.core.config_manager import DEFAULT_CONFIG


class FakeCapture:
    def __init__(self, *, opened: bool = True, width: int = 1920, height: int = 1080, fps: float = 30.0):
        self.opened = opened
        self.width = width
        self.height = height
        self.fps = fps
        self.released = False
        self.set_calls: list[tuple[int, float]] = []
        self.frame = np.zeros((height, width, 3), dtype=np.uint8)

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def release(self) -> None:
        self.released = True

    def set(self, prop: int, value: float) -> bool:
        self.set_calls.append((prop, value))
        return True

    def get(self, prop: int) -> float:
        values = {
            cv2.CAP_PROP_FRAME_WIDTH: float(self.width),
            cv2.CAP_PROP_FRAME_HEIGHT: float(self.height),
            cv2.CAP_PROP_FPS: float(self.fps),
        }
        return values.get(prop, 0.0)

    def read(self) -> tuple[bool, np.ndarray]:
        return True, self.frame.copy()


def test_follow_camera_settings_do_not_force_resolution_or_fps() -> None:
    capture = FakeCapture()
    camera.apply_capture_settings(capture, {"resolution": "original", "fps": 0})
    requested_properties = {prop for prop, _value in capture.set_calls}
    assert cv2.CAP_PROP_FRAME_WIDTH not in requested_properties
    assert cv2.CAP_PROP_FRAME_HEIGHT not in requested_properties
    assert cv2.CAP_PROP_FPS not in requested_properties


def test_fixed_camera_settings_are_requested_explicitly() -> None:
    capture = FakeCapture()
    camera.apply_capture_settings(capture, {"resolution": "1080p", "fps": 60})
    assert (cv2.CAP_PROP_FRAME_WIDTH, 1920.0) in capture.set_calls
    assert (cv2.CAP_PROP_FRAME_HEIGHT, 1080.0) in capture.set_calls
    assert (cv2.CAP_PROP_FPS, 60.0) in capture.set_calls


def test_fixed_output_mismatch_is_not_silently_scaled_or_duplicated() -> None:
    with pytest.raises(camera.CameraParameterMismatch, match="1920×1080，30FPS"):
        camera._validate_requested_parameters(
            {"resolution": "1080p", "fps": 60},
            width=1920,
            height=1080,
            fps=30.0,
        )
    with pytest.raises(camera.CameraParameterMismatch, match="1920×1080，30FPS"):
        camera._validate_requested_parameters(
            {"resolution": "720p", "fps": 30},
            width=1920,
            height=1080,
            fps=30.0,
        )


def test_measured_fps_replaces_unreliable_camera_property() -> None:
    assert camera.select_effective_fps(0.0, 59.94) == pytest.approx(59.94)
    assert camera.select_effective_fps(60.0, 59.94) == pytest.approx(60.0)
    assert camera.select_effective_fps(60.0, 30.0) == pytest.approx(30.0)


def test_ivcam_backend_order_on_windows() -> None:
    if camera.os.name != "nt":
        pytest.skip("Windows capture backend test")
    assert camera.backend_candidates("e2eSoft iVCam")[:2] == [
        ("DirectShow", cv2.CAP_DSHOW),
        ("Media Foundation", cv2.CAP_MSMF),
    ]


def test_ivcam_falls_back_to_media_foundation_when_directshow_fails() -> None:
    if camera.os.name != "nt":
        pytest.skip("Windows capture backend test")
    opened_backends: list[int] = []

    def factory(_index: int, backend: int) -> FakeCapture:
        opened_backends.append(backend)
        return FakeCapture(opened=backend == cv2.CAP_MSMF)

    opened = camera.open_and_negotiate_camera(
        0,
        "iVCam",
        {"resolution": "original", "fps": 0},
        capture_factory=factory,
    )
    try:
        assert opened.negotiation.backend == "Media Foundation"
        assert opened_backends[:2] == [cv2.CAP_DSHOW, cv2.CAP_MSMF]
    finally:
        opened.capture.release()


def test_original_size_path_does_not_call_resize(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    def fail_resize(*_args, **_kwargs):
        raise AssertionError("unlimited original-size recording must not resize")

    monkeypatch.setattr(cv2, "resize", fail_resize)
    result = prepare_recording_frame(frame, 0)
    assert result is frame
    assert result.shape == frame.shape


def test_long_edge_limit_only_downscales() -> None:
    small = np.zeros((720, 1280, 3), dtype=np.uint8)
    assert prepare_recording_frame(small, 1920) is small
    large = np.zeros((2160, 3840, 3), dtype=np.uint8)
    limited = prepare_recording_frame(large, 1920)
    assert limited.shape == (1080, 1920, 3)
    assert recording_output_size(3840, 2160, 0) == (3840, 2160)


def test_preview_copy_cannot_modify_recording_source() -> None:
    source = np.full((720, 1280, 3), 127, dtype=np.uint8)
    record_frame = source.copy()
    preview_frame = source.copy()
    preview_frame[:] = 0
    assert np.all(source == 127)
    assert np.all(record_frame == 127)


def test_watermark_does_not_change_recording_dimensions() -> None:
    from datetime import datetime, timezone

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    rendered = WatermarkRenderer(28, 16).draw(frame.copy(), "TEST-ORDER", datetime.now(timezone.utc))
    assert rendered.shape == frame.shape


def test_writer_worker_flushes_queued_frames_before_close() -> None:
    import logging

    class MemoryEncoder:
        def __init__(self) -> None:
            self.frames: list[np.ndarray] = []
            self.closed = False

        def write(self, frame: np.ndarray) -> None:
            self.frames.append(frame.copy())

        def close(self) -> None:
            self.closed = True

    encoder = MemoryEncoder()
    worker = RecordingWriterWorker(encoder, logging.getLogger("test-recorder"), max_queue_size=20)
    for index in range(10):
        assert worker.enqueue(np.full((4, 4, 3), index, dtype=np.uint8)) is True
    worker.stop_and_wait()
    assert len(encoder.frames) == 10
    assert encoder.closed is True


def test_quality_profiles_match_product_settings() -> None:
    assert QUALITY_PROFILES == {
        "hd": (20, "veryfast"),
        "high": (18, "veryfast"),
        "source": (17, "veryfast"),
    }
    assert DEFAULT_CONFIG["fps"] == 0
    assert DEFAULT_CONFIG["recording_max_long_edge"] == 0
    assert DEFAULT_CONFIG["recording_video_quality"] == "source"


def test_compatibility_fallback_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import app.core.video_encoder as module

    class FailedFFmpeg:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("libx264 unavailable")

    class FakeFallback:
        def __init__(self, *_args, **_kwargs):
            pass

        def write(self, _frame):
            pass

        def close(self):
            pass

    monkeypatch.setattr(module, "FFmpegH264Encoder", FailedFFmpeg)
    monkeypatch.setattr(module, "OpenCvCompatibilityEncoder", FakeFallback)
    selection = create_video_encoder(tmp_path / "fallback.mp4", 1280, 720, 30)
    assert selection.compatibility_mode is True
    assert "mp4v" in selection.codec
    assert selection.fallback_reason == "libx264 unavailable"
    assert COMPATIBILITY_MODE_MESSAGE == "当前使用兼容录制模式，视频清晰度可能降低。"


def test_opencv_compatibility_encoder_keeps_dimensions_and_fps(tmp_path: Path) -> None:
    path = tmp_path / "compatibility.mp4"
    encoder = OpenCvCompatibilityEncoder(path, 640, 360, 25.0)
    for index in range(3):
        encoder.write(_synthetic_frame(640, 360, index))
    encoder.close()
    metadata = _probe_video(path)
    stream = metadata["streams"][0]
    assert stream["codec_name"] == "mpeg4"
    assert (stream["width"], stream["height"]) == (640, 360)
    assert float(Fraction(stream["avg_frame_rate"])) == pytest.approx(25.0)


def _synthetic_frame(width: int, height: int, frame_index: int) -> np.ndarray:
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = np.arange(width, dtype=np.uint16)[None, :] % 256
    frame[:, :, 1] = np.arange(height, dtype=np.uint16)[:, None] % 256
    frame[:, :, 2] = (frame_index * 31) % 256
    cv2.rectangle(frame, (20 + frame_index * 3, 20), (180 + frame_index * 3, 100), (255, 255, 255), -1)
    return frame


def _probe_video(path: Path) -> dict:
    ffprobe = resolve_ffmpeg_tool("ffprobe.exe")
    assert ffprobe is not None
    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("width", "height", "fps"),
    [
        (1280, 720, 30.0),
        (1920, 1080, 30.0),
        (1920, 1080, 60.0),
        (2560, 1440, 30.0),
        (2560, 1440, 60.0),
        (3840, 2160, 30.0),
    ],
)
def test_ffmpeg_h264_preserves_dynamic_dimensions_and_fps(
    tmp_path: Path,
    width: int,
    height: int,
    fps: float,
) -> None:
    toolchain = inspect_ffmpeg_toolchain()
    assert toolchain.has_libx264 is True
    path = tmp_path / f"synthetic-{width}x{height}-{fps:g}.mp4"
    frame_count = max(3, int(round(fps * 0.1)))
    encoder = FFmpegH264Encoder(path, width, height, fps, quality_profile="source")
    for index in range(frame_count):
        encoder.write(_synthetic_frame(width, height, index))
    encoder.close()

    assert path.stat().st_size > 0
    metadata = _probe_video(path)
    stream = metadata["streams"][0]
    probed_fps = float(Fraction(stream["avg_frame_rate"]))
    duration = float(metadata["format"]["duration"])
    assert stream["codec_name"] == "h264"
    assert stream["width"] == width
    assert stream["height"] == height
    assert probed_fps == pytest.approx(fps, rel=0.001)
    assert duration == pytest.approx(frame_count / fps, abs=max(0.04, 1.0 / fps))
    capture = cv2.VideoCapture(str(path))
    try:
        ok, decoded = capture.read()
        assert ok is True
        assert decoded is not None
        assert decoded.shape[:2] == (height, width)
    finally:
        capture.release()
