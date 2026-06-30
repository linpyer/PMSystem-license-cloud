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
from app.core.disk_space_checker import DiskSpaceChecker
from app.core.video_checker import VideoChecker
from app.utils.filename import unique_temp_recording_path, unique_video_path
from app.utils.time_utils import format_datetime


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
        order_text = f"物流单号：{order_id}"
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

    def __init__(self, config: dict[str, Any], base_dir: Path, logger: logging.Logger) -> None:
        super().__init__()
        self.config = dict(config)
        self.base_dir = Path(base_dir)
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
        self._watermark_error_logged = False

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
                time.sleep(0.05)
                continue

            capture_started = time.perf_counter()
            ok, frame = self._capture.read()
            capture_elapsed = time.perf_counter() - capture_started
            self._perf_capture_count += 1
            self._perf_capture_time_sum += capture_elapsed
            if not ok or frame is None:
                self.camera_status_changed.emit(False, "摄像头不可用")
                self.message.emit("摄像头不可用")
                self.logger.warning("摄像头读取失败")
                self._release_camera()
                time.sleep(0.3)
                continue

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
                    self.message.emit(f"视频保存失败：{exc}")
                    self._stop_recording(save_failed_reason=str(exc))

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
            time.sleep(0.001)

        if self._recording:
            self._stop_recording()
        self._release_camera()

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
            self.logger.info("扫码为空，停止当前录制：物流单号=%s", current_order_id)
            self._stop_recording()
            return

        if order_id == current_order_id:
            self.logger.info("扫描到与当前正在录制单号一致，执行结束录制：%s", order_id)
            self._stop_recording()
            return

        self.logger.info("扫描到新物流单号，切换录制：%s -> %s", current_order_id, order_id)
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
            self.message.emit("请先输入或扫描物流单号")
            return
        self._start_recording(order_id)

    def _handle_manual_stop(self) -> None:
        if self._pending_start_order_id and not self._recording:
            self.logger.info("取消待启动录制：物流单号=%s", self._pending_start_order_id)
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
        if self._capture is None or not self._capture.isOpened():
            self.message.emit("摄像头不可用，无法开始录制")
            self.logger.error("开始录制失败：摄像头不可用")
            return

        video_dir = self._video_dir()
        try:
            video_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.logger.exception("创建视频保存目录失败：%s", video_dir)
            self.message.emit(f"无法创建视频保存目录：{exc}")
            return

        self._check_disk_space_notice()

        extension = str(self.config.get("video_format", "mp4") or "mp4").lower()
        temp_path = unique_temp_recording_path(video_dir, order_id, extension)
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
        self._start_time = datetime.now()
        self._frames_written = 0
        self._frames_enqueued = 0
        self._target_recording_fps = target_fps
        self._effective_recording_fps = fps
        self._record_interval = 1.0 / max(1, fps)
        self._next_record_frame_at = 0.0
        self._next_preview_frame_at = 0.0
        self._reset_performance_window()

        self.logger.info(
            "开始录制：物流单号=%s, 临时文件=%s, 编码=%s, 配置FPS=%s, 写入FPS=%s, 摄像头实际FPS=%s, 队列容量=%s",
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
        final_path = unique_video_path(self._video_dir(), order_id, extension, started_at)
        recording_ended_at = datetime.now()

        self.logger.info("停止录制：物流单号=%s", order_id)

        writer_snapshot: dict[str, float | int | str] = {}
        if writer_worker is not None:
            writer_worker.stop_and_wait()
            writer_snapshot = writer_worker.snapshot(reset_window=False)

        frames_written = int(writer_snapshot.get("frames_written", 0) or 0)
        frames_dropped = int(writer_snapshot.get("frames_dropped", 0) or 0)
        if writer_snapshot.get("error") and not save_failed_reason:
            save_failed_reason = str(writer_snapshot.get("error"))

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

        if save_failed_reason:
            self.logger.error("视频保存失败：%s", save_failed_reason)
            self.message.emit(f"视频保存失败：{save_failed_reason}")
            return

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
                "录制文件大小或帧数异常，仍保留文件等待完整性校验：物流单号=%s，帧数=%s，大小=%s，临时文件=%s",
                order_id,
                frames_written,
                temp_size,
                temp_path,
            )

        try:
            temp_path.rename(final_path)
        except OSError as exc:
            self.logger.exception("视频保存失败")
            self.message.emit(f"视频保存失败：{exc}")
            return

        duration_seconds = 0
        if started_at is not None:
            duration_seconds = max(0, int((recording_ended_at - started_at).total_seconds()))
        self.logger.info("录制时长：物流单号=%s，时长=%s 秒", order_id, duration_seconds)
        avg_record_fps = frames_written / max(0.001, (recording_ended_at - started_at).total_seconds()) if started_at else 0.0
        self.logger.info(
            "录制性能摘要：物流单号=%s, 开始时间=%s, 结束时间=%s, 实际时长=%.2f秒, 配置FPS=%s, 写入FPS=%s, 总帧数=%s, 平均录制FPS=%.2f, 丢帧=%s, 平均写入耗时=%.2fms, 最大写入耗时=%.2fms",
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
        if check_result.is_valid:
            self._update_video_index(final_path, started_at)
            self.logger.info("视频保存成功：%s", final_path)
            self.message.emit(f"视频保存成功：{final_path}")
        else:
            warning = f"视频可能保存异常，请检查文件。{final_path}"
            self.logger.warning("%s，校验信息：%s", warning, check_result.message)
            self.warning_message.emit(warning)
            self.message.emit(warning)

        self._warn_short_video(check_result.duration_seconds)
        self._check_disk_space_notice()

    def _open_camera(self) -> None:
        self._release_camera()
        camera_index = int(self.config.get("camera_index", 0) or 0)

        try:
            capture = open_camera(camera_index)
            apply_capture_settings(capture, self.config)
        except Exception as exc:
            self.logger.exception("摄像头打开失败")
            self.camera_status_changed.emit(False, f"摄像头打开失败：{exc}")
            self.message.emit(f"摄像头打开失败：{exc}")
            return

        if not capture.isOpened():
            self.camera_status_changed.emit(False, "摄像头不可用")
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
        self.logger.info(
            "摄像头打开：%s, index=%s, 分辨率=%sx%s, 摄像头实际FPS=%s, 配置目标FPS=%s",
            camera_name,
            camera_index,
            width,
            height,
            f"{self._camera_actual_fps:.2f}" if self._camera_actual_fps else "unknown",
            self.config.get("fps", 25),
        )
        self.camera_status_changed.emit(True, f"摄像头已打开：{camera_name}（索引 {camera_index}），{width}x{height}")
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
            database = DatabaseManager(self.base_dir / "pm_system.db", self.logger)
            database.upsert_video_file(final_path, record_type=record_type, recorded_at=recorded_at)
            database.close()
            self.logger.info("新录制视频写入 SQLite record_type：%s，%s", record_type, final_path)
        except Exception:
            self.logger.exception("SQLite 视频索引更新失败：%s", final_path)
            self.warning_message.emit("视频已保存，但 SQLite 索引写入失败，请查看日志。")

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

        result = DiskSpaceChecker(self.config, self.logger).check(self._video_dir())
        if result.level == "critical":
            self.critical_message.emit(result.message)
            self.message.emit(result.message)
        elif result.level == "warning":
            self.warning_message.emit(result.message)
            self.message.emit(result.message)
        elif result.level == "error":
            self.logger.warning(result.message)

    def _video_dir(self) -> Path:
        path_value = str(self.config.get("video_save_dir", "videos"))
        path = Path(path_value).expanduser()
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()
