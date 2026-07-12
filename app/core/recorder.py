from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QThread, Signal

from app.core.camera import apply_capture_settings, get_capture_size, list_camera_devices, open_camera
from app.core.database import DatabaseManager
from app.core.database_paths import database_path
from app.core.disk_space_checker import DiskSpaceChecker
from app.core.file_hash import calculate_file_hash, normalize_hash_algorithm
from app.core.video_checker import VideoChecker
from app.utils.filename import unique_temp_recording_path, unique_video_path
from app.utils.time_utils import format_datetime


CAMERA_FAIL_LIMIT_IDLE = 8
CAMERA_FAIL_LIMIT_RECORDING = 5
CAMERA_FAIL_SECONDS_IDLE = 2.0
CAMERA_FAIL_SECONDS_RECORDING = 1.5
CAMERA_RECOVER_SUCCESS_LIMIT = 8
CAMERA_RECOVER_SECONDS = 1.0
FRAME_FREEZE_SECONDS = 6.0
FRAME_FREEZE_DIFF_THRESHOLD = 1.2
IVCAM_WAIT_MATCH_LIMIT = 5
IVCAM_PLACEHOLDER_MATCH_LIMIT = 5
IVCAM_PLACEHOLDER_MIN_SECONDS = 1.5
IVCAM_PLACEHOLDER_CHECK_INTERVAL = 0.35
DISK_WARNING_GB = 2.0
DISK_CRITICAL_GB = 0.5
DISK_CHECK_INTERVAL_SECONDS = 6.0
FILE_GROWTH_CHECK_INTERVAL_SECONDS = 5.0
FILE_STALL_LIMIT = 3


class WatermarkRenderer:
    def __init__(self, font_size: int, margin: int) -> None:
        self.font_size = font_size
        self.margin = margin
        self.font = self._load_font(font_size)
        self._label_cache: dict[str, np.ndarray] = {}

    def update(self, font_size: int, margin: int) -> None:
        if font_size != self.font_size:
            self.font = self._load_font(font_size)
            self._label_cache.clear()
        self.font_size = font_size
        self.margin = margin

    def draw(self, frame: np.ndarray, order_id: str, current_time: datetime) -> np.ndarray:
        order_text = f"单号：{order_id}"
        time_text = format_datetime(current_time)

        order_label = self._label_image(order_text)
        time_label = self._label_image(time_text)
        self._blend_label(frame, order_label, self.margin, self.margin)
        bottom_y = max(self.margin, frame.shape[0] - self.margin - time_label.shape[0])
        self._blend_label(frame, time_label, self.margin, bottom_y)
        return frame

    def _label_image(self, text: str) -> np.ndarray:
        cached = self._label_cache.get(text)
        if cached is not None:
            return cached

        padding_x = 8
        padding_y = 6
        probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
        box = draw.textbbox((0, 0), text, font=self.font)
        width = max(1, box[2] - box[0] + padding_x * 2)
        height = max(1, box[3] - box[1] + padding_y * 2)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width, height), fill=(0, 0, 0, 128))
        draw.text((padding_x - box[0], padding_y - box[1]), text, font=self.font, fill=(255, 255, 255, 255))
        label = np.array(image)
        if len(self._label_cache) > 128:
            self._label_cache.clear()
        self._label_cache[text] = label
        return label

    @staticmethod
    def _blend_label(frame: np.ndarray, label: np.ndarray, x: int, y: int) -> None:
        height, width = label.shape[:2]
        frame_height, frame_width = frame.shape[:2]
        if x >= frame_width or y >= frame_height:
            return
        width = min(width, frame_width - x)
        height = min(height, frame_height - y)
        if width <= 0 or height <= 0:
            return

        overlay = label[:height, :width]
        alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
        overlay_bgr = overlay[:, :, :3][:, :, ::-1].astype(np.float32)
        target = frame[y : y + height, x : x + width].astype(np.float32)
        blended = overlay_bgr * alpha + target * (1.0 - alpha)
        frame[y : y + height, x : x + width] = blended.astype(np.uint8)

    @staticmethod
    def _load_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/msyh.ttf"),
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("C:/Windows/Fonts/simsun.ttc"),
        ]
        for font_path in candidates:
            if font_path.exists():
                try:
                    return ImageFont.truetype(str(font_path), font_size)
                except OSError:
                    continue
        return ImageFont.load_default()


class RecordingWriterWorker:
    def __init__(self, writer: cv2.VideoWriter, logger: logging.Logger, max_queue_size: int) -> None:
        self.writer = writer
        self.logger = logger
        self.queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=max_queue_size)
        self.stop_requested = threading.Event()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name="RecordingWriterWorker", daemon=True)
        self.frames_written = 0
        self.frames_dropped = 0
        self.write_time_sum = 0.0
        self.write_time_count = 0
        self.write_time_max = 0.0
        self.error: Exception | None = None
        self.thread.start()

    def enqueue(self, frame: np.ndarray) -> bool:
        if self.error is not None:
            return False
        try:
            self.queue.put_nowait(frame)
            return True
        except queue.Full:
            try:
                self.queue.get_nowait()
                with self.lock:
                    self.frames_dropped += 1
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(frame)
                return True
            except queue.Full:
                with self.lock:
                    self.frames_dropped += 1
                return False

    def stop_and_wait(self) -> None:
        self.stop_requested.set()
        try:
            self.queue.put(None, timeout=2)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            self.queue.put(None, timeout=2)
        self.thread.join()

    def snapshot(self, reset_window: bool = False) -> dict[str, float | int | str]:
        with self.lock:
            write_count = self.write_time_count
            avg_write_ms = (self.write_time_sum / write_count * 1000) if write_count else 0.0
            result: dict[str, float | int | str] = {
                "queue_size": self.queue.qsize(),
                "frames_written": self.frames_written,
                "frames_dropped": self.frames_dropped,
                "avg_write_ms": avg_write_ms,
                "max_write_ms": self.write_time_max * 1000,
                "error": str(self.error or ""),
            }
            if reset_window:
                self.write_time_sum = 0.0
                self.write_time_count = 0
                self.write_time_max = 0.0
            return result

    def _run(self) -> None:
        while True:
            frame = self.queue.get()
            if frame is None:
                break
            start = time.perf_counter()
            try:
                self.writer.write(frame)
            except Exception as exc:
                self.error = exc
                self.logger.exception("视频写入线程失败")
                break
            elapsed = time.perf_counter() - start
            with self.lock:
                self.frames_written += 1
                self.write_time_sum += elapsed
                self.write_time_count += 1
                self.write_time_max = max(self.write_time_max, elapsed)

        while True:
            try:
                frame = self.queue.get_nowait()
            except queue.Empty:
                break
            if frame is None:
                continue
            start = time.perf_counter()
            try:
                self.writer.write(frame)
            except Exception as exc:
                self.error = exc
                self.logger.exception("视频写入线程 flush 失败")
                break
            elapsed = time.perf_counter() - start
            with self.lock:
                self.frames_written += 1
                self.write_time_sum += elapsed
                self.write_time_count += 1
                self.write_time_max = max(self.write_time_max, elapsed)

        self.writer.release()


class RecorderThread(QThread):
    frame_ready = Signal(object)
    camera_status_changed = Signal(bool, str)
    recording_state_changed = Signal(bool, str, str)
    duration_changed = Signal(int)
    message = Signal(str)
    warning_message = Signal(str)
    critical_message = Signal(str)

    def __init__(
        self,
        config: dict[str, Any],
        base_dir: Path,
        logger: logging.Logger,
        db_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.config = dict(config)
        self.base_dir = Path(base_dir)
        self.database_path = Path(db_path) if db_path is not None else database_path(self.base_dir)
        self.logger = logger

        self._commands: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._stop_requested = threading.Event()

        self._capture: cv2.VideoCapture | None = None
        self._writer: cv2.VideoWriter | None = None
        self._writer_worker: RecordingWriterWorker | None = None
        self._writer_size: tuple[int, int] | None = None
        self._temp_path: Path | None = None
        self._recording = False
        self._order_id = ""
        self._start_time: datetime | None = None
        self._last_frame_size: tuple[int, int] | None = None
        self._pending_start_order_id: str | None = None
        self._frames_written = 0
        self._frames_enqueued = 0
        self._record_type_for_current_recording = str(self.config.get("current_record_type") or "发货")
        self._target_recording_fps = int(self.config.get("fps", 25) or 25)
        self._effective_recording_fps = self._target_recording_fps
        self._camera_actual_fps: float | None = None
        self._next_record_frame_at = 0.0
        self._next_preview_frame_at = 0.0
        self._record_interval = 1.0 / max(1, self._target_recording_fps)
        self._perf_last_log = time.perf_counter()
        self._perf_capture_count = 0
        self._perf_capture_time_sum = 0.0
        self._perf_watermark_time_sum = 0.0
        self._perf_watermark_count = 0
        self._perf_enqueue_time_sum = 0.0
        self._perf_enqueue_count = 0
        self._perf_preview_time_sum = 0.0
        self._perf_preview_count = 0
        self._perf_last_drop_count = 0
        self._video_checker = VideoChecker(logger)
        self._preview_watermark_logged = False
        self._watermark_error_logged = False
        self._camera_fail_count = 0
        self._last_frame_ok_at = time.perf_counter()
        self._last_camera_issue_log_at = 0.0
        self._last_freeze_warning_log_at = 0.0
        self._camera_available = False
        self._camera_last_error = "摄像头尚未就绪"
        self._camera_unhealthy_since = time.perf_counter()
        self._camera_confirmed_error = False
        self._camera_pending_error_since = 0.0
        self._camera_pending_recover_since = 0.0
        self._camera_success_count = 0
        self._last_camera_status_available: bool | None = None
        self._last_camera_status_message = ""
        self._last_camera_status_at = 0.0
        self._last_disk_check_at = 0.0
        self._last_file_growth_check_at = 0.0
        self._last_recording_file_size = 0
        self._last_file_growth_frame_count = 0
        self._file_stall_count = 0
        self._freeze_sample_at = 0.0
        self._freeze_started_at = 0.0
        self._last_freeze_sample: np.ndarray | None = None
        self._ivcam_camera = False
        self._ivcam_wait_matches = 0
        self._ivcam_waiting = False
        self._ivcam_placeholder_type = ""
        self._ivcam_placeholder_message = ""
        self._ivcam_placeholder_metrics: dict[str, float] = {}
        self._ivcam_placeholder_first_match_at = 0.0
        self._ivcam_placeholder_last_check_at = 0.0
        self._ivcam_placeholder_last_log_at = 0.0
        self._camera_state = "normal"
        self._camera_error_started_at = 0.0
        self._camera_recover_started_at = 0.0
        self._frame_frozen = False
        self._recording_error_reason: str | None = None

        self._watermark = WatermarkRenderer(
            int(self.config.get("watermark_font_size", 28) or 28),
            int(self.config.get("watermark_margin", 16) or 16),
        )

    def scan(self, order_id: str) -> None:
        self._commands.put(("scan", order_id))

    def manual_start(self, order_id: str) -> None:
        self._commands.put(("manual_start", order_id))

    def manual_stop(self) -> None:
        self._commands.put(("manual_stop", None))

    def restart_camera(self) -> None:
        self._commands.put(("restart_camera", None))

    def camera_health(self) -> dict[str, Any]:
        now_perf = time.perf_counter()
        elapsed = now_perf - self._last_frame_ok_at
        capture_ok = self._capture is not None and self._capture.isOpened()
        reason = str(self._camera_last_error or "").strip()
        is_healthy = bool(capture_ok and self._camera_available and not self._camera_confirmed_error)
        error_type = ""

        if not capture_ok:
            reason = reason or "摄像头不可用"
        elif self._camera_confirmed_error:
            error_type = self._ivcam_placeholder_type or ("ivcam_waiting" if self._ivcam_waiting else "camera_lost")
            reason = reason or "摄像头连接异常，请检查 iVCam 或摄像头"
        elif not self._camera_available:
            reason = reason or "摄像头画面尚未就绪"
        elif elapsed >= self._camera_fail_seconds():
            is_healthy = False
            reason = "摄像头连接异常，请检查 iVCam 或摄像头"
        elif self._ivcam_waiting:
            is_healthy = False
            error_type = self._ivcam_placeholder_type or "ivcam_waiting"
            reason = self._ivcam_placeholder_message or "摄像头连接异常，请检查 iVCam"

        confirmed_ivcam_waiting = bool(self._camera_confirmed_error and self._ivcam_waiting)
        confirmed_ivcam_placeholder = bool(
            self._camera_confirmed_error and self._ivcam_placeholder_type == "ivcam_placeholder"
        )
        return {
            "is_healthy": is_healthy,
            "is_available": bool(capture_ok and self._camera_available),
            "is_error": bool(self._camera_confirmed_error),
            "error_type": error_type if self._camera_confirmed_error else "",
            "error_message": reason if self._camera_confirmed_error else "",
            "last_frame_elapsed": elapsed,
            "last_error": reason,
            "is_ivcam_waiting": confirmed_ivcam_waiting,
            "is_ivcam_placeholder": confirmed_ivcam_placeholder,
            "is_frozen": self._frame_frozen,
            "camera_fail_count": self._camera_fail_count,
            "consecutive_fail_count": self._camera_fail_count,
            "consecutive_success_count": self._camera_success_count,
            "pending_error_since": self._camera_pending_error_since,
            "pending_recover_since": self._camera_pending_recover_since,
            "placeholder_hit_count": self._ivcam_wait_matches,
        }

    def _emit_camera_status(self, available: bool, message: str, *, force: bool = False) -> None:
        message = str(message or ("摄像头正常" if available else "摄像头连接异常，请检查 iVCam 或摄像头")).strip()
        now_perf = time.perf_counter()
        duplicate = (
            self._last_camera_status_available == available
            and self._last_camera_status_message == message
            and now_perf - self._last_camera_status_at < 1.0
        )
        if duplicate and not force:
            return
        self._last_camera_status_available = available
        self._last_camera_status_message = message
        self._last_camera_status_at = now_perf
        self.camera_status_changed.emit(available, message)

    def _set_camera_state(self, state: str, *, error_type: str = "", reason: str = "") -> None:
        state = str(state or "normal").strip()
        if state == self._camera_state:
            return
        now_perf = time.perf_counter()
        old_state = self._camera_state
        error_duration = now_perf - self._camera_error_started_at if self._camera_error_started_at > 0 else 0.0
        recover_duration = now_perf - self._camera_recover_started_at if self._camera_recover_started_at > 0 else 0.0
        if state == "error":
            self._camera_error_started_at = now_perf
            self._camera_recover_started_at = 0.0
            error_duration = 0.0
        elif state == "recovering":
            self._camera_recover_started_at = now_perf
            recover_duration = 0.0
        elif state == "normal":
            self._camera_error_started_at = 0.0
            self._camera_recover_started_at = 0.0
        self._camera_state = state
        self.logger.info(
            "camera_state: %s -> %s error_type=%s hit_count=%s normal_frame_count=%s "
            "error_duration=%.2f recover_duration=%.2f reason=%s",
            old_state,
            state,
            error_type or self._ivcam_placeholder_type or "",
            self._ivcam_wait_matches,
            self._camera_success_count,
            error_duration,
            recover_duration,
            reason or self._camera_last_error or "",
        )

    def _camera_fail_limit(self) -> int:
        return CAMERA_FAIL_LIMIT_RECORDING if self._recording else CAMERA_FAIL_LIMIT_IDLE

    def _camera_fail_seconds(self) -> float:
        return CAMERA_FAIL_SECONDS_RECORDING if self._recording else CAMERA_FAIL_SECONDS_IDLE

    def _confirm_camera_error(self, reason: str, *, force: bool = False) -> None:
        reason = str(reason or "摄像头连接异常，请检查 iVCam 或摄像头").strip()
        was_error = self._camera_confirmed_error
        now_perf = time.perf_counter()
        error_type = self._ivcam_placeholder_type or ("ivcam_waiting" if self._ivcam_waiting else "read_failed")
        self._camera_confirmed_error = True
        self._camera_available = False
        self._camera_last_error = reason
        self._camera_success_count = 0
        self._camera_pending_recover_since = 0.0
        if self._camera_unhealthy_since <= 0:
            self._camera_unhealthy_since = now_perf
        self._set_camera_state("error", error_type=error_type, reason=reason)
        if not was_error or force:
            elapsed = now_perf - self._last_frame_ok_at
            self.logger.error(
                "camera_state=error reason=%s error_type=%s fail_count=%s placeholder_hit_count=%s "
                "last_valid_elapsed=%.2f recording=%s",
                reason,
                error_type,
                self._camera_fail_count,
                self._ivcam_wait_matches,
                elapsed,
                self._recording,
            )
            self._emit_camera_status(False, reason, force=True)

    def _maybe_confirm_camera_error(self, reason: str) -> bool:
        elapsed = time.perf_counter() - self._last_frame_ok_at
        if self._camera_fail_count >= self._camera_fail_limit() or elapsed >= self._camera_fail_seconds():
            self._confirm_camera_error(reason)
            return True
        return False

    def _confirm_camera_recovered(self, *, force: bool = False) -> None:
        was_error = self._camera_confirmed_error or not self._camera_available
        self._camera_confirmed_error = False
        self._camera_available = True
        self._camera_last_error = ""
        self._camera_unhealthy_since = 0.0
        self._camera_pending_error_since = 0.0
        self._camera_pending_recover_since = 0.0
        self._frame_frozen = False
        self._ivcam_waiting = False
        self._ivcam_wait_matches = 0
        self._ivcam_placeholder_type = ""
        self._ivcam_placeholder_message = ""
        self._ivcam_placeholder_metrics = {}
        self._ivcam_placeholder_first_match_at = 0.0
        self._ivcam_placeholder_last_check_at = 0.0
        self._ivcam_placeholder_last_log_at = 0.0
        if was_error or force:
            self._set_camera_state("normal", error_type="recovered", reason="摄像头已恢复")
            self.logger.info(
                "camera_state=healthy reason=recovered success_count=%s recording=%s",
                self._camera_success_count,
                self._recording,
            )
            self._emit_camera_status(True, "摄像头已恢复", force=True)

    def update_config(self, config: dict[str, Any]) -> None:
        self._commands.put(("update_config", dict(config)))

    def stop_thread(self) -> None:
        self._stop_requested.set()
        self._commands.put(("noop", None))

    def run(self) -> None:
        self._open_camera()
        last_duration = -1

        while not self._stop_requested.is_set():
            self._drain_commands()

            if self._capture is None or not self._capture.isOpened():
                self._handle_capture_unavailable()
                time.sleep(0.05)
                continue

            capture_started = time.perf_counter()
            ok, frame = self._capture.read()
            capture_elapsed = time.perf_counter() - capture_started
            self._perf_capture_count += 1
            self._perf_capture_time_sum += capture_elapsed
            if not ok or frame is None:
                self._handle_camera_read_failure()
                time.sleep(0.3)
                continue
            if not self.is_valid_camera_frame(frame):
                self._handle_camera_read_failure()
                time.sleep(0.3)
                continue

            self._handle_camera_frame_ok(frame)
            self._last_frame_size = (frame.shape[1], frame.shape[0])
            preview_frame = frame
            now_perf = time.perf_counter()
            should_emit_preview = now_perf >= self._next_preview_frame_at
            should_record_frame = self._recording and now_perf >= self._next_record_frame_at

            if self._pending_start_order_id and not self._recording:
                pending_order_id = self._pending_start_order_id
                self._pending_start_order_id = None
                self._start_recording(pending_order_id)
                now_perf = time.perf_counter()
                should_emit_preview = True
                should_record_frame = self._recording
            elif self._recording and not should_record_frame:
                should_emit_preview = False

            if self._recording and should_record_frame:
                now = datetime.now()
                write_frame = self._prepare_frame_for_writer(frame)
                try:
                    watermark_started = time.perf_counter()
                    watermarked = self._watermark.draw(write_frame.copy(), self._order_id, now)
                    watermark_elapsed = time.perf_counter() - watermark_started
                    self._perf_watermark_count += 1
                    self._perf_watermark_time_sum += watermark_elapsed
                except Exception as exc:
                    if not self._watermark_error_logged:
                        self.logger.exception("预览或录制水印绘制异常")
                        self._watermark_error_logged = True
                    self.message.emit(f"视频水印绘制失败：{exc}")
                    watermarked = write_frame.copy()

                if self._show_recording_watermark_in_preview():
                    preview_frame = watermarked.copy()
                else:
                    preview_frame = frame

                try:
                    enqueue_started = time.perf_counter()
                    if self._writer_worker is None:
                        raise RuntimeError("视频写入线程不可用")
                    if not self._writer_worker.enqueue(watermarked):
                        raise RuntimeError("视频写入队列不可用")
                    enqueue_elapsed = time.perf_counter() - enqueue_started
                    self._perf_enqueue_count += 1
                    self._perf_enqueue_time_sum += enqueue_elapsed
                    self._frames_enqueued += 1
                except Exception as exc:
                    self.logger.exception("视频保存失败")
                    self._trigger_recording_error(f"视频写入失败：{exc}")
                    continue

                self._schedule_next_record_frame(now_perf)
                if self._start_time is not None:
                    duration = int((now - self._start_time).total_seconds())
                    if duration != last_duration:
                        last_duration = duration
                        self.duration_changed.emit(duration)

            if should_emit_preview or should_record_frame:
                preview_started = time.perf_counter()
                self.frame_ready.emit(preview_frame)
                self._perf_preview_count += 1
                self._perf_preview_time_sum += time.perf_counter() - preview_started
                self._next_preview_frame_at = time.perf_counter() + (1.0 / 30.0)

            self._log_performance_if_needed()
            self._check_recording_runtime_health()
            time.sleep(0.001)

        if self._recording:
            self._stop_recording()
        self._release_camera()

    def _handle_capture_unavailable(self) -> None:
        now_perf = time.perf_counter()
        self._camera_fail_count += 1
        self._camera_success_count = 0
        self._camera_pending_recover_since = 0.0
        self._camera_last_error = "摄像头连接异常，请检查 iVCam 或摄像头"
        if self._camera_pending_error_since <= 0:
            self._camera_pending_error_since = now_perf
            self._set_camera_state("suspected_error", error_type="capture_unavailable", reason=self._camera_last_error)
        if self._camera_unhealthy_since <= 0:
            self._camera_unhealthy_since = now_perf
        if now_perf - self._last_camera_issue_log_at >= 1.0:
            self.logger.warning(
                "摄像头不可用待确认：连续失败=%s, 阈值=%s, 距离最后成功帧=%.2f秒, recording=%s",
                self._camera_fail_count,
                self._camera_fail_limit(),
                now_perf - self._last_frame_ok_at,
                self._recording,
            )
            self._last_camera_issue_log_at = now_perf
        confirmed = self._maybe_confirm_camera_error(self._camera_last_error)
        if confirmed and self._recording:
            self._trigger_recording_error(self._camera_last_error)

    def _handle_camera_read_failure(self) -> None:
        self._camera_fail_count += 1
        now_perf = time.perf_counter()
        elapsed = now_perf - self._last_frame_ok_at
        self._camera_success_count = 0
        self._camera_pending_recover_since = 0.0
        self._camera_last_error = "摄像头读取失败，请检查 iVCam 或摄像头"
        if self._camera_pending_error_since <= 0:
            self._camera_pending_error_since = now_perf
            self._set_camera_state("suspected_error", error_type="read_failed", reason=self._camera_last_error)
        if self._camera_unhealthy_since <= 0:
            self._camera_unhealthy_since = now_perf
        if now_perf - self._last_camera_issue_log_at >= 1.0:
            self.logger.warning(
                "摄像头读取失败待确认：连续失败=%s, 阈值=%s, 距离最后成功帧=%.2f秒, recording=%s",
                self._camera_fail_count,
                self._camera_fail_limit(),
                elapsed,
                self._recording,
            )
            self._last_camera_issue_log_at = now_perf
        confirmed = self._maybe_confirm_camera_error(self._camera_last_error)
        if confirmed and self._recording:
            self._trigger_recording_error("摄像头读取失败，请检查 iVCam 或摄像头")

    def _handle_camera_frame_ok(self, frame: np.ndarray) -> None:
        now_perf = time.perf_counter()
        was_confirmed_error = self._camera_confirmed_error
        was_unhealthy = self._camera_confirmed_error or self._camera_fail_count > 0 or self._ivcam_waiting or not self._camera_available
        self._last_frame_ok_at = now_perf
        if self._check_ivcam_waiting_frame(frame):
            self._confirm_camera_error(self._ivcam_placeholder_message or "摄像头连接异常，请检查 iVCam")
            if self._recording:
                self._trigger_recording_error(self._camera_last_error)
            return
        if not self._camera_confirmed_error:
            self._ivcam_waiting = False
        self._check_frame_freeze(frame)

        self._camera_fail_count = 0
        self._camera_success_count += 1
        self._camera_pending_error_since = 0.0
        if self._camera_pending_recover_since <= 0:
            self._camera_pending_recover_since = now_perf
            if was_confirmed_error:
                self._set_camera_state(
                    "recovering",
                    error_type=self._ivcam_placeholder_type or "camera_recovering",
                    reason="检测到正常帧，等待稳定恢复",
                )
        stable_for = now_perf - self._camera_pending_recover_since
        if was_unhealthy:
            if self._camera_confirmed_error:
                if self._camera_success_count >= CAMERA_RECOVER_SUCCESS_LIMIT and stable_for >= CAMERA_RECOVER_SECONDS:
                    self._confirm_camera_recovered()
                return
            if self._camera_success_count >= CAMERA_RECOVER_SUCCESS_LIMIT or stable_for >= CAMERA_RECOVER_SECONDS:
                if self._camera_state != "normal":
                    self._set_camera_state("normal", error_type="recovered", reason="摄像头状态恢复")
                self._confirm_camera_recovered()
            return

        self._camera_available = True
        self._camera_last_error = ""
        self._camera_unhealthy_since = 0.0

    def _check_frame_freeze(self, frame: np.ndarray) -> bool:
        now_perf = time.perf_counter()
        if now_perf - self._freeze_sample_at < 1.0:
            return False
        self._freeze_sample_at = now_perf
        try:
            sample = cv2.resize(frame, (32, 18), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
        except Exception:
            self.logger.info("画面冻结抽样失败", exc_info=True)
            return False
        if self._last_freeze_sample is None:
            self._last_freeze_sample = gray
            self._freeze_started_at = now_perf
            return False
        diff = float(np.mean(cv2.absdiff(gray, self._last_freeze_sample)))
        if diff <= FRAME_FREEZE_DIFF_THRESHOLD:
            frozen_for = now_perf - self._freeze_started_at
            if frozen_for >= FRAME_FREEZE_SECONDS:
                self._frame_frozen = True
                if now_perf - self._last_freeze_warning_log_at >= 30.0:
                    self.logger.warning(
                        "摄像头画面长时间变化很小，仅记录为疑似静止画面，不触发异常：diff=%.3f, frozen_for=%.2f秒, recording=%s, iVCam=%s",
                        diff,
                        frozen_for,
                        self._recording,
                        self._ivcam_camera,
                    )
                    self._last_freeze_warning_log_at = now_perf
        else:
            self._last_freeze_sample = gray
            self._freeze_started_at = now_perf
            self._frame_frozen = False
        return False

    def _check_ivcam_waiting_frame(self, frame: np.ndarray) -> bool:
        if not self._ivcam_camera:
            self._ivcam_waiting = False
            self._ivcam_wait_matches = 0
            self._ivcam_placeholder_type = ""
            self._ivcam_placeholder_message = ""
            self._ivcam_placeholder_metrics = {}
            self._ivcam_placeholder_first_match_at = 0.0
            return False
        now_perf = time.perf_counter()
        if now_perf - self._ivcam_placeholder_last_check_at < IVCAM_PLACEHOLDER_CHECK_INTERVAL:
            if self._camera_confirmed_error and self._ivcam_waiting:
                return True
            return False
        self._ivcam_placeholder_last_check_at = now_perf
        was_waiting = self._ivcam_waiting
        placeholder_type, message, metrics = self._detect_ivcam_placeholder_frame(frame)
        if placeholder_type:
            if self._ivcam_wait_matches <= 0 or placeholder_type != self._ivcam_placeholder_type:
                self._ivcam_wait_matches = 0
                self._ivcam_placeholder_first_match_at = now_perf
            self._ivcam_placeholder_type = placeholder_type
            self._ivcam_placeholder_message = message
            self._ivcam_placeholder_metrics = metrics
            self._ivcam_wait_matches += 1
            if now_perf - self._ivcam_placeholder_last_log_at >= 2.0:
                self.logger.info(
                    "iVCam 占位画面待确认：type=%s, score=%.2f, matches=%s, duration=%.2f秒, "
                    "light_bg=%s, blue_circle=%s, blue_area=%.4f, blue_bbox=(%.2f,%.2f,%.2f,%.2f), "
                    "text_score=%.4f, computer_score=%.4f, recording=%s",
                    placeholder_type,
                    metrics.get("placeholder_score", 0.0),
                    self._ivcam_wait_matches,
                    now_perf - self._ivcam_placeholder_first_match_at,
                    bool(metrics.get("light_background", 0.0)),
                    bool(metrics.get("blue_circle_detected", 0.0)),
                    metrics.get("blue_component_area_ratio", 0.0),
                    metrics.get("blue_bbox_x", 0.0),
                    metrics.get("blue_bbox_y", 0.0),
                    metrics.get("blue_bbox_w", 0.0),
                    metrics.get("blue_bbox_h", 0.0),
                    metrics.get("text_region_score", 0.0),
                    metrics.get("computer_line_score", 0.0),
                    self._recording,
                )
                self._ivcam_placeholder_last_log_at = now_perf
            if self._camera_confirmed_error:
                self._ivcam_waiting = True
                self._camera_success_count = 0
                self._camera_pending_recover_since = 0.0
                self._set_camera_state("error", error_type=placeholder_type, reason=message)
                return True
        else:
            self._ivcam_wait_matches = 0
            self._ivcam_placeholder_first_match_at = 0.0
            if self._camera_confirmed_error and self._ivcam_waiting:
                self._ivcam_waiting = False
            elif not self._camera_confirmed_error:
                self._ivcam_waiting = False
                self._ivcam_placeholder_type = ""
                self._ivcam_placeholder_message = ""
                self._ivcam_placeholder_metrics = {}
        match_limit = IVCAM_PLACEHOLDER_MATCH_LIMIT if placeholder_type == "ivcam_placeholder" else IVCAM_WAIT_MATCH_LIMIT
        matched_for = now_perf - self._ivcam_placeholder_first_match_at if self._ivcam_placeholder_first_match_at > 0 else 0.0
        if placeholder_type and self._ivcam_wait_matches >= match_limit and matched_for >= IVCAM_PLACEHOLDER_MIN_SECONDS:
            self._ivcam_waiting = True
            if not was_waiting:
                self.logger.error(
                    "检测到 iVCam 异常占位画面：type=%s, score=%.2f, matches=%s, duration=%.2f秒, "
                    "light_bg=%s, blue_circle=%s, blue_area=%.4f, blue_bbox=(%.2f,%.2f,%.2f,%.2f), "
                    "text_score=%.4f, computer_score=%.4f, recording=%s",
                    placeholder_type,
                    metrics.get("placeholder_score", 0.0),
                    self._ivcam_wait_matches,
                    matched_for,
                    bool(metrics.get("light_background", 0.0)),
                    bool(metrics.get("blue_circle_detected", 0.0)),
                    metrics.get("blue_component_area_ratio", 0.0),
                    metrics.get("blue_bbox_x", 0.0),
                    metrics.get("blue_bbox_y", 0.0),
                    metrics.get("blue_bbox_w", 0.0),
                    metrics.get("blue_bbox_h", 0.0),
                    metrics.get("text_region_score", 0.0),
                    metrics.get("computer_line_score", 0.0),
                    self._recording,
                )
            return True
        return False

    def _detect_ivcam_placeholder_frame(self, frame: np.ndarray) -> tuple[str, str, dict[str, float]]:
        try:
            if not self.is_valid_camera_frame(frame):
                return "", "", {}
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            bgr = small.astype(np.float32)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            brightness = float(np.mean(gray))
            gray_std = float(np.std(gray))
            edges = cv2.Canny(gray, 70, 150)
            edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)
            channel_gap = float(np.mean(np.max(bgr, axis=2) - np.min(bgr, axis=2)))
            blue_mask = cv2.inRange(hsv, (85, 35, 45), (135, 255, 255))
            blue_count = int(np.count_nonzero(blue_mask))
            blue_ratio = float(np.count_nonzero(blue_mask)) / float(blue_mask.size)
            center = blue_mask[18:72, 35:125]
            center_blue_ratio = float(np.count_nonzero(center)) / float(center.size)
            left_visual_roi = blue_mask[8:70, 8:90]
            left_blue_ratio = float(np.count_nonzero(left_visual_roi)) / float(left_visual_roi.size)
            light_text_mask = cv2.inRange(hsv, (0, 0, 95), (179, 70, 245))
            lower_center = light_text_mask[44:78, 28:132]
            light_text_ratio = float(np.count_nonzero(lower_center)) / float(lower_center.size)
            dark_ratio = float(np.count_nonzero(gray < 55)) / float(gray.size)
            light_bg_ratio = float(np.count_nonzero(gray > 178)) / float(gray.size)
            light_clean_mask = cv2.inRange(hsv, (0, 0, 190), (179, 80, 255))
            light_clean_ratio = float(np.count_nonzero(light_clean_mask)) / float(light_clean_mask.size)
            right_line_roi = edges[12:55, 88:150]
            computer_line_score = float(np.count_nonzero(right_line_roi)) / float(right_line_roi.size)
            text_edge_roi = edges[50:80, 38:140]
            text_region_score = float(np.count_nonzero(text_edge_roi)) / float(text_edge_roi.size)
            if blue_count > 0:
                blue_y, blue_x = np.nonzero(blue_mask)
                blue_cx = float(np.mean(blue_x)) / float(blue_mask.shape[1])
                blue_cy = float(np.mean(blue_y)) / float(blue_mask.shape[0])
            else:
                blue_cx = -1.0
                blue_cy = -1.0
            blue_near_center = 0.24 <= blue_cx <= 0.70 and 0.22 <= blue_cy <= 0.68
            blue_component_detected = False
            blue_component_area_ratio = 0.0
            blue_bbox_x = blue_bbox_y = blue_bbox_w = blue_bbox_h = 0.0
            blue_component_aspect = 0.0
            blue_component_fill = 0.0
            if blue_count > 0:
                component_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(blue_mask, 8)
                largest_area = 0
                largest_bbox = (0, 0, 0, 0)
                for index in range(1, component_count):
                    x, y, width, height, area = stats[index]
                    if int(area) > int(largest_area):
                        largest_area = int(area)
                        largest_bbox = (int(x), int(y), int(width), int(height))
                if largest_area > 0:
                    width_s = float(blue_mask.shape[1])
                    height_s = float(blue_mask.shape[0])
                    x, y, width, height = largest_bbox
                    blue_component_area_ratio = float(largest_area) / float(blue_mask.size)
                    blue_bbox_x = float(x) / width_s
                    blue_bbox_y = float(y) / height_s
                    blue_bbox_w = float(width) / width_s
                    blue_bbox_h = float(height) / height_s
                    blue_component_aspect = float(width) / float(max(1, height))
                    blue_component_fill = float(largest_area) / float(max(1, width * height))
                    blue_component_detected = (
                        0.012 <= blue_component_area_ratio <= 0.24
                        and 0.04 <= blue_bbox_x <= 0.55
                        and 0.08 <= blue_bbox_y <= 0.72
                        and 0.16 <= blue_bbox_w <= 0.58
                        and 0.20 <= blue_bbox_h <= 0.78
                        and 0.65 <= blue_component_aspect <= 1.45
                        and blue_component_fill >= 0.20
                        and left_blue_ratio >= 0.06
                    )
            light_background = brightness >= 175 and light_bg_ratio >= 0.62 and light_clean_ratio >= 0.42
            waiting_score = 0.0
            if light_background:
                waiting_score += 0.25
            if blue_component_detected:
                waiting_score += 0.45
            if computer_line_score >= 0.018:
                waiting_score += 0.15
            if text_region_score >= 0.018:
                waiting_score += 0.15
            metrics = {
                "brightness": brightness,
                "blue_score": center_blue_ratio,
                "blue_ratio": blue_ratio,
                "left_blue_ratio": left_blue_ratio,
                "light_text_score": light_text_ratio,
                "dark_ratio": dark_ratio,
                "light_bg_ratio": light_bg_ratio,
                "light_clean_ratio": light_clean_ratio,
                "channel_gap": channel_gap,
                "edge_ratio": edge_ratio,
                "gray_std": gray_std,
                "blue_cx": blue_cx,
                "blue_cy": blue_cy,
                "blue_circle_detected": 1.0 if blue_component_detected else 0.0,
                "blue_component_area_ratio": blue_component_area_ratio,
                "blue_component_aspect": blue_component_aspect,
                "blue_component_fill": blue_component_fill,
                "blue_bbox_x": blue_bbox_x,
                "blue_bbox_y": blue_bbox_y,
                "blue_bbox_w": blue_bbox_w,
                "blue_bbox_h": blue_bbox_h,
                "light_background": 1.0 if light_background else 0.0,
                "text_region_score": text_region_score,
                "computer_line_score": computer_line_score,
                "placeholder_score": waiting_score,
            }
            if self._looks_like_real_camera_frame(edge_ratio=edge_ratio, gray_std=gray_std):
                metrics["real_frame_score"] = 1.0
                return "", "", metrics
            metrics["real_frame_score"] = 0.0
            if (
                brightness <= 35
                and dark_ratio >= 0.82
                and blue_near_center
                and 0.003 <= blue_ratio <= 0.045
                and 0.012 <= center_blue_ratio <= 0.11
                and 0.004 <= light_text_ratio <= 0.075
                and edge_ratio <= 0.075
                and gray_std <= 62
            ):
                return "ivcam_placeholder", "iVCam 未启动或未连接，请检查手机端 iVCam", metrics
            if (
                brightness >= 165
                and light_background
                and blue_component_detected
                and waiting_score >= 0.82
                and (computer_line_score >= 0.010 or text_region_score >= 0.010)
                and 0.03 <= blue_ratio <= 0.24
                and edge_ratio <= 0.090
                and gray_std <= 70
            ):
                return "ivcam_waiting_connection", "摄像头连接异常，请检查 iVCam", metrics
        except Exception:
            self.logger.debug("iVCam 占位画面检测失败", exc_info=True)
        return "", "", {}

    @staticmethod
    def is_valid_camera_frame(frame: np.ndarray | None) -> bool:
        if frame is None or not hasattr(frame, "shape"):
            return False
        if len(frame.shape) < 2:
            return False
        height = int(frame.shape[0] or 0)
        width = int(frame.shape[1] or 0)
        return width > 0 and height > 0

    @staticmethod
    def _looks_like_real_camera_frame(*, edge_ratio: float, gray_std: float) -> bool:
        # 只作为保护信号使用：条码、面单、纸箱纹理明显时，不把画面内容反推成摄像头异常。
        return edge_ratio >= 0.095 or (edge_ratio >= 0.065 and gray_std >= 44)

    def _check_recording_runtime_health(self) -> None:
        if not self._recording:
            return
        now_perf = time.perf_counter()
        if now_perf - self._last_disk_check_at >= DISK_CHECK_INTERVAL_SECONDS:
            self._last_disk_check_at = now_perf
            result = DiskSpaceChecker(self._recording_disk_config(), self.logger).check(self._video_dir())
            self.logger.info("录制保护磁盘检查：free=%.2fGB, level=%s", result.free_gb, result.level)
            if result.free_gb <= DISK_CRITICAL_GB or result.level == "critical":
                self._trigger_recording_error("磁盘空间不足，请及时清理")
                return
            if result.free_gb <= DISK_WARNING_GB or result.level == "warning":
                self.warning_message.emit("磁盘空间不足，请及时清理")
        if now_perf - self._last_file_growth_check_at >= FILE_GROWTH_CHECK_INTERVAL_SECONDS:
            self._last_file_growth_check_at = now_perf
            self._check_recording_file_growth()

    def _check_recording_file_growth(self) -> None:
        if self._temp_path is None:
            return
        try:
            current_size = int(self._temp_path.stat().st_size)
        except OSError as exc:
            self._trigger_recording_error(f"视频写入失败，请检查视频存储目录或磁盘空间：{exc}")
            return
        self.logger.info(
            "录制保护文件增长检查：path=%s, size=%s, last_size=%s, frames=%s, last_frames=%s, stall_count=%s",
            self._temp_path,
            current_size,
            self._last_recording_file_size,
            self._frames_enqueued,
            self._last_file_growth_frame_count,
            self._file_stall_count,
        )
        frames_increased = self._frames_enqueued > self._last_file_growth_frame_count
        if (
            self._frames_enqueued > max(5, self._effective_recording_fps)
            and current_size <= self._last_recording_file_size
            and not frames_increased
        ):
            self._file_stall_count += 1
        else:
            self._file_stall_count = 0
        self._last_recording_file_size = current_size
        self._last_file_growth_frame_count = self._frames_enqueued
        if self._file_stall_count >= FILE_STALL_LIMIT:
            self._trigger_recording_error("视频写入失败，请检查视频存储目录或磁盘空间")

    def _trigger_recording_error(self, reason: str) -> None:
        reason = str(reason or "录制异常").strip()
        if not self._recording:
            self.critical_message.emit(reason)
            self.message.emit(reason)
            return
        self._recording_error_reason = reason
        self.logger.error("录制保护触发异常：%s", reason)
        self.critical_message.emit(reason)
        self.message.emit(f"录制异常：{reason}")
        self._stop_recording(save_failed_reason=reason)

    def _drain_commands(self) -> None:
        while True:
            try:
                command, payload = self._commands.get_nowait()
            except queue.Empty:
                break

            try:
                if command == "scan":
                    self._handle_scan(str(payload or ""))
                elif command == "manual_start":
                    self._handle_manual_start(str(payload or ""))
                elif command == "manual_stop":
                    self._handle_manual_stop()
                elif command == "restart_camera":
                    self._handle_restart_camera()
                elif command == "update_config":
                    self._handle_update_config(payload)
            except Exception as exc:
                self.logger.exception("处理录制命令失败")
                self.message.emit(f"操作失败：{exc}")

    def _handle_scan(self, order_id: str) -> None:
        order_id = order_id.strip()
        self.logger.info("扫码内容：%s", order_id or "<空>")

        if not self._recording:
            if order_id:
                self._start_recording(order_id)
            return

        current_order_id = self._order_id.strip()
        if not order_id:
            self.logger.info("扫码为空，停止当前录制：单号=%s", current_order_id)
            self._stop_recording()
            return

        if order_id == current_order_id:
            self.logger.info("扫描到与当前正在录制单号一致，执行结束录制：%s", order_id)
            self._stop_recording()
            return

        self.logger.info("扫描到新单号，切换录制：%s -> %s", current_order_id, order_id)
        self._stop_recording()
        if bool(self.config.get("auto_continue_recording", True)):
            self._pending_start_order_id = order_id
            self.message.emit(f"准备开始下一单录制：{order_id}")

    def _handle_manual_start(self, order_id: str) -> None:
        order_id = order_id.strip()
        if self._recording:
            self.message.emit("当前正在录制，请先停止当前录制")
            return
        if not order_id:
            self.message.emit("请先输入或扫描单号")
            return
        self._start_recording(order_id)

    def _handle_manual_stop(self) -> None:
        if self._pending_start_order_id and not self._recording:
            self.logger.info("取消待启动录制：单号=%s", self._pending_start_order_id)
            self._pending_start_order_id = None
            self.message.emit("已取消待启动录制")
            return
        if not self._recording:
            self.message.emit("当前未录制")
            return
        self._stop_recording()

    def _handle_restart_camera(self) -> None:
        if self._recording:
            self.message.emit("录制中不能刷新摄像头")
            return
        self._open_camera()

    def _handle_update_config(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self._watermark.update(
            int(self.config.get("watermark_font_size", 28) or 28),
            int(self.config.get("watermark_margin", 16) or 16),
        )
        self.message.emit("配置已保存")

    def _show_recording_watermark_in_preview(self) -> bool:
        preview_config = self.config.get("preview", {})
        if not isinstance(preview_config, dict):
            return True
        return bool(preview_config.get("show_recording_watermark", True))

    def _effective_fps(self, target_fps: int) -> int:
        target_fps = max(1, int(target_fps or 25))
        if self._camera_actual_fps and self._camera_actual_fps > 1 and self._camera_actual_fps + 1 < target_fps:
            return max(1, int(round(self._camera_actual_fps)))
        return target_fps

    def _schedule_next_record_frame(self, now_perf: float) -> None:
        if self._next_record_frame_at <= 0:
            self._next_record_frame_at = now_perf + self._record_interval
            return
        self._next_record_frame_at += self._record_interval
        if self._next_record_frame_at < now_perf - self._record_interval:
            self._next_record_frame_at = now_perf + self._record_interval

    def _reset_performance_window(self) -> None:
        self._perf_last_log = time.perf_counter()
        self._perf_capture_count = 0
        self._perf_capture_time_sum = 0.0
        self._perf_watermark_time_sum = 0.0
        self._perf_watermark_count = 0
        self._perf_enqueue_time_sum = 0.0
        self._perf_enqueue_count = 0
        self._perf_preview_time_sum = 0.0
        self._perf_preview_count = 0
        self._perf_last_drop_count = 0

    def _log_performance_if_needed(self) -> None:
        now = time.perf_counter()
        elapsed = now - self._perf_last_log
        if elapsed < 5:
            return

        writer_snapshot = self._writer_worker.snapshot(reset_window=True) if self._writer_worker else {}
        dropped_total = int(writer_snapshot.get("frames_dropped", 0) or 0)
        dropped_window = max(0, dropped_total - self._perf_last_drop_count)
        self._perf_last_drop_count = dropped_total
        capture_fps = self._perf_capture_count / max(0.001, elapsed)
        avg_capture_ms = self._perf_capture_time_sum / max(1, self._perf_capture_count) * 1000
        avg_watermark_ms = self._perf_watermark_time_sum / max(1, self._perf_watermark_count) * 1000
        avg_enqueue_ms = self._perf_enqueue_time_sum / max(1, self._perf_enqueue_count) * 1000
        avg_preview_ms = self._perf_preview_time_sum / max(1, self._perf_preview_count) * 1000
        queue_size = int(writer_snapshot.get("queue_size", 0) or 0)
        avg_write_ms = float(writer_snapshot.get("avg_write_ms", 0.0) or 0.0)
        max_write_ms = float(writer_snapshot.get("max_write_ms", 0.0) or 0.0)
        self.logger.info(
            "录制性能窗口：采集FPS=%.2f, 摄像头实际FPS=%s, 配置FPS=%s, 写入FPS=%s, 平均采集耗时=%.2fms, 平均水印耗时=%.2fms, 平均入队耗时=%.2fms, 平均写入耗时=%.2fms, 最大写入耗时=%.2fms, 预览刷新耗时=%.2fms, 队列长度=%s, 是否丢帧=%s, 窗口丢帧=%s, 总丢帧=%s",
            capture_fps,
            f"{self._camera_actual_fps:.2f}" if self._camera_actual_fps else "unknown",
            self._target_recording_fps,
            self._effective_recording_fps,
            avg_capture_ms,
            avg_watermark_ms,
            avg_enqueue_ms,
            avg_write_ms,
            max_write_ms,
            avg_preview_ms,
            queue_size,
            "是" if dropped_window > 0 else "否",
            dropped_window,
            dropped_total,
        )
        if self._recording and (queue_size >= max(10, self._effective_recording_fps) or dropped_window > 0):
            message = "当前录制性能不足，建议降低帧率、分辨率或录制长边上限。"
            self.logger.warning("%s 队列长度=%s, 窗口丢帧=%s", message, queue_size, dropped_window)
            self.warning_message.emit(message)
            self.message.emit(message)
        if self._recording and capture_fps + 1 < self._effective_recording_fps:
            message = "当前摄像头实际帧率低于配置帧率，建议降低帧率或分辨率。"
            self.logger.warning(
                "%s 窗口采集FPS=%.2f, 写入FPS=%s",
                message,
                capture_fps,
                self._effective_recording_fps,
            )
            self.warning_message.emit(message)
            self.message.emit(message)
        if avg_write_ms > 1000 / max(1, self._effective_recording_fps):
            self.logger.warning(
                "录制写入耗时较高，建议降低帧率或分辨率：平均写入耗时=%.2fms, 写入FPS=%s",
                avg_write_ms,
                self._effective_recording_fps,
            )
        self._reset_performance_window()
        self._perf_last_drop_count = dropped_total

    def _start_recording(self, order_id: str) -> None:
        health = self.camera_health()
        if not health.get("is_healthy", False):
            reason = str(health.get("last_error") or "摄像头连接异常，请检查 iVCam 或摄像头")
            self.logger.error("开始录制失败：摄像头健康检查未通过，reason=%s, health=%s", reason, health)
            self.critical_message.emit(reason)
            self.message.emit(reason)
            return

        if self._capture is None or not self._capture.isOpened():
            self.message.emit("摄像头不可用，无法开始录制")
            self.logger.error("开始录制失败：摄像头不可用")
            return

        video_dir = self._video_dir()
        disk_result = DiskSpaceChecker(self._recording_disk_config(), self.logger).check(video_dir)
        if disk_result.free_gb <= DISK_CRITICAL_GB or disk_result.level == "critical":
            message = "磁盘空间不足，无法开始录制"
            self.logger.error("%s：dir=%s, free=%.2fGB", message, video_dir, disk_result.free_gb)
            self.critical_message.emit(message)
            self.message.emit(message)
            return
        if disk_result.free_gb <= DISK_WARNING_GB or disk_result.level == "warning":
            message = "磁盘空间不足，请及时清理"
            self.logger.warning("%s：dir=%s, free=%.2fGB", message, video_dir, disk_result.free_gb)
            self.warning_message.emit(message)
            self.message.emit(message)
        extension = str(self.config.get("video_format", "mp4") or "mp4").lower()
        recording_started_at = datetime.now()
        try:
            temp_path = unique_temp_recording_path(video_dir, order_id, extension, recording_started_at)
        except OSError as exc:
            self.logger.exception("创建视频日期存储目录失败：base_dir=%s, order_id=%s", video_dir, order_id)
            self.message.emit(f"无法创建视频存储目录：{exc}")
            return

        self._check_disk_space_notice()

        width, height = self._recording_frame_size(*self._current_frame_size())
        target_fps = int(self.config.get("fps", 25) or 25)
        fps = self._effective_fps(target_fps)

        writer, codec = self._create_writer(temp_path, width, height, fps, extension)
        if writer is None:
            message = "视频编码器不可用，无法创建 mp4 文件"
            self.message.emit(message)
            self.logger.error("开始录制失败：%s", message)
            return

        max_queue_size = max(30, fps * 2)
        self._writer = None
        self._writer_worker = RecordingWriterWorker(writer, self.logger, max_queue_size)
        self._writer_size = (width, height)
        self._temp_path = temp_path
        self._recording = True
        self._order_id = order_id
        self._record_type_for_current_recording = str(self.config.get("current_record_type") or "发货")
        self._start_time = recording_started_at
        self._frames_written = 0
        self._frames_enqueued = 0
        self._target_recording_fps = target_fps
        self._effective_recording_fps = fps
        self._record_interval = 1.0 / max(1, fps)
        self._next_record_frame_at = 0.0
        self._next_preview_frame_at = 0.0
        self._recording_error_reason = None
        self._last_disk_check_at = time.perf_counter()
        self._last_file_growth_check_at = time.perf_counter()
        self._last_recording_file_size = 0
        self._last_file_growth_frame_count = 0
        self._file_stall_count = 0
        self._freeze_sample_at = 0.0
        self._freeze_started_at = time.perf_counter()
        self._last_freeze_sample = None
        self._last_freeze_warning_log_at = 0.0
        self._ivcam_wait_matches = 0
        self._ivcam_waiting = False
        self._ivcam_placeholder_type = ""
        self._ivcam_placeholder_message = ""
        self._ivcam_placeholder_metrics = {}
        self._ivcam_placeholder_first_match_at = 0.0
        self._ivcam_placeholder_last_check_at = 0.0
        self._ivcam_placeholder_last_log_at = 0.0
        self._frame_frozen = False
        self._reset_performance_window()
        self.logger.info("录制保护监控启动：单号=%s, iVCam=%s, free=%.2fGB", order_id, self._ivcam_camera, disk_result.free_gb)

        self.logger.info(
            "开始录制：单号=%s, 临时文件=%s, 编码=%s, 配置FPS=%s, 写入FPS=%s, 摄像头实际FPS=%s, 队列容量=%s",
            order_id,
            temp_path,
            codec,
            target_fps,
            fps,
            self._camera_actual_fps if self._camera_actual_fps else "unknown",
            max_queue_size,
        )
        if self._camera_actual_fps and self._camera_actual_fps + 1 < target_fps:
            message = "当前摄像头实际帧率低于配置帧率，可能导致视频不流畅，建议降低帧率或分辨率。"
            self.logger.warning("%s 摄像头实际FPS=%.2f, 配置FPS=%s", message, self._camera_actual_fps, target_fps)
            self.warning_message.emit(message)
            self.message.emit(message)
        if self._show_recording_watermark_in_preview() and not self._preview_watermark_logged:
            self.logger.info("预览水印功能启用")
            self._preview_watermark_logged = True
        self.recording_state_changed.emit(True, order_id, format_datetime(self._start_time))
        self.duration_changed.emit(0)
        self.message.emit(f"开始录制：{order_id}")

    def _stop_recording(self, save_failed_reason: str | None = None) -> None:
        if not self._recording:
            return

        order_id = self._order_id
        temp_path = self._temp_path
        writer_worker = self._writer_worker
        started_at = self._start_time
        extension = str(self.config.get("video_format", "mp4") or "mp4").lower()
        recording_ended_at = datetime.now()

        self.logger.info("停止录制：单号=%s", order_id)

        writer_snapshot: dict[str, float | int | str] = {}
        if writer_worker is not None:
            writer_worker.stop_and_wait()
            writer_snapshot = writer_worker.snapshot(reset_window=False)

        frames_written = int(writer_snapshot.get("frames_written", 0) or 0)
        frames_dropped = int(writer_snapshot.get("frames_dropped", 0) or 0)
        if writer_snapshot.get("error") and not save_failed_reason:
            save_failed_reason = str(writer_snapshot.get("error"))
        is_abnormal_stop = bool(save_failed_reason)

        self._writer = None
        self._writer_worker = None
        self._writer_size = None
        self._recording = False
        self._order_id = ""
        self._start_time = None
        self._temp_path = None
        self._frames_written = 0
        self._frames_enqueued = 0
        self.recording_state_changed.emit(False, "", "")
        self.duration_changed.emit(0)

        if is_abnormal_stop:
            self.logger.error("录制异常终止，保留当前视频并写入异常记录：%s", save_failed_reason)

        if temp_path is None or not temp_path.exists():
            message = "临时视频文件不存在，保存失败"
            self.logger.error(message)
            self.message.emit(message)
            return

        try:
            temp_size = temp_path.stat().st_size
        except OSError:
            temp_size = 0

        if frames_written <= 0 or temp_size <= 0:
            self.logger.warning(
                "录制文件大小或帧数异常，仍保留文件等待完整性校验：单号=%s，帧数=%s，大小=%s，临时文件=%s",
                order_id,
                frames_written,
                temp_size,
                temp_path,
            )

        try:
            final_path = unique_video_path(self._video_dir(), order_id, extension, started_at)
        except OSError as exc:
            self.logger.exception("创建视频日期存储目录失败：order_id=%s", order_id)
            self.message.emit(f"无法创建视频存储目录：{exc}")
            return

        try:
            temp_path.rename(final_path)
        except OSError as exc:
            self.logger.exception("视频保存失败")
            self.message.emit(f"视频保存失败：{exc}")
            return

        duration_seconds = 0
        if started_at is not None:
            duration_seconds = max(0, int((recording_ended_at - started_at).total_seconds()))
        self.logger.info("录制时长：单号=%s，时长=%s 秒", order_id, duration_seconds)
        avg_record_fps = frames_written / max(0.001, (recording_ended_at - started_at).total_seconds()) if started_at else 0.0
        self.logger.info(
            "录制性能摘要：单号=%s, 开始时间=%s, 结束时间=%s, 实际时长=%.2f秒, 配置FPS=%s, 写入FPS=%s, 总帧数=%s, 平均录制FPS=%.2f, 丢帧=%s, 平均写入耗时=%.2fms, 最大写入耗时=%.2fms",
            order_id,
            format_datetime(started_at) if started_at else "",
            format_datetime(recording_ended_at),
            (recording_ended_at - started_at).total_seconds() if started_at else 0.0,
            self._target_recording_fps,
            self._effective_recording_fps,
            frames_written,
            avg_record_fps,
            frames_dropped,
            float(writer_snapshot.get("avg_write_ms", 0.0) or 0.0),
            float(writer_snapshot.get("max_write_ms", 0.0) or 0.0),
        )

        check_result = self._video_checker.check_video(final_path)
        self.logger.info(
            "视频校验结果：文件=%s, 是否有效=%s, 视频时长=%.2f秒, 视频帧数=%s, 文件大小=%s",
            final_path,
            check_result.is_valid,
            check_result.duration_seconds,
            check_result.frame_count,
            check_result.file_size,
        )
        self._update_video_index(final_path, started_at)
        validation_warning = str(getattr(check_result, "warning", "") or "")
        validation_error = str(getattr(check_result, "error", "") or check_result.message or "")
        if is_abnormal_stop:
            abnormal_reason = str(save_failed_reason or validation_error or "录制异常")
            self._mark_video_abnormal(final_path, abnormal_reason)
            warning = f"录制异常：{abnormal_reason}"
            self.logger.error("异常视频已写入 SQLite：file=%s, reason=%s", final_path, abnormal_reason)
            self.warning_message.emit(warning)
            self.message.emit(warning)
            self._schedule_video_hash_generation(final_path)
            self._check_disk_space_notice()
            return
        if not check_result.exists:
            warning = "视频文件不存在，校验失败"
            self.logger.warning("%s：%s", warning, final_path)
            self.warning_message.emit(warning)
            self.message.emit(warning)
        elif check_result.is_valid and validation_warning:
            warning = "视频已保存，但时长过短，请确认是否误操作"
            self.logger.warning("%s：%s，时长=%.2f 秒", warning, final_path, check_result.duration_seconds)
            self.warning_message.emit(warning)
            self.message.emit(warning)
        elif check_result.is_valid:
            self.logger.info("视频保存并校验通过：%s", final_path)
            self.message.emit("视频已保存并校验通过")
        else:
            warning = f"视频保存异常：{validation_error or '视频文件校验失败'}"
            self.logger.warning("%s，文件=%s", warning, final_path)
            self.warning_message.emit(warning)
            self.message.emit(warning)

        if not validation_warning:
            self._warn_short_video(check_result.duration_seconds)
        self._schedule_video_hash_generation(final_path)
        self._check_disk_space_notice()

    def _hash_check_config(self) -> tuple[bool, str, bool]:
        hash_config = self.config.get("hash_check", {})
        if not isinstance(hash_config, dict):
            hash_config = {}
        enabled = bool(hash_config.get("enabled", True))
        auto_generate = bool(hash_config.get("auto_generate_after_recording", True))
        algorithm = normalize_hash_algorithm(str(hash_config.get("algorithm") or "SHA256"))
        return enabled, algorithm, auto_generate

    def _schedule_video_hash_generation(self, final_path: Path) -> None:
        enabled, algorithm, auto_generate = self._hash_check_config()
        self.logger.info("视频哈希校验配置：enabled=%s, algorithm=%s, auto=%s", enabled, algorithm, auto_generate)
        if not enabled or not auto_generate:
            return
        try:
            if not final_path.exists() or not final_path.is_file():
                self.logger.warning("跳过视频哈希生成：文件不存在，file=%s", final_path)
                return
            if final_path.stat().st_size <= 0:
                self.logger.warning("跳过视频哈希生成：文件大小为 0，file=%s", final_path)
                return
        except OSError as exc:
            self.logger.warning("跳过视频哈希生成：无法读取文件状态，file=%s, error=%s", final_path, exc)
            return

        worker = threading.Thread(
            target=self._generate_video_hash_worker,
            args=(str(final_path), algorithm),
            name="VideoHashWorker",
            daemon=True,
        )
        worker.start()

    def _generate_video_hash_worker(self, file_path: str, algorithm: str) -> None:
        start_time = time.perf_counter()
        database: DatabaseManager | None = None
        record_id = 0
        try:
            path = Path(file_path)
            database = DatabaseManager(self.database_path, self.logger)
            record = database.get_video_by_path(path)
            if record:
                record_id = int(record.get("id") or 0)
            self.logger.info("开始生成视频哈希：record_id=%s, file=%s, algorithm=%s", record_id or "-", path, algorithm)
            self.message.emit("正在生成视频校验码...")
            file_hash = calculate_file_hash(path, algorithm)
            affected = database.update_video_hash_by_path(path, file_hash, algorithm)
            cost_time = time.perf_counter() - start_time
            if affected == 1:
                self.logger.info(
                    "视频哈希生成成功：record_id=%s, algorithm=%s, cost=%.2fs, hash_prefix=%s",
                    record_id or "-",
                    algorithm,
                    cost_time,
                    file_hash[:12],
                )
                self.message.emit("视频校验码已生成")
            else:
                self.logger.warning("视频哈希生成完成但未命中 SQLite 记录：record_id=%s, file=%s", record_id or "-", path)
                self.warning_message.emit("视频校验码生成失败：未找到视频记录")
        except Exception as exc:
            self.logger.exception("视频哈希生成失败：record_id=%s, file=%s", record_id or "-", file_path)
            self.warning_message.emit(f"视频校验码生成失败：{exc}")
        finally:
            if database is not None:
                database.close()

    def _open_camera(self) -> None:
        self._release_camera()
        camera_index = int(self.config.get("camera_index", 0) or 0)

        try:
            capture = open_camera(camera_index)
            apply_capture_settings(capture, self.config)
        except Exception as exc:
            self.logger.exception("摄像头打开失败")
            self._camera_available = False
            self._camera_last_error = f"摄像头打开失败：{exc}"
            self._camera_unhealthy_since = time.perf_counter()
            self._emit_camera_status(False, f"摄像头打开失败：{exc}", force=True)
            self.message.emit(f"摄像头打开失败：{exc}")
            return

        if not capture.isOpened():
            self._camera_available = False
            self._camera_last_error = "摄像头不可用"
            self._camera_unhealthy_since = time.perf_counter()
            self._emit_camera_status(False, "摄像头不可用", force=True)
            self.message.emit("摄像头不可用")
            self.logger.error("摄像头不可用：index=%s", camera_index)
            capture.release()
            return

        self._capture = capture
        width, height = get_capture_size(capture)
        capture_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self._camera_actual_fps = capture_fps if capture_fps > 1 else None
        camera_name = str(self.config.get("camera_name", "") or "")
        if not camera_name:
            camera_name = next(
                (device.name for device in list_camera_devices() if device.index == camera_index),
                f"摄像头 {camera_index}",
            )
        camera_name_lower = camera_name.lower()
        self._ivcam_camera = "ivcam" in camera_name_lower or "e2esoft" in camera_name_lower
        self._camera_fail_count = 0
        self._camera_success_count = 0
        self._camera_available = False
        self._camera_last_error = "等待摄像头画面"
        self._camera_unhealthy_since = time.perf_counter()
        self._camera_confirmed_error = False
        self._camera_pending_error_since = 0.0
        self._camera_pending_recover_since = 0.0
        self._last_frame_ok_at = time.perf_counter()
        self._ivcam_wait_matches = 0
        self._ivcam_waiting = False
        self._ivcam_placeholder_type = ""
        self._ivcam_placeholder_message = ""
        self._ivcam_placeholder_metrics = {}
        self._ivcam_placeholder_first_match_at = 0.0
        self._ivcam_placeholder_last_check_at = 0.0
        self._ivcam_placeholder_last_log_at = 0.0
        self._frame_frozen = False
        self._freeze_sample_at = 0.0
        self._freeze_started_at = time.perf_counter()
        self._last_freeze_sample = None
        self._last_freeze_warning_log_at = 0.0
        self.logger.info(
            "摄像头打开：%s, index=%s, 分辨率=%sx%s, 摄像头实际FPS=%s, 配置目标FPS=%s, iVCam=%s",
            camera_name,
            camera_index,
            width,
            height,
            f"{self._camera_actual_fps:.2f}" if self._camera_actual_fps else "unknown",
            self.config.get("fps", 25),
            self._ivcam_camera,
        )
        self.message.emit("摄像头已打开")

    def _release_camera(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _create_writer(
        self,
        path: Path,
        width: int,
        height: int,
        fps: int,
        extension: str,
    ) -> tuple[cv2.VideoWriter | None, str]:
        codec_candidates = ["mp4v", "avc1", "H264", "X264"] if extension.lower() == "mp4" else ["XVID", "MJPG"]
        for codec in codec_candidates:
            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(str(path), fourcc, float(fps), (width, height))
            if writer.isOpened():
                return writer, codec
            writer.release()
        return None, ""

    def _prepare_frame_for_writer(self, frame: np.ndarray) -> np.ndarray:
        if self._writer_size is None:
            return frame
        width, height = self._writer_size
        if frame.shape[1] == width and frame.shape[0] == height:
            return frame
        return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

    def _recording_frame_size(self, width: int, height: int) -> tuple[int, int]:
        max_long_edge = int(self.config.get("recording_max_long_edge", 1280) or 0)
        if max_long_edge > 0:
            scale = min(1.0, max_long_edge / max(width, height))
            width = int(width * scale)
            height = int(height * scale)

        width = max(2, width - (width % 2))
        height = max(2, height - (height % 2))
        return width, height

    def _current_frame_size(self) -> tuple[int, int]:
        if self._last_frame_size is not None:
            return self._last_frame_size
        if self._capture is not None:
            return get_capture_size(self._capture)
        return 640, 480

    def _update_video_index(self, final_path: Path, recorded_at: datetime | None = None) -> None:
        try:
            record_type = str(self._record_type_for_current_recording or self.config.get("current_record_type") or "发货")
            database = DatabaseManager(self.database_path, self.logger)
            database.upsert_video_file(final_path, record_type=record_type, recorded_at=recorded_at)
            database.close()
            self.logger.info("新录制视频写入 SQLite record_type：%s，%s", record_type, final_path)
        except Exception:
            self.logger.exception("SQLite 视频索引更新失败：%s", final_path)
            self.warning_message.emit("视频已保存，但 SQLite 索引写入失败，请查看日志。")

    def _mark_video_abnormal(self, final_path: Path, reason: str) -> None:
        database: DatabaseManager | None = None
        try:
            now_text = format_datetime()
            database = DatabaseManager(self.database_path, self.logger)
            ok = database.update_video_metadata(
                final_path,
                {
                    "status": "异常",
                    "validation_status": "异常",
                    "validation_error": reason,
                    "validation_warning": "",
                    "validated_at": now_text,
                    "updated_at": now_text,
                },
            )
            if ok:
                self.logger.info("异常视频状态写入 SQLite 成功：%s, reason=%s", final_path, reason)
            else:
                self.logger.warning("异常视频状态写入 SQLite 未命中记录：%s, reason=%s", final_path, reason)
        except Exception:
            self.logger.exception("异常视频状态写入 SQLite 失败：%s", final_path)
        finally:
            if database is not None:
                database.close()

    def _warn_short_video(self, duration_seconds: float) -> None:
        quality_config = self.config.get("recording_quality", {})
        if not isinstance(quality_config, dict) or not bool(quality_config.get("warn_short_video", True)):
            return

        min_duration = float(quality_config.get("min_valid_duration_seconds", 3) or 3)
        if 0 < duration_seconds < min_duration:
            message = "该视频录制时间过短，请确认是否有效。"
            self.logger.warning("异常短视频提醒：时长=%.2f 秒，阈值=%.2f 秒", duration_seconds, min_duration)
            self.warning_message.emit(message)
            self.message.emit(message)

    def _check_disk_space_notice(self) -> None:
        disk_config = self.config.get("disk_space", {})
        if isinstance(disk_config, dict) and not bool(disk_config.get("enabled", True)):
            return

        result = DiskSpaceChecker(self._recording_disk_config(), self.logger).check(self._video_dir())
        if result.level == "critical":
            self.critical_message.emit(result.message)
            self.message.emit(result.message)
        elif result.level == "warning":
            self.warning_message.emit(result.message)
            self.message.emit(result.message)
        elif result.level == "error":
            self.logger.warning(result.message)

    def _recording_disk_config(self) -> dict[str, Any]:
        disk_config = self.config.get("disk_space", {})
        disk_config = dict(disk_config) if isinstance(disk_config, dict) else {}
        disk_config.setdefault("enabled", True)
        disk_config["warning_gb"] = float(disk_config.get("warning_gb", DISK_WARNING_GB) or DISK_WARNING_GB)
        disk_config["critical_gb"] = float(disk_config.get("critical_gb", DISK_CRITICAL_GB) or DISK_CRITICAL_GB)
        return {"disk_space": disk_config}

    def _video_dir(self) -> Path:
        path_value = str(self.config.get("video_root_dir") or self.config.get("video_save_dir") or "videos")
        path = Path(path_value).expanduser()
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()
