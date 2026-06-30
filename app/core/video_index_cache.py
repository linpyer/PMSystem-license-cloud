from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import cv2

from app.core.file_indexer import VIDEO_EXTENSIONS
from app.core.video_checker import VideoChecker
from app.utils.file_utils import human_file_size
from app.utils.filename import tracking_number_from_video_name
from app.utils.time_utils import format_datetime


INDEX_VERSION = "1.0"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_RECORD_TYPE = "发货"
VALID_RECORD_TYPES = {"发货", "退货"}


class VideoIndexCache:
    def __init__(self, index_path: str | Path, logger: logging.Logger | None = None) -> None:
        self.index_path = Path(index_path)
        self.logger = logger
        self.items: list[dict[str, Any]] = []
        self.last_load_failed = False

    def load_index(self) -> dict[str, Any]:
        self.last_load_failed = False
        if not self.index_path.exists():
            self.items = []
            return self._payload()

        try:
            with self.index_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            items = payload.get("items", [])
            self.items = [dict(item) for item in items if isinstance(item, dict)]
            changed = self.apply_default_fields()
            if self.apply_duplicate_info():
                changed = True
            if changed:
                self.save_index()
            return self._payload(payload.get("last_updated"))
        except (OSError, json.JSONDecodeError) as exc:
            self.last_load_failed = True
            self._backup_broken_index(exc)
            self.items = []
            return self._payload()

    def save_index(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.apply_default_fields()
        self.apply_duplicate_info()
        payload = self._payload()
        with self.index_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        if self.logger:
            self.logger.info("视频索引缓存更新：%s，数量=%s", self.index_path, len(self.items))

    def rebuild_from_folder(self, video_dir: str | Path) -> list[dict[str, Any]]:
        directory = Path(video_dir)
        directory.mkdir(parents=True, exist_ok=True)
        items: list[dict[str, Any]] = []
        for path in directory.iterdir():
            if not self._is_video_file(path):
                continue
            items.append(self._build_item(path))
        self.items = self._sort_items(items)
        self.save_index()
        if self.logger:
            self.logger.info("查询页刷新并重建视频索引：目录=%s，数量=%s", directory, len(self.items))
        return list(self.items)

    def add_or_update_video(self, file_path: str | Path, record_type: str | None = None) -> dict[str, Any] | None:
        path = Path(file_path)
        if not self._is_video_file(path):
            return None
        self.load_index()
        path_text = str(path)
        existing = next((old for old in self.items if str(old.get("file_path", "")) == path_text), {})
        item = self._build_item(
            path,
            record_type=record_type or str(existing.get("record_type") or DEFAULT_RECORD_TYPE),
            remark=str(existing.get("remark") or ""),
        )
        self.items = [old for old in self.items if str(old.get("file_path", "")) != path_text]
        self.items.append(item)
        self.items = self._sort_items(self.items)
        self.save_index()
        return item

    def update_video_fields(self, file_path: str | Path, fields: dict[str, Any]) -> bool:
        path_text = str(Path(file_path))
        changed = False
        for item in self.items:
            if str(item.get("file_path", "")) != path_text:
                continue
            if "record_type" in fields:
                value = self.normalize_record_type(fields.get("record_type"))
                if item.get("record_type") != value:
                    item["record_type"] = value
                    changed = True
            if "remark" in fields:
                value = str(fields.get("remark") or "")[:500]
                if item.get("remark") != value:
                    item["remark"] = value
                    changed = True
            if changed:
                self.save_index()
            return True
        return False

    def remove_missing_files(self) -> None:
        self.load_index()
        original_count = len(self.items)
        self.items = [item for item in self.items if Path(str(item.get("file_path", ""))).exists()]
        if len(self.items) != original_count:
            self.save_index()
        elif self.apply_duplicate_info():
            self.save_index()

    def search(
        self,
        keyword: str = "",
        date_from: date | None = None,
        date_to: date | None = None,
        record_type: str | None = None,
    ) -> list[dict[str, Any]]:
        keyword = keyword.strip().lower()
        normalized_record_type = self.normalize_record_type(record_type) if record_type else None
        rows: list[dict[str, Any]] = []
        for item in self.items:
            if normalized_record_type and self.normalize_record_type(item.get("record_type")) != normalized_record_type:
                continue
            if keyword and not self._matches_keyword(item, keyword):
                continue

            recorded_at = parse_datetime(self.recording_time_text(item))
            if recorded_at is not None:
                recorded_date = recorded_at.date()
                if date_from and recorded_date < date_from:
                    continue
                if date_to and recorded_date > date_to:
                    continue
            elif date_from or date_to:
                continue

            rows.append(item)
        return self._sort_items(rows)

    def get_all_items(self) -> list[dict[str, Any]]:
        return self._sort_items(list(self.items))

    def count_order_no(self, order_no: str) -> int:
        self.apply_default_fields()
        self.apply_duplicate_info()
        order_no = order_no.strip()
        if not order_no:
            return 0
        return sum(
            1
            for item in self.items
            if bool(item.get("exists", True)) and str(item.get("order_no", "")).strip() == order_no
        )

    def apply_default_fields(self) -> bool:
        changed = False
        for item in self.items:
            record_type = self.normalize_record_type(item.get("record_type"))
            if item.get("record_type") != record_type:
                item["record_type"] = record_type
                changed = True

            if "remark" not in item or item.get("remark") is None:
                item["remark"] = ""
                changed = True

            if not item.get("order_no"):
                item["order_no"] = tracking_number_from_video_name(str(item.get("file_name", "")))
                changed = True

            if not item.get("recording_time"):
                item["recording_time"] = self.recording_time_text(item)
                changed = True

            path = Path(str(item.get("file_path", "")))
            exists = path.exists()
            if item.get("exists") != exists:
                item["exists"] = exists
                changed = True

            if not item.get("resolution") or not item.get("codec"):
                resolution = "-"
                codec = "-"
                if exists:
                    resolution, codec = self._read_video_metadata(path)
                if item.get("resolution") != resolution:
                    item["resolution"] = resolution
                    changed = True
                if item.get("codec") != codec:
                    item["codec"] = codec
                    changed = True

        if changed and self.logger:
            self.logger.info("索引缺失字段自动补齐: %s", self.index_path)
        return changed

    @staticmethod
    def normalize_record_type(value: Any) -> str:
        text = str(value or "").strip()
        return text if text in VALID_RECORD_TYPES else DEFAULT_RECORD_TYPE

    @staticmethod
    def recording_time_text(item: dict[str, Any]) -> str:
        return str(
            item.get("recording_time")
            or item.get("recorded_at")
            or item.get("created_time")
            or item.get("modified_time")
            or ""
        )

    def apply_duplicate_info(self) -> bool:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in self.items:
            order_no = str(item.get("order_no", "")).strip()
            if not order_no or not bool(item.get("exists", True)):
                continue
            groups.setdefault(order_no, []).append(item)

        duplicate_meta: dict[int, tuple[int, int, bool]] = {}
        for order_no, rows in groups.items():
            rows.sort(key=self._sequence_sort_key)
            count = len(rows)
            for index, item in enumerate(rows, 1):
                duplicate_meta[id(item)] = (count, index, count > 1)

        changed = False
        for item in self.items:
            count, sequence, is_duplicate = duplicate_meta.get(id(item), (0, 0, False))
            if item.get("duplicate_count") != count:
                item["duplicate_count"] = count
                changed = True
            if item.get("duplicate_sequence") != sequence:
                item["duplicate_sequence"] = sequence
                changed = True
            if item.get("is_duplicate") != is_duplicate:
                item["is_duplicate"] = is_duplicate
                changed = True

        if changed and self.logger:
            self.logger.info("索引缓存更新重复录制字段：%s", self.index_path)
            self.logger.info("计算重复录制序号：%s", self.index_path)
        return changed

    def _build_item(self, path: Path, record_type: str | None = None, remark: str = "") -> dict[str, Any]:
        exists = path.exists()
        file_size = 0
        created_time = ""
        modified_time = ""
        duration_seconds = 0.0
        resolution = "-"
        codec = "-"

        if exists:
            try:
                stat_result = path.stat()
                file_size = stat_result.st_size
                created_time = format_datetime(datetime.fromtimestamp(stat_result.st_ctime or stat_result.st_mtime))
                modified_time = format_datetime(datetime.fromtimestamp(stat_result.st_mtime))
            except OSError:
                exists = False

        if exists:
            check = VideoChecker(self.logger).check_video(path)
            duration_seconds = float(check.duration_seconds or 0.0)
            resolution, codec = self._read_video_metadata(path)

        return {
            "order_no": tracking_number_from_video_name(path.name),
            "file_name": path.name,
            "file_format": path.suffix.lstrip(".").upper(),
            "file_size": file_size,
            "file_size_text": human_file_size(file_size),
            "recording_time": created_time,
            "created_time": created_time,
            "modified_time": modified_time,
            "duration_seconds": duration_seconds,
            "resolution": resolution,
            "codec": codec,
            "record_type": self.normalize_record_type(record_type),
            "remark": remark or "",
            "file_path": str(path),
            "exists": exists,
            "is_duplicate": False,
            "duplicate_count": 0,
            "duplicate_sequence": 0,
        }

    def _read_video_metadata(self, path: Path) -> tuple[str, str]:
        capture = None
        try:
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                if self.logger:
                    self.logger.warning("读取视频分辨率失败: %s", path)
                return "-", "-"

            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fourcc_value = int(capture.get(cv2.CAP_PROP_FOURCC) or 0)
            resolution = f"{width} x {height}" if width > 0 and height > 0 else "-"
            codec = self._decode_fourcc(fourcc_value)
            if self.logger:
                self.logger.info("读取视频分辨率成功: %s %s %s", path, resolution, codec)
            return resolution, codec
        except Exception:
            if self.logger:
                self.logger.exception("读取视频编码失败: %s", path)
            return "-", "-"
        finally:
            if capture is not None:
                capture.release()

    def _payload(self, last_updated: str | None = None) -> dict[str, Any]:
        return {
            "version": INDEX_VERSION,
            "last_updated": last_updated or format_datetime(),
            "items": self._sort_items(self.items),
        }

    def _backup_broken_index(self, exc: Exception) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.index_path.with_name(f"{self.index_path.stem}.broken_{timestamp}{self.index_path.suffix}")
        try:
            shutil.copy2(self.index_path, backup_path)
        except OSError:
            if self.logger:
                self.logger.exception("视频索引缓存损坏且备份失败：%s", self.index_path)
        if self.logger:
            self.logger.warning("视频索引缓存损坏，已准备重建：%s，原因：%s", self.index_path, exc)

    @staticmethod
    def _is_video_file(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and ".recording." not in path.name

    @staticmethod
    def _matches_keyword(item: dict[str, Any], keyword: str) -> bool:
        values = [
            str(item.get("order_no", "")),
            str(item.get("file_name", "")),
            str(item.get("remark", "")),
            str(item.get("file_path", "")),
        ]
        return any(keyword in value.lower() for value in values)

    @staticmethod
    def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: parse_datetime(VideoIndexCache.recording_time_text(item)) or datetime.min,
            reverse=True,
        )

    @staticmethod
    def _sequence_sort_key(item: dict[str, Any]) -> tuple[datetime, str]:
        recorded_at = (
            parse_datetime(VideoIndexCache.recording_time_text(item))
            or parse_datetime(str(item.get("modified_time", "")))
            or datetime.min
        )
        return recorded_at, str(item.get("file_name", ""))

    @staticmethod
    def _decode_fourcc(value: int) -> str:
        if not value:
            return "-"
        raw = "".join(chr((value >> (8 * index)) & 0xFF) for index in range(4)).strip("\x00 ").strip()
        mapping = {
            "avc1": "H.264",
            "H264": "H.264",
            "h264": "H.264",
            "X264": "H.264",
            "mp4v": "mp4v",
            "XVID": "XVID",
            "MJPG": "MJPG",
        }
        return mapping.get(raw, raw or "-")


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, DATETIME_FORMAT)
    except ValueError:
        return None
