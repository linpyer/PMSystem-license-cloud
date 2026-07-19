from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading
from typing import Protocol

import cv2
import numpy as np

from app.core.ffmpeg_tools import FFmpegUnavailableError, inspect_ffmpeg_toolchain


QUALITY_PROFILES: dict[str, tuple[int, str]] = {
    "hd": (20, "veryfast"),
    "high": (18, "veryfast"),
    "source": (17, "veryfast"),
}
DEFAULT_QUALITY_PROFILE = "source"
COMPATIBILITY_MODE_MESSAGE = "当前使用兼容录制模式，视频清晰度可能降低。"
ENCODING_OVERLOAD_MESSAGE = (
    "当前摄像头输出规格较高，电脑无法稳定完成视频编码。\n"
    "当前规格：{width}×{height}，{fps}FPS。\n"
    "请适当降低摄像头分辨率或帧率后重试。"
)


class VideoEncoder(Protocol):
    def write(self, frame: np.ndarray) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class EncoderSelection:
    encoder: VideoEncoder
    codec: str
    compatibility_mode: bool
    fallback_reason: str = ""


def format_fps(fps: float) -> str:
    return f"{float(fps):.6f}".rstrip("0").rstrip(".")


def recording_output_size(width: int, height: int, max_long_edge: int = 0) -> tuple[int, int]:
    width = int(width)
    height = int(height)
    if width <= 1 or height <= 1:
        raise ValueError("录制画面尺寸无效")
    if max_long_edge > 0 and max(width, height) > max_long_edge:
        scale = max_long_edge / max(width, height)
        width = max(2, int(round(width * scale)))
        height = max(2, int(round(height * scale)))
    width -= width % 2
    height -= height % 2
    return max(2, width), max(2, height)


def prepare_recording_frame(frame: np.ndarray, max_long_edge: int = 0) -> np.ndarray:
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("编码帧必须是 BGR24 三通道图像")
    source_height, source_width = frame.shape[:2]
    output_width, output_height = recording_output_size(source_width, source_height, max_long_edge)
    requires_scale = max_long_edge > 0 and max(source_width, source_height) > max_long_edge
    if requires_scale:
        return cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)
    if output_width != source_width or output_height != source_height:
        return frame[:output_height, :output_width]
    return frame


class FFmpegH264Encoder:
    def __init__(
        self,
        output_path: Path,
        width: int,
        height: int,
        fps: float,
        *,
        quality_profile: str = DEFAULT_QUALITY_PROFILE,
        close_timeout: float = 20.0,
    ) -> None:
        profile = quality_profile if quality_profile in QUALITY_PROFILES else DEFAULT_QUALITY_PROFILE
        crf, preset = QUALITY_PROFILES[profile]
        self.output_path = Path(output_path)
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)
        self.close_timeout = float(close_timeout)
        self._stderr_lines: deque[str] = deque(maxlen=80)
        self._closed = False

        toolchain = inspect_ffmpeg_toolchain()
        command = [
            str(toolchain.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-video_size",
            f"{self.width}x{self.height}",
            "-framerate",
            format_fps(self.fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(self.output_path),
        ]
        startupinfo = None
        creationflags = 0
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise FFmpegUnavailableError("FFmpeg H.264 编码器启动失败") from exc
        self._stderr_thread = threading.Thread(target=self._drain_stderr, name="FFmpegStderr", daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        if self._process.stderr is None:
            return
        for raw_line in iter(self._process.stderr.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                self._stderr_lines.append(line)

    def write(self, frame: np.ndarray) -> None:
        if self._closed or self._process.stdin is None:
            raise RuntimeError("FFmpeg 编码器已关闭")
        if frame.shape[:2] != (self.height, self.width) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(
                f"编码帧尺寸或格式变化：期望 {self.width}x{self.height} BGR24，"
                f"实际 {frame.shape[1]}x{frame.shape[0]}"
            )
        if self._process.poll() is not None:
            raise RuntimeError(self._error_message("FFmpeg 编码进程已异常退出"))
        try:
            self._process.stdin.write(np.ascontiguousarray(frame).tobytes())
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(self._error_message("FFmpeg 写入失败")) from exc

    def _error_message(self, prefix: str) -> str:
        detail = " | ".join(self._stderr_lines)
        return f"{prefix}：{detail}" if detail else prefix

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        try:
            return_code = self._process.wait(timeout=self.close_timeout)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                return_code = self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                return_code = self._process.wait(timeout=5)
        self._stderr_thread.join(timeout=2)
        if return_code != 0:
            raise RuntimeError(self._error_message(f"FFmpeg 结束失败（退出码 {return_code}）"))
        if not self.output_path.is_file() or self.output_path.stat().st_size <= 0:
            raise RuntimeError("FFmpeg 未生成有效视频文件")


class OpenCvCompatibilityEncoder:
    def __init__(self, output_path: Path, width: int, height: int, fps: float) -> None:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(str(output_path), fourcc, float(fps), (int(width), int(height)))
        if not self._writer.isOpened():
            self._writer.release()
            raise RuntimeError("兼容视频编码器不可用")

    def write(self, frame: np.ndarray) -> None:
        self._writer.write(frame)

    def close(self) -> None:
        self._writer.release()


def create_video_encoder(
    output_path: Path,
    width: int,
    height: int,
    fps: float,
    *,
    quality_profile: str = DEFAULT_QUALITY_PROFILE,
    allow_compatibility_fallback: bool = True,
) -> EncoderSelection:
    try:
        encoder = FFmpegH264Encoder(
            output_path,
            width,
            height,
            fps,
            quality_profile=quality_profile,
        )
        return EncoderSelection(encoder=encoder, codec="H.264", compatibility_mode=False)
    except (FFmpegUnavailableError, OSError, RuntimeError) as exc:
        if not allow_compatibility_fallback:
            raise
        fallback = OpenCvCompatibilityEncoder(output_path, width, height, fps)
        return EncoderSelection(
            encoder=fallback,
            codec="mp4v（兼容模式）",
            compatibility_mode=True,
            fallback_reason=str(exc),
        )
