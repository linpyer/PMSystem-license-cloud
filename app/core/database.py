from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import cv2

from app.core.file_indexer import VIDEO_EXTENSIONS
from app.core.video_checker import VideoChecker
from app.utils.file_utils import human_file_size
from app.utils.filename import tracking_number_from_video_name
from app.utils.time_utils import format_datetime, format_duration


DEFAULT_RECORD_TYPE = "发货"
VALID_RECORD_TYPES = {"发货", "退货"}
MISSING_STATUS = "文件不存在"
NORMAL_STATUS = "正常"
ERROR_STATUS = "异常"


class DatabaseManager:
    def __init__(self, db_path: str | Path, logger: logging.Logger | None = None) -> None:
        self.db_path = Path(db_path)
        self.logger = logger
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self.last_query_truncated = False
        self.init_db()

    def init_db(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self.get_connection()
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self.create_tables()
            if self.logger:
                self.logger.info("SQLite 数据库初始化成功：%s", self.db_path)
        except Exception:
            if self.logger:
                self.logger.exception("SQLite 数据库初始化失败：%s", self.db_path)
            raise

    def get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            if self.logger:
                self.logger.info("SQLite 数据库路径：%s", self.db_path)
            self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def create_tables(self) -> None:
        with self._lock:
            connection = self.get_connection()
            try:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS videos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        order_no TEXT NOT NULL,
                        file_name TEXT NOT NULL,
                        file_path TEXT NOT NULL UNIQUE,
                        file_ext TEXT,
                        file_size_bytes INTEGER DEFAULT 0,
                        file_size_text TEXT,
                        duration_seconds REAL DEFAULT 0,
                        duration_text TEXT,
                        width INTEGER DEFAULT 0,
                        height INTEGER DEFAULT 0,
                        resolution TEXT,
                        codec TEXT,
                        fps REAL DEFAULT 0,
                        record_type TEXT NOT NULL DEFAULT '发货',
                        remark TEXT DEFAULT '',
                        status TEXT DEFAULT '正常',
                        recorded_at TEXT,
                        created_time TEXT,
                        updated_at TEXT,
                        is_duplicate INTEGER DEFAULT 0,
                        duplicate_count INTEGER DEFAULT 1,
                        duplicate_sequence INTEGER DEFAULT 1
                    );

                    CREATE INDEX IF NOT EXISTS idx_videos_order_no ON videos(order_no);
                    CREATE INDEX IF NOT EXISTS idx_videos_recorded_at ON videos(recorded_at);
                    CREATE INDEX IF NOT EXISTS idx_videos_record_type ON videos(record_type);
                    CREATE INDEX IF NOT EXISTS idx_videos_file_path ON videos(file_path);
                    CREATE INDEX IF NOT EXISTS idx_videos_file_name ON videos(file_name);
                    CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
                    """
                )
                connection.commit()
                if self.logger:
                    self.logger.info("创建 videos 表和索引成功")
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("创建 videos 表或索引失败")
                raise

    def insert_video_record(self, record: dict[str, Any]) -> None:
        self.upsert_video_record(record)

    def upsert_video_record(self, record: dict[str, Any]) -> None:
        fields = [
            "order_no",
            "file_name",
            "file_path",
            "file_ext",
            "file_size_bytes",
            "file_size_text",
            "duration_seconds",
            "duration_text",
            "width",
            "height",
            "resolution",
            "codec",
            "fps",
            "record_type",
            "remark",
            "status",
            "recorded_at",
            "created_time",
            "updated_at",
            "is_duplicate",
            "duplicate_count",
            "duplicate_sequence",
        ]
        normalized = {field: record.get(field) for field in fields}
        normalized["record_type"] = self.normalize_record_type(normalized.get("record_type"))
        normalized["remark"] = str(normalized.get("remark") or "")[:500]

        placeholders = ", ".join("?" for _ in fields)
        field_list = ", ".join(fields)
        update_list = ", ".join(f"{field}=excluded.{field}" for field in fields if field != "file_path")
        values = [normalized.get(field) for field in fields]

        with self._lock:
            connection = self.get_connection()
            try:
                connection.execute(
                    f"""
                    INSERT INTO videos ({field_list})
                    VALUES ({placeholders})
                    ON CONFLICT(file_path) DO UPDATE SET {update_list}
                    """,
                    values,
                )
                connection.commit()
                if self.logger:
                    self.logger.info("插入或更新视频记录成功：%s", normalized.get("file_path"))
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("插入或更新视频记录失败并 rollback：%s", normalized.get("file_path"))
                raise

    def upsert_video_file(
        self,
        file_path: str | Path,
        record_type: str | None = None,
        recorded_at: datetime | str | None = None,
        order_no: str | None = None,
    ) -> dict[str, Any] | None:
        path = Path(file_path).resolve()
        if not self._is_video_file(path):
            return None

        existing = self.get_video_by_path(path)
        preserved_type = record_type
        preserved_remark = ""
        if existing:
            preserved_type = record_type or str(existing.get("record_type") or DEFAULT_RECORD_TYPE)
            preserved_remark = str(existing.get("remark") or "")

        record = self._build_record_from_file(
            path,
            record_type=preserved_type,
            remark=preserved_remark,
            recorded_at=recorded_at,
            order_no=order_no,
        )
        self.upsert_video_record(record)
        self.recalculate_duplicate_sequences(str(record.get("order_no") or ""))
        return record

    def update_video_metadata(self, file_path: str | Path, metadata: dict[str, Any]) -> bool:
        allowed = {
            "file_size_bytes",
            "file_size_text",
            "duration_seconds",
            "duration_text",
            "width",
            "height",
            "resolution",
            "codec",
            "fps",
            "status",
            "updated_at",
        }
        updates = {key: value for key, value in metadata.items() if key in allowed}
        if not updates:
            return False
        return self._update_fields(file_path, updates, "更新视频元数据")

    def update_record_type(self, file_path: str | Path, record_type: str) -> bool:
        record_type = self.normalize_record_type(record_type)
        ok = self._update_fields(
            file_path,
            {"record_type": record_type, "updated_at": format_datetime()},
            "修改发货/退货类型",
        )
        if ok and self.logger:
            self.logger.info("修改发货/退货类型成功：%s -> %s", file_path, record_type)
        return ok

    def update_remark(self, file_path: str | Path, remark: str) -> bool:
        remark = str(remark or "")[:500]
        ok = self._update_fields(
            file_path,
            {"remark": remark, "updated_at": format_datetime()},
            "修改备注",
        )
        if ok and self.logger:
            self.logger.info("修改备注成功：%s", file_path)
        return ok

    def delete_video_record(self, file_path: str | Path) -> bool:
        path_text = str(Path(file_path).resolve())
        existing = self.get_video_by_path(path_text)
        order_no = str(existing.get("order_no") or "") if existing else ""
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute("DELETE FROM videos WHERE file_path = ?", (path_text,))
                connection.commit()
                if order_no:
                    self.recalculate_duplicate_sequences(order_no)
                if self.logger:
                    self.logger.info("删除 SQLite 视频记录成功：%s", path_text)
                return cursor.rowcount > 0
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("删除 SQLite 视频记录失败并 rollback：%s", path_text)
                raise

    def mark_file_missing(self, file_path: str | Path) -> bool:
        ok = self._update_fields(
            file_path,
            {"status": MISSING_STATUS, "updated_at": format_datetime()},
            "标记文件不存在",
        )
        if ok and self.logger:
            self.logger.warning("标记文件不存在：%s", file_path)
        return ok

    def query_videos(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        started = time.perf_counter()
        conditions, params = self._video_filter_conditions(filters)

        limit = int(filters.get("limit") or 1000)
        limit = max(1, min(limit, 5000))
        offset = int(filters.get("offset") or 0)
        offset = max(0, offset)
        params.extend([limit, offset])

        sql = f"""
            SELECT *
            FROM videos
            WHERE {' AND '.join(conditions)}
            ORDER BY
                COALESCE(NULLIF(recorded_at, ''), NULLIF(created_time, ''), printf('%012d', id)) DESC,
                id DESC
            LIMIT ? OFFSET ?
        """
        try:
            rows = [self._row_to_item(row) for row in self.get_connection().execute(sql, params).fetchall()]
            self.last_query_truncated = False
            elapsed_ms = (time.perf_counter() - started) * 1000
            if self.logger:
                self.logger.info(
                    "查询视频列表成功：数量=%s, limit=%s, offset=%s, 耗时=%.2fms, filters=%s",
                    len(rows),
                    limit,
                    offset,
                    elapsed_ms,
                    filters,
                )
            return rows
        except Exception:
            if self.logger:
                self.logger.exception("查询视频列表失败：filters=%s", filters)
            return []

    def count_videos(self, filters: dict[str, Any] | None = None) -> int:
        filters = filters or {}
        started = time.perf_counter()
        conditions, params = self._video_filter_conditions(filters)
        sql = f"SELECT COUNT(*) AS total FROM videos WHERE {' AND '.join(conditions)}"
        try:
            row = self.get_connection().execute(sql, params).fetchone()
            total = int(row["total"] if row else 0)
            if self.logger:
                self.logger.info(
                    "统计视频列表总数成功：数量=%s, 耗时=%.2fms, filters=%s",
                    total,
                    (time.perf_counter() - started) * 1000,
                    filters,
                )
            return total
        except Exception:
            if self.logger:
                self.logger.exception("统计视频列表总数失败：filters=%s", filters)
            return 0

    def rebuild_from_video_directory(self, video_dir: str | Path) -> list[dict[str, Any]]:
        return self.refresh_video_directory(video_dir)

    def refresh_video_directory(self, video_dir: str | Path) -> list[dict[str, Any]]:
        directory = Path(video_dir)
        started = time.perf_counter()
        if self.logger:
            self.logger.info("刷新目录扫描开始：%s", directory)
        directory.mkdir(parents=True, exist_ok=True)

        scanned_paths: set[str] = set()
        for path in directory.rglob("*"):
            if not self._is_video_file(path):
                continue
            resolved = str(path.resolve())
            scanned_paths.add(resolved)
            try:
                self.upsert_video_file(path)
            except Exception:
                if self.logger:
                    self.logger.exception("刷新目录时写入视频记录失败：%s", path)

        for row in self.query_videos({"query_dir": directory, "limit": 5000}):
            path = Path(str(row.get("file_path", "")))
            if str(path.resolve()) not in scanned_paths and not path.exists():
                try:
                    self.mark_file_missing(path)
                except Exception:
                    if self.logger:
                        self.logger.exception("标记文件不存在失败：%s", path)

        self.recalculate_duplicate_sequences()
        rows = self.query_videos({"query_dir": directory, "limit": 5000})
        elapsed_ms = (time.perf_counter() - started) * 1000
        if self.logger:
            self.logger.info("刷新目录扫描结束：%s，记录数=%s，耗时=%.2fms", directory, len(rows), elapsed_ms)
        return rows

    def recalculate_duplicate_sequences(self, order_no: str | None = None) -> None:
        with self._lock:
            connection = self.get_connection()
            try:
                if order_no:
                    order_numbers = [order_no]
                else:
                    order_numbers = [
                        str(row["order_no"])
                        for row in connection.execute(
                            "SELECT DISTINCT order_no FROM videos WHERE order_no IS NOT NULL AND order_no <> ''"
                        ).fetchall()
                    ]

                for current_order_no in order_numbers:
                    rows = connection.execute(
                        """
                        SELECT id
                        FROM videos
                        WHERE order_no = ? AND status <> ?
                        ORDER BY
                            COALESCE(NULLIF(recorded_at, ''), NULLIF(created_time, ''), printf('%012d', id)) ASC,
                            file_name ASC,
                            id ASC
                        """,
                        (current_order_no, MISSING_STATUS),
                    ).fetchall()
                    count = len(rows)
                    for sequence, row in enumerate(rows, start=1):
                        connection.execute(
                            """
                            UPDATE videos
                            SET duplicate_count = ?,
                                duplicate_sequence = ?,
                                is_duplicate = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (count or 1, sequence, 1 if count > 1 else 0, format_datetime(), int(row["id"])),
                        )
                    connection.execute(
                        """
                        UPDATE videos
                        SET duplicate_count = 0,
                            duplicate_sequence = 0,
                            is_duplicate = 0,
                            updated_at = ?
                        WHERE order_no = ? AND status = ?
                        """,
                        (format_datetime(), current_order_no, MISSING_STATUS),
                    )
                connection.commit()
                if self.logger:
                    self.logger.info("重复录制序号重新计算：order_no=%s", order_no or "<全部>")
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("重复录制序号重新计算失败并 rollback：order_no=%s", order_no or "<全部>")
                raise

    def count_order_no(self, order_no: str, video_dir: str | Path | None = None) -> int:
        order_no = str(order_no or "").strip()
        if not order_no:
            return 0
        conditions = ["order_no = ?", "status <> ?"]
        params: list[Any] = [order_no, MISSING_STATUS]
        if video_dir:
            prefix = str(Path(video_dir).resolve()).rstrip("\\/")
            conditions.append("(file_path = ? OR file_path LIKE ?)")
            params.extend([prefix, prefix + "\\%"])
        sql = f"SELECT COUNT(*) AS total FROM videos WHERE {' AND '.join(conditions)}"
        try:
            row = self.get_connection().execute(sql, params).fetchone()
            return int(row["total"] if row else 0)
        except Exception:
            if self.logger:
                self.logger.exception("查询重复单号记录数失败：order_no=%s", order_no)
            return 0

    def get_recent_videos(self, video_dir: str | Path | None = None, limit: int = 3) -> list[dict[str, Any]]:
        started = time.perf_counter()
        conditions = ["status = ?"]
        params: list[Any] = [NORMAL_STATUS]
        if video_dir:
            prefix = str(Path(video_dir).resolve()).rstrip("\\/")
            conditions.append("(file_path = ? OR file_path LIKE ?)")
            params.extend([prefix, prefix + "\\%"])
        limit = max(1, min(int(limit or 3), 10))
        params.append(limit)
        sql = f"""
            SELECT *
            FROM videos
            WHERE {' AND '.join(conditions)}
            ORDER BY
                COALESCE(NULLIF(recorded_at, ''), NULLIF(created_time, ''), printf('%012d', id)) DESC,
                id DESC
            LIMIT ?
        """
        try:
            rows = [self._row_to_item(row) for row in self.get_connection().execute(sql, params).fetchall()]
            if self.logger:
                self.logger.info(
                    "最近录制查询成功：dir=%s, 数量=%s, 耗时=%.2fms",
                    video_dir or "<全部>",
                    len(rows),
                    (time.perf_counter() - started) * 1000,
                )
            return rows
        except Exception:
            if self.logger:
                self.logger.exception("最近录制查询失败：dir=%s", video_dir or "<全部>")
            return []

    def get_video_by_path(self, file_path: str | Path) -> dict[str, Any] | None:
        row = self.get_connection().execute(
            "SELECT * FROM videos WHERE file_path = ?",
            (str(Path(file_path).resolve()),),
        ).fetchone()
        return self._row_to_item(row) if row else None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _video_filter_conditions(self, filters: dict[str, Any]) -> tuple[list[str], list[Any]]:
        conditions = ["1=1"]
        params: list[Any] = []

        query_dir = filters.get("query_dir")
        if query_dir:
            prefix = str(Path(str(query_dir)).resolve()).rstrip("\\/")
            conditions.append("(file_path = ? OR file_path LIKE ?)")
            params.extend([prefix, prefix + "\\%"])

        keyword = str(filters.get("keyword") or "").strip()
        if keyword:
            like = f"%{keyword}%"
            conditions.append("(order_no LIKE ? OR file_name LIKE ? OR remark LIKE ?)")
            params.extend([like, like, like])

        date_start = filters.get("date_start")
        if date_start:
            conditions.append("recorded_at >= ?")
            params.append(self._date_start_text(date_start))

        date_end = filters.get("date_end")
        if date_end:
            conditions.append("recorded_at <= ?")
            params.append(self._date_end_text(date_end))

        record_type = filters.get("record_type")
        if record_type:
            conditions.append("record_type = ?")
            params.append(self.normalize_record_type(record_type))

        return conditions, params

    def _update_fields(self, file_path: str | Path, values: dict[str, Any], action_name: str) -> bool:
        if not values:
            return False
        path_text = str(Path(file_path).resolve())
        assignments = ", ".join(f"{key} = ?" for key in values)
        params = list(values.values()) + [path_text]
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(f"UPDATE videos SET {assignments} WHERE file_path = ?", params)
                connection.commit()
                if cursor.rowcount <= 0 and self.logger:
                    self.logger.warning("%s 失败：数据库记录不存在，path=%s", action_name, path_text)
                return cursor.rowcount > 0
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("%s 失败并 rollback：path=%s", action_name, path_text)
                raise

    def _build_record_from_file(
        self,
        path: Path,
        record_type: str | None = None,
        remark: str = "",
        recorded_at: datetime | str | None = None,
        order_no: str | None = None,
    ) -> dict[str, Any]:
        now_text = format_datetime()
        exists = path.exists()
        file_size = 0
        created_time = ""
        status = MISSING_STATUS
        duration_seconds = 0.0
        duration_text = "-"
        width = 0
        height = 0
        resolution = "-"
        codec = "-"
        fps = 0.0

        if exists:
            try:
                stat_result = path.stat()
                file_size = int(stat_result.st_size)
                created_time = format_datetime(datetime.fromtimestamp(stat_result.st_ctime or stat_result.st_mtime))
            except OSError:
                exists = False

        if exists:
            check = VideoChecker(self.logger).check_video(path)
            duration_seconds = float(check.duration_seconds or 0.0)
            duration_text = format_duration(int(round(duration_seconds))) if duration_seconds > 0 else "-"
            status = NORMAL_STATUS if check.is_valid else ERROR_STATUS
            width, height, resolution, codec, fps = self._read_video_metadata(path)

        recorded_text = self._datetime_text(recorded_at) or created_time or now_text
        return {
            "order_no": order_no or tracking_number_from_video_name(path.name),
            "file_name": path.name,
            "file_path": str(path.resolve()),
            "file_ext": path.suffix.lower().lstrip("."),
            "file_size_bytes": file_size,
            "file_size_text": human_file_size(file_size),
            "duration_seconds": duration_seconds,
            "duration_text": duration_text,
            "width": width,
            "height": height,
            "resolution": resolution,
            "codec": codec,
            "fps": fps,
            "record_type": self.normalize_record_type(record_type),
            "remark": remark or "",
            "status": status,
            "recorded_at": recorded_text,
            "created_time": created_time or now_text,
            "updated_at": now_text,
            "is_duplicate": 0,
            "duplicate_count": 1,
            "duplicate_sequence": 1,
        }

    def _read_video_metadata(self, path: Path) -> tuple[int, int, str, str, float]:
        capture = None
        try:
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                if self.logger:
                    self.logger.warning("读取视频分辨率失败：%s", path)
                return 0, 0, "-", "-", 0.0
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fourcc_value = int(capture.get(cv2.CAP_PROP_FOURCC) or 0)
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            resolution = f"{width} x {height}" if width > 0 and height > 0 else "-"
            codec = self._decode_fourcc(fourcc_value)
            if self.logger:
                self.logger.info("读取视频分辨率成功：%s %s %s", path, resolution, codec)
            return width, height, resolution, codec, fps
        except Exception:
            if self.logger:
                self.logger.exception("读取视频编码失败：%s", path)
            return 0, 0, "-", "-", 0.0
        finally:
            if capture is not None:
                capture.release()

    def _row_to_item(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["exists"] = item.get("status") != MISSING_STATUS
        item["is_duplicate"] = bool(item.get("is_duplicate"))
        item["file_format"] = str(item.get("file_ext") or "").upper()
        item["recording_time"] = item.get("recorded_at") or item.get("created_time") or ""
        item["duration_text"] = item.get("duration_text") or self._duration_text(item)
        item["file_size_text"] = item.get("file_size_text") or human_file_size(int(item.get("file_size_bytes") or 0))
        return item

    @staticmethod
    def _is_video_file(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and ".recording." not in path.name

    @staticmethod
    def normalize_record_type(value: Any) -> str:
        text = str(value or "").strip()
        return text if text in VALID_RECORD_TYPES else DEFAULT_RECORD_TYPE

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
            "FMP4": "FMP4",
            "XVID": "XVID",
            "MJPG": "MJPG",
        }
        return mapping.get(raw, raw or "-")

    @staticmethod
    def _datetime_text(value: datetime | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return format_datetime(value)
        return str(value)

    @staticmethod
    def _date_start_text(value: date | str) -> str:
        if isinstance(value, date):
            return f"{value:%Y-%m-%d} 00:00:00"
        return str(value)

    @staticmethod
    def _date_end_text(value: date | str) -> str:
        if isinstance(value, date):
            return f"{value:%Y-%m-%d} 23:59:59"
        return str(value)

    @staticmethod
    def _duration_text(item: dict[str, Any]) -> str:
        seconds = float(item.get("duration_seconds") or 0)
        if seconds <= 0:
            return "-"
        return format_duration(int(round(seconds)))
