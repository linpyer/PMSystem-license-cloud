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
