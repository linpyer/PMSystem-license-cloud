from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2


@dataclass(frozen=True)
class VideoCheckResult:
    file_path: str
    exists: bool
    file_size: int
    duration_seconds: float
    frame_count: int
    is_playable: bool
    is_valid: bool
    message: str


class VideoChecker:
    def __init__(self, logger: logging.Logger | None = None, min_size_bytes: int = 1024) -> None:
        self.logger = logger
        self.min_size_bytes = min_size_bytes

    def check_video(self, file_path: str | Path) -> VideoCheckResult:
        path = Path(file_path)
        exists = path.exists()
        file_size = 0
        duration_seconds = 0.0
        frame_count = 0
        is_playable = False

        if not exists:
            return self._result(path, False, 0, 0.0, 0, False, "文件不存在")

        try:
            file_size = path.stat().st_size
        except OSError as exc:
            if self.logger:
                self.logger.exception("读取视频文件大小失败：%s", path)
            return self._result(path, True, 0, 0.0, 0, False, f"读取文件大小失败：{exc}")

        if file_size <= 0:
            return self._result(path, True, file_size, 0.0, 0, False, "文件大小为 0")

        capture = cv2.VideoCapture(str(path))
        try:
            is_playable = bool(capture.isOpened())
            if not is_playable:
                return self._result(path, True, file_size, 0.0, 0, False, "OpenCV 无法打开视频")

            frame_count_value = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            fps_value = capture.get(cv2.CAP_PROP_FPS)
            frame_count = max(0, int(frame_count_value or 0))
            fps = float(fps_value or 0)

            ok, _frame = capture.read()
            if not ok:
                return self._result(path, True, file_size, 0.0, frame_count, True, "无法读取视频首帧", False)

            if frame_count > 0 and fps > 0:
                duration_seconds = frame_count / fps

            if frame_count <= 0:
                return self._result(path, True, file_size, duration_seconds, frame_count, True, "无法读取到有效帧数")
            if duration_seconds <= 0:
                return self._result(path, True, file_size, duration_seconds, frame_count, True, "无法读取到有效时长")
            if file_size < self.min_size_bytes:
                return self._result(
                    path,
                    True,
                    file_size,
                    duration_seconds,
                    frame_count,
                    True,
                    "文件大小明显异常",
                    False,
                )

            return self._result(path, True, file_size, duration_seconds, frame_count, True, "视频校验通过")
        except Exception as exc:
            if self.logger:
                self.logger.exception("视频完整性校验异常：%s", path)
            return self._result(path, True, file_size, duration_seconds, frame_count, is_playable, f"校验异常：{exc}", False)
        finally:
            capture.release()

    def scan_unfinished_files(self, video_dir: str | Path) -> list[Path]:
        directory = Path(video_dir)
        if not directory.exists():
            return []

        patterns = [
            "*.recording.mp4",
            "*.recording.avi",
            "*.recording.mov",
            "*.temp.mp4",
            "*.temp.avi",
            "*.temp.mov",
            "*_temp.mp4",
            "*_temp.avi",
            "*_temp.mov",
        ]
        found: list[Path] = []
        for pattern in patterns:
            found.extend(directory.rglob(pattern))

        unique = sorted(set(found), key=self._mtime, reverse=True)
        if unique and self.logger:
            self.logger.warning("检测到未完成录制文件：%s", [str(path) for path in unique])
        return unique

    def _result(
        self,
        path: Path,
        exists: bool,
        file_size: int,
        duration_seconds: float,
        frame_count: int,
        is_playable: bool,
        message: str,
        is_valid: bool | None = None,
    ) -> VideoCheckResult:
        if is_valid is None:
            is_valid = exists and file_size > 0 and duration_seconds > 0 and frame_count > 0 and is_playable
        result = VideoCheckResult(
            file_path=str(path),
            exists=exists,
            file_size=file_size,
            duration_seconds=duration_seconds,
            frame_count=frame_count,
            is_playable=is_playable,
            is_valid=is_valid,
            message=message,
        )
        if self.logger:
            level = logging.INFO if is_valid else logging.WARNING
            self.logger.log(
                level,
                "视频完整性校验结果：path=%s, exists=%s, size=%s, duration=%.2f, frames=%s, playable=%s, valid=%s, message=%s",
                result.file_path,
                result.exists,
                result.file_size,
                result.duration_seconds,
                result.frame_count,
                result.is_playable,
                result.is_valid,
                result.message,
            )
        return result

    @staticmethod
    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0


# v1.0.2: extended validator used by recording, directory refresh, and query status.
# Kept at the end so older imports in this module continue to resolve to the expanded API.
from datetime import datetime

VALIDATION_UNCHECKED = "未校验"
VALIDATION_NORMAL = "正常"
VALIDATION_ERROR = "异常"
VALIDATION_MISSING = "文件不存在"
SHORT_VIDEO_WARNING = "视频时长过短"


@dataclass(frozen=True)
class VideoCheckResult:
    file_path: str
    exists: bool
    file_size: int
    duration_seconds: float
    frame_count: int
    is_playable: bool
    is_valid: bool
    message: str
    status: str = VALIDATION_UNCHECKED
    error: str = ""
    warning: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = "-"
    validated_at: str = ""


class VideoChecker:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        min_size_bytes: int = 0,
        min_valid_duration_seconds: float = 3.0,
    ) -> None:
        self.logger = logger
        self.min_size_bytes = max(0, int(min_size_bytes or 0))
        self.min_valid_duration_seconds = float(min_valid_duration_seconds or 3.0)

    def validate_video_file(self, file_path: str | Path) -> VideoCheckResult:
        return self.check_video(file_path)

    def check_video(self, file_path: str | Path) -> VideoCheckResult:
        path = Path(file_path)
        if self.logger:
            self.logger.info("视频完整性校验开始：%s", path)

        if not path.exists():
            return self._result(path, False, 0, 0.0, 0, False, "视频文件不存在", False, VALIDATION_MISSING)

        file_size = 0
        duration_seconds = 0.0
        frame_count = 0
        width = 0
        height = 0
        fps = 0.0
        codec = "-"
        is_playable = False

        try:
            file_size = int(path.stat().st_size)
        except OSError as exc:
            if self.logger:
                self.logger.exception("视频完整性校验异常：读取文件大小失败，file_path=%s", path)
            return self._result(
                path,
                True,
                0,
                0.0,
                0,
                False,
                f"读取视频文件大小失败：{exc}",
                False,
                VALIDATION_ERROR,
            )

        if file_size <= 0:
            return self._result(path, True, file_size, 0.0, 0, False, "视频文件大小为 0", False, VALIDATION_ERROR)

        capture = cv2.VideoCapture(str(path))
        try:
            is_playable = bool(capture.isOpened())
            if not is_playable:
                return self._result(path, True, file_size, 0.0, 0, False, "视频文件无法打开", False, VALIDATION_ERROR)

            frame_count = max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            codec = self._decode_fourcc(int(capture.get(cv2.CAP_PROP_FOURCC) or 0))

            ok, _frame = capture.read()
            if not ok:
                return self._result(
                    path,
                    True,
                    file_size,
                    0.0,
                    frame_count,
                    True,
                    "视频文件无法读取画面",
                    False,
                    VALIDATION_ERROR,
                    width=width,
                    height=height,
                    fps=fps,
                    codec=codec,
                )

            if frame_count <= 0:
                return self._result(
                    path,
                    True,
                    file_size,
                    0.0,
                    frame_count,
                    True,
                    "视频帧数为 0",
                    False,
                    VALIDATION_ERROR,
                    width=width,
                    height=height,
                    fps=fps,
                    codec=codec,
                )
            if width <= 0 or height <= 0:
                return self._result(
                    path,
                    True,
                    file_size,
                    0.0,
                    frame_count,
                    True,
                    "视频分辨率异常",
                    False,
                    VALIDATION_ERROR,
                    width=width,
                    height=height,
                    fps=fps,
                    codec=codec,
                )
            if fps <= 0:
                return self._result(
                    path,
                    True,
                    file_size,
                    0.0,
                    frame_count,
                    True,
                    "视频 FPS 异常",
                    False,
                    VALIDATION_ERROR,
                    width=width,
                    height=height,
                    fps=fps,
                    codec=codec,
                )

            duration_seconds = frame_count / fps
            if duration_seconds <= 0:
                return self._result(
                    path,
                    True,
                    file_size,
                    duration_seconds,
                    frame_count,
                    True,
                    "视频时长为 0",
                    False,
                    VALIDATION_ERROR,
                    width=width,
                    height=height,
                    fps=fps,
                    codec=codec,
                )

            warning = ""
            if 0 < duration_seconds < self.min_valid_duration_seconds:
                warning = SHORT_VIDEO_WARNING
                if self.logger:
                    self.logger.warning("视频时长过短：file_path=%s, duration=%.2f", path, duration_seconds)

            return self._result(
                path,
                True,
                file_size,
                duration_seconds,
                frame_count,
                True,
                "视频校验通过",
                True,
                VALIDATION_NORMAL,
                warning=warning,
                width=width,
                height=height,
                fps=fps,
                codec=codec,
            )
        except Exception as exc:
            if self.logger:
                self.logger.exception("视频完整性校验异常：%s", path)
            return self._result(
                path,
                True,
                file_size,
                duration_seconds,
                frame_count,
                is_playable,
                f"校验异常：{exc}",
                False,
                VALIDATION_ERROR,
                width=width,
                height=height,
                fps=fps,
                codec=codec,
            )
        finally:
            capture.release()

    def _result(
        self,
        path: Path,
        exists: bool,
        file_size: int,
        duration_seconds: float,
        frame_count: int,
        is_playable: bool,
        message: str,
        is_valid: bool | None = None,
        status: str | None = None,
        warning: str = "",
        width: int = 0,
        height: int = 0,
        fps: float = 0.0,
        codec: str = "-",
    ) -> VideoCheckResult:
        if status is None:
            status = VALIDATION_NORMAL if is_valid else VALIDATION_ERROR
        if is_valid is None:
            is_valid = status == VALIDATION_NORMAL and exists and file_size > 0 and duration_seconds > 0 and frame_count > 0 and is_playable
        error = "" if is_valid else message
        result = VideoCheckResult(
            file_path=str(path),
            exists=exists,
            file_size=file_size,
            duration_seconds=float(duration_seconds or 0.0),
            frame_count=int(frame_count or 0),
            is_playable=is_playable,
            is_valid=bool(is_valid),
            message=message,
            status=status,
            error=error,
            warning=warning,
            width=int(width or 0),
            height=int(height or 0),
            fps=float(fps or 0.0),
            codec=codec or "-",
            validated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        if self.logger:
            level = logging.INFO if result.is_valid else logging.WARNING
            self.logger.log(
                level,
                "视频完整性校验结果：path=%s, status=%s, valid=%s, error=%s, warning=%s, duration=%.2f, frames=%s, fps=%.2f, resolution=%sx%s, size=%s",
                result.file_path,
                result.status,
                result.is_valid,
                result.error,
                result.warning,
                result.duration_seconds,
                result.frame_count,
                result.fps,
                result.width,
                result.height,
                result.file_size,
            )
        return result

    def scan_unfinished_files(self, video_dir: str | Path) -> list[Path]:
        directory = Path(video_dir)
        if not directory.exists():
            return []

        patterns = [
            "*.recording.mp4",
            "*.recording.avi",
            "*.recording.mov",
            "*.temp.mp4",
            "*.temp.avi",
            "*.temp.mov",
            "*_temp.mp4",
            "*_temp.avi",
            "*_temp.mov",
        ]
        found: list[Path] = []
        for pattern in patterns:
            found.extend(directory.rglob(pattern))

        unique = sorted(set(found), key=self._mtime, reverse=True)
        if unique and self.logger:
            self.logger.warning("检测到未完成录制文件：%s", [str(path) for path in unique])
        return unique

    @staticmethod
    def _decode_fourcc(value: int) -> str:
        if not value:
            return "-"
        raw = "".join(chr((value >> (8 * index)) & 0xFF) for index in range(4)).strip("\x00 ").strip()
        return raw or "-"

    @staticmethod
    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0
