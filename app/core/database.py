from __future__ import annotations

import logging
import os
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
UPLOAD_PENDING = "未上传"
UPLOAD_UPLOADING = "上传中"
UPLOAD_DONE = "已上传"
UPLOAD_FAILED = "上传失败"
VALID_UPLOAD_STATUSES = {UPLOAD_PENDING, UPLOAD_UPLOADING, UPLOAD_DONE, UPLOAD_FAILED}
UPLOAD_STATUS_PRIORITY = {
    UPLOAD_PENDING: 1,
    UPLOAD_UPLOADING: 2,
    UPLOAD_FAILED: 3,
    UPLOAD_DONE: 4,
}


def normalize_file_path(path: str | Path | None) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    normalized = os.path.normpath(os.path.abspath(raw))
    if os.name == "nt":
        normalized = os.path.normcase(normalized)
    return normalized.strip()


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
            self.repair_duplicate_video_records()
            self.reset_interrupted_uploads()
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
                        normalized_file_path TEXT,
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
                        is_important INTEGER DEFAULT 0,
                        important_note TEXT DEFAULT '',
                        important_at TEXT,
                        status TEXT DEFAULT '正常',
                        recorded_at TEXT,
                        created_time TEXT,
                        updated_at TEXT,
                        is_duplicate INTEGER DEFAULT 0,
                        duplicate_count INTEGER DEFAULT 1,
                        duplicate_sequence INTEGER DEFAULT 1,
                        upload_status TEXT DEFAULT '未上传',
                        upload_time TEXT,
                        upload_remote_path TEXT,
                        upload_error TEXT,
                        upload_retry_count INTEGER DEFAULT 0,
                        validation_status TEXT DEFAULT '未校验',
                        validation_error TEXT DEFAULT '',
                        validation_warning TEXT DEFAULT '',
                        validated_at TEXT,
                        file_hash TEXT DEFAULT '',
                        hash_algorithm TEXT DEFAULT '',
                        hash_generated_at TEXT DEFAULT '',
                        hash_verify_status TEXT DEFAULT '',
                        hash_verify_at TEXT DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS idx_videos_order_no ON videos(order_no);
                    CREATE INDEX IF NOT EXISTS idx_videos_recorded_at ON videos(recorded_at);
                    CREATE INDEX IF NOT EXISTS idx_videos_record_type ON videos(record_type);
                    CREATE INDEX IF NOT EXISTS idx_videos_file_path ON videos(file_path);
                    CREATE INDEX IF NOT EXISTS idx_videos_file_name ON videos(file_name);
                    CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
                    """
                )
                self._ensure_upload_columns(connection)
                self._sync_normalized_file_paths(connection)
                connection.execute("CREATE INDEX IF NOT EXISTS idx_videos_normalized_file_path ON videos(normalized_file_path)")
                connection.execute("CREATE INDEX IF NOT EXISTS idx_videos_upload_status ON videos(upload_status)")
                connection.commit()
                if self.logger:
                    self.logger.info("创建 videos 表和索引成功")
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("创建 videos 表或索引失败")
                raise

    def _ensure_upload_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(videos)").fetchall()
        }
        required_columns = {
            "upload_status": "TEXT DEFAULT '未上传'",
            "upload_time": "TEXT",
            "upload_remote_path": "TEXT",
            "upload_error": "TEXT",
            "upload_retry_count": "INTEGER DEFAULT 0",
            "validation_status": "TEXT DEFAULT '未校验'",
            "validation_error": "TEXT DEFAULT ''",
            "validation_warning": "TEXT DEFAULT ''",
            "validated_at": "TEXT",
            "file_hash": "TEXT DEFAULT ''",
            "hash_algorithm": "TEXT DEFAULT ''",
            "hash_generated_at": "TEXT DEFAULT ''",
            "hash_verify_status": "TEXT DEFAULT ''",
            "hash_verify_at": "TEXT DEFAULT ''",
            "normalized_file_path": "TEXT",
            "is_important": "INTEGER DEFAULT 0",
            "important_note": "TEXT DEFAULT ''",
            "important_at": "TEXT",
        }
        for column, definition in required_columns.items():
            if column in existing_columns:
                continue
            connection.execute(f"ALTER TABLE videos ADD COLUMN {column} {definition}")
            if self.logger:
                self.logger.info("SQLite 自动迁移 videos.%s 字段成功", column)

    def _sync_normalized_file_paths(self, connection: sqlite3.Connection) -> int:
        rows = connection.execute("SELECT id, file_path, normalized_file_path FROM videos").fetchall()
        updated = 0
        for row in rows:
            normalized = normalize_file_path(row["file_path"])
            if normalized and normalized != str(row["normalized_file_path"] or ""):
                connection.execute(
                    "UPDATE videos SET normalized_file_path = ? WHERE id = ?",
                    (normalized, int(row["id"])),
                )
                updated += 1
        if updated and self.logger:
            self.logger.info("已同步规范化视频路径：%s 条", updated)
        return updated

    def insert_video_record(self, record: dict[str, Any]) -> None:
        self.upsert_video_record(record)

    def upsert_video_record(self, record: dict[str, Any]) -> None:
        fields = [
            "order_no",
            "file_name",
            "file_path",
            "normalized_file_path",
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
            "validation_status",
            "validation_error",
            "validation_warning",
            "validated_at",
        ]
        normalized = {field: record.get(field) for field in fields}
        normalized["record_type"] = self.normalize_record_type(normalized.get("record_type"))
        normalized["remark"] = str(normalized.get("remark") or "")[:500]
        normalized_path = normalize_file_path(normalized.get("file_path"))
        if not normalized_path:
            raise ValueError("视频路径为空，无法写入数据库")
        normalized["normalized_file_path"] = normalized_path
        normalized["file_path"] = str(Path(str(normalized.get("file_path") or normalized_path)).resolve())

        placeholders = ", ".join("?" for _ in fields)
        field_list = ", ".join(fields)
        update_parts: list[str] = []
        for field in fields:
            if field == "file_path":
                continue
            if field == "remark":
                update_parts.append(
                    "remark = CASE "
                    "WHEN excluded.remark IS NULL OR excluded.remark = '' THEN videos.remark "
                    "ELSE excluded.remark END"
                )
            else:
                update_parts.append(f"{field}=excluded.{field}")
        update_list = ", ".join(update_parts)
        values = [normalized.get(field) for field in fields]

        with self._lock:
            connection = self.get_connection()
            try:
                existing = connection.execute(
                    "SELECT id FROM videos WHERE normalized_file_path = ?",
                    (normalized_path,),
                ).fetchone()
                if existing:
                    assignments: list[str] = []
                    update_values: list[Any] = []
                    for field in fields:
                        if field == "file_path":
                            continue
                        if field == "remark":
                            if normalized.get("remark"):
                                assignments.append("remark = ?")
                                update_values.append(normalized.get("remark"))
                            continue
                        assignments.append(f"{field} = ?")
                        update_values.append(normalized.get(field))
                    update_values.append(int(existing["id"]))
                    connection.execute(
                        f"UPDATE videos SET {', '.join(assignments)} WHERE id = ?",
                        update_values,
                    )
                else:
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
            "validation_status",
            "validation_error",
            "validation_warning",
            "validated_at",
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
        return self.update_video_remark_by_path(file_path, remark) == 1

    def update_video_remark_by_path(self, file_path: str | Path, remark: str) -> int:
        remark = str(remark or "")[:500]
        path_text = str(Path(file_path).resolve())
        path_clause, path_params = self._path_match_clause(file_path)
        now_text = format_datetime()
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(
                    f"""
                    UPDATE videos
                    SET remark = ?,
                        updated_at = ?
                    WHERE {path_clause}
                    """,
                    [remark, now_text] + path_params,
                )
                connection.commit()
                if self.logger:
                    self.logger.info(
                        "修改备注提交：db=%s, path=%s, affected=%s, remark_len=%s",
                        self.db_path,
                        path_text,
                        cursor.rowcount,
                        len(remark),
                    )
                return int(cursor.rowcount)
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("修改备注失败并 rollback：db=%s, path=%s, remark_len=%s", self.db_path, path_text, len(remark))
                raise

    def update_video_remark(self, record_id: int, remark: str) -> int:
        remark = str(remark or "")[:500]
        now_text = format_datetime()
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(
                    """
                    UPDATE videos
                    SET remark = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (remark, now_text, int(record_id)),
                )
                connection.commit()
                if self.logger:
                    self.logger.info(
                        "修改备注提交：db=%s, id=%s, affected=%s, remark_len=%s",
                        self.db_path,
                        record_id,
                        cursor.rowcount,
                        len(remark),
                    )
                return int(cursor.rowcount)
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("修改备注失败并 rollback：db=%s, id=%s, remark_len=%s", self.db_path, record_id, len(remark))
                raise

    def update_video_importance(self, record_id: int, is_important: bool, note: str = "") -> int:
        note = str(note or "").strip()[:500]
        now_text = format_datetime()
        with self._lock:
            connection = self.get_connection()
            try:
                if is_important:
                    cursor = connection.execute(
                        """
                        UPDATE videos
                        SET is_important = 1,
                            important_note = ?,
                            important_at = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (note, now_text, now_text, int(record_id)),
                    )
                else:
                    cursor = connection.execute(
                        """
                        UPDATE videos
                        SET is_important = 0,
                            important_note = '',
                            important_at = '',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now_text, int(record_id)),
                    )
                connection.commit()
                if self.logger:
                    self.logger.info(
                        "修改重要视频标记：db=%s, id=%s, important=%s, affected=%s, note_len=%s",
                        self.db_path,
                        record_id,
                        bool(is_important),
                        cursor.rowcount,
                        len(note),
                    )
                return int(cursor.rowcount)
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception(
                        "修改重要视频标记失败并 rollback：db=%s, id=%s, important=%s, note_len=%s",
                        self.db_path,
                        record_id,
                        bool(is_important),
                        len(note),
                    )
                raise

    def update_video_hash(
        self,
        record_id: int,
        file_hash: str,
        algorithm: str = "SHA256",
        generated_at: str | None = None,
    ) -> int:
        hash_text = str(file_hash or "").strip()
        algorithm_text = str(algorithm or "SHA256").strip().upper()
        generated_at_text = generated_at or format_datetime()
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(
                    """
                    UPDATE videos
                    SET file_hash = ?,
                        hash_algorithm = ?,
                        hash_generated_at = ?,
                        hash_verify_status = '未校验',
                        hash_verify_at = '',
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (hash_text, algorithm_text, generated_at_text, generated_at_text, int(record_id)),
                )
                connection.commit()
                if self.logger:
                    self.logger.info(
                        "视频哈希写入 SQLite：db=%s, id=%s, affected=%s, algorithm=%s, hash_prefix=%s",
                        self.db_path,
                        record_id,
                        cursor.rowcount,
                        algorithm_text,
                        hash_text[:12],
                    )
                return int(cursor.rowcount)
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("视频哈希写入失败并 rollback：db=%s, id=%s", self.db_path, record_id)
                raise

    def update_video_hash_by_path(
        self,
        file_path: str | Path,
        file_hash: str,
        algorithm: str = "SHA256",
        generated_at: str | None = None,
    ) -> int:
        hash_text = str(file_hash or "").strip()
        algorithm_text = str(algorithm or "SHA256").strip().upper()
        generated_at_text = generated_at or format_datetime()
        path_text = str(Path(file_path).resolve())
        path_clause, path_params = self._path_match_clause(file_path)
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(
                    f"""
                    UPDATE videos
                    SET file_hash = ?,
                        hash_algorithm = ?,
                        hash_generated_at = ?,
                        hash_verify_status = '未校验',
                        hash_verify_at = '',
                        updated_at = ?
                    WHERE {path_clause}
                    """,
                    [hash_text, algorithm_text, generated_at_text, generated_at_text] + path_params,
                )
                connection.commit()
                if self.logger:
                    self.logger.info(
                        "视频哈希按路径写入 SQLite：db=%s, path=%s, affected=%s, algorithm=%s, hash_prefix=%s",
                        self.db_path,
                        path_text,
                        cursor.rowcount,
                        algorithm_text,
                        hash_text[:12],
                    )
                return int(cursor.rowcount)
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("视频哈希按路径写入失败并 rollback：db=%s, path=%s", self.db_path, path_text)
                raise

    def update_video_hash_verify_status(
        self,
        record_id: int,
        verify_status: str,
        verified_at: str | None = None,
    ) -> int:
        status_text = str(verify_status or "").strip()
        verified_at_text = verified_at or format_datetime()
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(
                    """
                    UPDATE videos
                    SET hash_verify_status = ?,
                        hash_verify_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (status_text, verified_at_text, verified_at_text, int(record_id)),
                )
                connection.commit()
                if self.logger:
                    self.logger.info(
                        "视频哈希校验状态写入 SQLite：db=%s, id=%s, status=%s, affected=%s",
                        self.db_path,
                        record_id,
                        status_text,
                        cursor.rowcount,
                    )
                return int(cursor.rowcount)
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("视频哈希校验状态写入失败并 rollback：db=%s, id=%s", self.db_path, record_id)
                raise

    def delete_video_record(self, file_path: str | Path) -> bool:
        path_text = str(Path(file_path).resolve())
        existing = self.get_video_by_path(path_text)
        order_no = str(existing.get("order_no") or "") if existing else ""
        path_clause, path_params = self._path_match_clause(file_path)
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(f"DELETE FROM videos WHERE {path_clause}", path_params)
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

    def delete_video_by_id(self, record_id: int) -> bool:
        record_id = int(record_id or 0)
        if record_id <= 0:
            return False
        existing = self.get_video_by_id(record_id)
        order_no = str(existing.get("order_no") or "") if existing else ""
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute("DELETE FROM videos WHERE id = ?", (record_id,))
                connection.commit()
                if order_no:
                    self.recalculate_duplicate_sequences(order_no)
                if self.logger:
                    self.logger.info(
                        "按 id 删除 SQLite 视频记录：id=%s, affected=%s, order_no=%s",
                        record_id,
                        cursor.rowcount,
                        order_no or "-",
                    )
                return cursor.rowcount > 0
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("按 id 删除 SQLite 视频记录失败并 rollback：id=%s", record_id)
                raise

    def delete_videos_by_ids(self, record_ids: list[int]) -> int:
        deleted = 0
        for record_id in record_ids:
            if self.delete_video_by_id(int(record_id or 0)):
                deleted += 1
        return deleted

    def mark_file_missing(self, file_path: str | Path) -> bool:
        ok = self._update_fields(
            file_path,
            {"status": MISSING_STATUS, "updated_at": format_datetime()},
            "标记文件不存在",
        )
        if ok and self.logger:
            self.logger.warning("标记文件不存在：%s", file_path)
        return ok

    def update_upload_status(
        self,
        file_path: str | Path,
        upload_status: str,
        remote_path: str | None = None,
        error: str | None = None,
        increment_retry: bool = False,
    ) -> bool:
        status = str(upload_status or UPLOAD_PENDING).strip()
        if status not in VALID_UPLOAD_STATUSES:
            status = UPLOAD_PENDING
        path_text = str(Path(file_path).resolve())
        path_clause, path_params = self._path_match_clause(file_path)
        now_text = format_datetime()
        error_text = str(error or "")[:500]

        with self._lock:
            connection = self.get_connection()
            try:
                if increment_retry:
                    cursor = connection.execute(
                        f"""
                        UPDATE videos
                        SET upload_status = ?,
                            upload_time = CASE WHEN ? IN (?, ?, ?) THEN ? ELSE upload_time END,
                            upload_remote_path = COALESCE(?, upload_remote_path),
                            upload_error = ?,
                            upload_retry_count = COALESCE(upload_retry_count, 0) + 1,
                            updated_at = ?
                        WHERE {path_clause}
                        """,
                        [status, status, UPLOAD_UPLOADING, UPLOAD_DONE, UPLOAD_FAILED, now_text, remote_path, error_text, now_text] + path_params,
                    )
                else:
                    cursor = connection.execute(
                        f"""
                        UPDATE videos
                        SET upload_status = ?,
                            upload_time = CASE WHEN ? IN (?, ?, ?) THEN ? ELSE upload_time END,
                            upload_remote_path = COALESCE(?, upload_remote_path),
                            upload_error = ?,
                            updated_at = ?
                        WHERE {path_clause}
                        """,
                        [status, status, UPLOAD_UPLOADING, UPLOAD_DONE, UPLOAD_FAILED, now_text, remote_path, error_text, now_text] + path_params,
                    )
                connection.commit()
                if cursor.rowcount <= 0 and self.logger:
                    self.logger.warning(
                        "更新网盘上传状态失败：记录不存在，path=%s, status=%s, remote_path=%s, error=%s",
                        path_text,
                        status,
                        remote_path or "",
                        error_text,
                    )
                elif self.logger:
                    self.logger.info(
                        "更新网盘上传状态成功：path=%s, status=%s, remote_path=%s, error=%s",
                        path_text,
                        status,
                        remote_path or "",
                        error_text,
                    )
                return cursor.rowcount > 0
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("更新网盘上传状态失败并 rollback：path=%s, status=%s", path_text, status)
                raise

    def reset_interrupted_uploads(self) -> int:
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(
                    """
                    UPDATE videos
                    SET upload_status = ?,
                        upload_error = ?,
                        updated_at = ?
                    WHERE upload_status = ?
                    """,
                    (UPLOAD_FAILED, "上次上传中断", format_datetime(), UPLOAD_UPLOADING),
                )
                connection.commit()
                if cursor.rowcount and self.logger:
                    self.logger.warning("已恢复上次中断的网盘上传记录：%s 条", cursor.rowcount)
                return int(cursor.rowcount or 0)
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("恢复上次中断上传状态失败并 rollback")
                raise

    def backup_database_before_dedupe(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.db_path.with_name(f"pm_system_backup_before_dedupe_{timestamp}.db")
        try:
            with sqlite3.connect(str(backup_path)) as backup_connection:
                self.get_connection().backup(backup_connection)
            if self.logger:
                self.logger.warning("数据库去重前备份完成：%s", backup_path)
            return backup_path
        except Exception:
            if self.logger:
                self.logger.exception("数据库去重前备份失败：%s", backup_path)
            raise

    def diagnose_video_records(self, query_dir: str | Path | None = None) -> dict[str, int]:
        with self._lock:
            connection = self.get_connection()
            self._sync_normalized_file_paths(connection)
            connection.commit()
            conditions = ["1=1"]
            params: list[Any] = []
            if query_dir:
                directory_clause, directory_params = self._directory_filter_clause(query_dir)
                conditions.append(directory_clause)
                params.extend(directory_params)
            where_sql = " AND ".join(conditions)
            total = int(connection.execute(f"SELECT COUNT(*) AS total FROM videos WHERE {where_sql}", params).fetchone()["total"])
            duplicate_orders = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM (
                        SELECT order_no
                        FROM videos
                        WHERE {where_sql} AND order_no IS NOT NULL AND order_no <> ''
                        GROUP BY order_no
                        HAVING COUNT(*) > 1
                    )
                    """,
                    params,
                ).fetchone()["total"]
            )
            duplicate_paths = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM (
                        SELECT normalized_file_path
                        FROM videos
                        WHERE {where_sql}
                          AND normalized_file_path IS NOT NULL
                          AND normalized_file_path <> ''
                        GROUP BY normalized_file_path
                        HAVING COUNT(*) > 1
                    )
                    """,
                    params,
                ).fetchone()["total"]
            )
            suspicious_files = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM (
                        SELECT file_name, COALESCE(file_size_bytes, 0), ROUND(COALESCE(duration_seconds, 0), 1), order_no
                        FROM videos
                        WHERE {where_sql}
                        GROUP BY file_name, COALESCE(file_size_bytes, 0), ROUND(COALESCE(duration_seconds, 0), 1), order_no
                        HAVING COUNT(*) > 1
                    )
                    """,
                    params,
                ).fetchone()["total"]
            )
            if self.logger:
                self.logger.warning(
                    "视频记录诊断：db=%s, query_dir=%s, normalized_query_dir=%s, total=%s, duplicate_order_groups=%s, duplicate_path_groups=%s, suspicious_file_groups=%s, sql_where=%s, params=%s",
                    self.db_path,
                    query_dir or "<全部>",
                    normalize_file_path(query_dir) if query_dir else "<全部>",
                    total,
                    duplicate_orders,
                    duplicate_paths,
                    suspicious_files,
                    where_sql,
                    params,
                )
            return {
                "total": total,
                "duplicate_order_groups": duplicate_orders,
                "duplicate_path_groups": duplicate_paths,
                "suspicious_file_groups": suspicious_files,
            }

    def repair_duplicate_video_records(self) -> int:
        with self._lock:
            connection = self.get_connection()
            try:
                self._sync_normalized_file_paths(connection)
                connection.commit()
                groups = connection.execute(
                    """
                    SELECT normalized_file_path, COUNT(*) AS total
                    FROM videos
                    WHERE normalized_file_path IS NOT NULL AND normalized_file_path <> ''
                    GROUP BY normalized_file_path
                    HAVING COUNT(*) > 1
                    """
                ).fetchall()
                if not groups:
                    connection.execute(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_normalized_file_path_unique
                        ON videos(normalized_file_path)
                        WHERE normalized_file_path IS NOT NULL AND normalized_file_path <> ''
                        """
                    )
                    connection.commit()
                    return 0
                self.diagnose_video_records()
                try:
                    backup_path = self.backup_database_before_dedupe()
                except Exception:
                    connection.rollback()
                    if self.logger:
                        self.logger.error("数据库备份失败，已跳过自动去重修复")
                    return 0
                columns = self._video_column_names(connection)
                affected_order_numbers: set[str] = set()
                removed_count = 0
                for group in groups:
                    normalized_path = str(group["normalized_file_path"] or "")
                    rows = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT * FROM videos WHERE normalized_file_path = ? ORDER BY id ASC",
                            (normalized_path,),
                        ).fetchall()
                    ]
                    if len(rows) <= 1:
                        continue
                    main = self._choose_duplicate_primary(rows)
                    merged = self._merge_duplicate_rows(rows, main, columns)
                    update_fields = [key for key in merged if key in columns and key != "id"]
                    assignments = ", ".join(f"{key} = ?" for key in update_fields)
                    values = [merged[key] for key in update_fields] + [int(main["id"])]
                    connection.execute(f"UPDATE videos SET {assignments} WHERE id = ?", values)
                    duplicate_ids = [int(row["id"]) for row in rows if int(row["id"]) != int(main["id"])]
                    if duplicate_ids:
                        placeholders = ", ".join("?" for _ in duplicate_ids)
                        connection.execute(f"DELETE FROM videos WHERE id IN ({placeholders})", duplicate_ids)
                        removed_count += len(duplicate_ids)
                    for row in rows:
                        order_no = str(row.get("order_no") or "").strip()
                        if order_no:
                            affected_order_numbers.add(order_no)
                    if self.logger:
                        self.logger.warning(
                            "合并重复视频记录：normalized_path=%s, keep_id=%s, remove_ids=%s, upload_status=%s, remote_path=%s",
                            normalized_path,
                            int(main["id"]),
                            duplicate_ids,
                            merged.get("upload_status") or "",
                            merged.get("upload_remote_path") or "",
                        )
                connection.commit()
                for order_no in affected_order_numbers:
                    self.recalculate_duplicate_sequences(order_no)
                connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_normalized_file_path_unique
                    ON videos(normalized_file_path)
                    WHERE normalized_file_path IS NOT NULL AND normalized_file_path <> ''
                    """
                )
                connection.commit()
                if self.logger:
                    self.logger.warning("重复视频记录修复完成：backup=%s, removed=%s", backup_path, removed_count)
                return removed_count
            except Exception:
                connection.rollback()
                if self.logger:
                    self.logger.exception("重复视频记录修复失败并 rollback")
                raise

    def _video_column_names(self, connection: sqlite3.Connection) -> set[str]:
        return {str(row["name"]) for row in connection.execute("PRAGMA table_info(videos)").fetchall()}

    def _choose_duplicate_primary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        uploaded = [row for row in rows if str(row.get("upload_status") or "") == UPLOAD_DONE]
        if uploaded:
            return max(uploaded, key=lambda row: (str(row.get("upload_time") or ""), int(row.get("id") or 0)))
        return min(rows, key=lambda row: int(row.get("id") or 0))

    def _merge_duplicate_rows(
        self,
        rows: list[dict[str, Any]],
        main: dict[str, Any],
        columns: set[str],
    ) -> dict[str, Any]:
        merged = dict(main)
        final_status = max(
            (str(row.get("upload_status") or UPLOAD_PENDING) for row in rows),
            key=lambda status: UPLOAD_STATUS_PRIORITY.get(status, 0),
        )
        merged["upload_status"] = final_status
        merged["upload_time"] = self._latest_nonempty(rows, "upload_time")
        merged["upload_remote_path"] = self._first_nonempty(rows, "upload_remote_path") or str(main.get("upload_remote_path") or "")
        merged["upload_retry_count"] = max(int(row.get("upload_retry_count") or 0) for row in rows)
        merged["upload_error"] = self._first_nonempty(rows, "upload_error") if final_status == UPLOAD_FAILED else ""
        if not str(merged.get("remark") or "").strip():
            merged["remark"] = self._first_nonempty(rows, "remark")
        merged["status"] = self._preferred_text(rows, "status", [ERROR_STATUS, NORMAL_STATUS, MISSING_STATUS])
        merged["validation_status"] = self._preferred_text(rows, "validation_status", [ERROR_STATUS, NORMAL_STATUS, MISSING_STATUS, "未校验"])
        if not str(merged.get("validation_error") or ""):
            merged["validation_error"] = self._first_nonempty(rows, "validation_error")
        if not str(merged.get("validation_warning") or ""):
            merged["validation_warning"] = self._first_nonempty(rows, "validation_warning")
        merged["validated_at"] = self._latest_nonempty(rows, "validated_at") or str(main.get("validated_at") or "")
        merged["file_size_bytes"] = max(int(row.get("file_size_bytes") or 0) for row in rows)
        if int(merged.get("file_size_bytes") or 0) > 0:
            merged["file_size_text"] = human_file_size(int(merged.get("file_size_bytes") or 0))
        merged["duration_seconds"] = max(float(row.get("duration_seconds") or 0.0) for row in rows)
        if float(merged.get("duration_seconds") or 0.0) > 0:
            merged["duration_text"] = format_duration(int(round(float(merged.get("duration_seconds") or 0.0))))
        for field in ("width", "height"):
            merged[field] = max(int(row.get(field) or 0) for row in rows)
        if int(merged.get("width") or 0) > 0 and int(merged.get("height") or 0) > 0:
            merged["resolution"] = f"{int(merged['width'])} x {int(merged['height'])}"
        for field in ("codec", "fps", "record_type", "created_time", "recorded_at"):
            if not str(merged.get(field) or "").strip():
                merged[field] = self._first_nonempty(rows, field)
        for field in (
            "is_important",
            "important_note",
            "important_at",
            "file_hash",
            "hash_algorithm",
            "hash_generated_at",
            "hash_verify_status",
            "hash_verify_at",
        ):
            if field not in columns:
                continue
            if field == "is_important":
                merged[field] = max(int(row.get(field) or 0) for row in rows)
            elif not str(merged.get(field) or "").strip():
                merged[field] = self._first_nonempty(rows, field)
        merged["normalized_file_path"] = normalize_file_path(merged.get("file_path"))
        merged["updated_at"] = format_datetime()
        return merged

    @staticmethod
    def _first_nonempty(rows: list[dict[str, Any]], field: str) -> str:
        for row in rows:
            value = str(row.get(field) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _latest_nonempty(rows: list[dict[str, Any]], field: str) -> str:
        values = [str(row.get(field) or "").strip() for row in rows if str(row.get(field) or "").strip()]
        return max(values) if values else ""

    @staticmethod
    def _preferred_text(rows: list[dict[str, Any]], field: str, priority: list[str]) -> str:
        values = [str(row.get(field) or "").strip() for row in rows if str(row.get(field) or "").strip()]
        for item in priority:
            if item in values:
                return item
        return values[0] if values else ""

    def query_upload_candidates(
        self,
        query_dir: str | Path | None = None,
        include_failed: bool = False,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"limit": limit, "offset": 0}
        if query_dir:
            filters["query_dir"] = query_dir
        conditions, params = self._video_filter_conditions(filters)
        statuses = [UPLOAD_PENDING]
        if include_failed:
            statuses.append(UPLOAD_FAILED)
        placeholders = ", ".join("?" for _ in statuses)
        conditions.append(f"COALESCE(upload_status, ?) IN ({placeholders})")
        params.append(UPLOAD_PENDING)
        params.extend(statuses)
        conditions.append("status = ?")
        params.append(NORMAL_STATUS)
        params.append(max(1, min(int(limit or 5000), 5000)))
        sql = f"""
            SELECT *
            FROM videos
            WHERE {' AND '.join(conditions)}
            ORDER BY
                COALESCE(NULLIF(recorded_at, ''), NULLIF(created_time, ''), printf('%012d', id)) ASC,
                id ASC
            LIMIT ?
        """
        try:
            rows = [self._row_to_item(row) for row in self.get_connection().execute(sql, params).fetchall()]
            if self.logger:
                self.logger.info(
                    "查询网盘上传候选视频成功：dir=%s, include_failed=%s, count=%s",
                    query_dir or "<全部>",
                    include_failed,
                    len(rows),
                )
            return rows
        except Exception:
            if self.logger:
                self.logger.exception("查询网盘上传候选视频失败：dir=%s", query_dir or "<全部>")
            return []

    def query_upload_history(
        self,
        upload_status: str | None = None,
        keyword: str = "",
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions = ["COALESCE(upload_status, ?) IN (?, ?)"]
        params: list[Any] = [UPLOAD_PENDING, UPLOAD_DONE, UPLOAD_FAILED]
        status = str(upload_status or "").strip()
        if status and status in {UPLOAD_DONE, UPLOAD_FAILED}:
            conditions.append("COALESCE(upload_status, ?) = ?")
            params.extend([UPLOAD_PENDING, status])
        keyword_text = str(keyword or "").strip()
        if keyword_text:
            conditions.append("order_no LIKE ?")
            like_text = f"%{keyword_text}%"
            params.append(like_text)
        safe_limit = max(1, min(int(limit or 5000), 5000))
        safe_offset = max(0, int(offset or 0))
        params.extend([safe_limit, safe_offset])
        sql = f"""
            SELECT *
            FROM videos
            WHERE {' AND '.join(conditions)}
            ORDER BY
                CASE WHEN upload_time IS NULL OR upload_time = '' THEN 1 ELSE 0 END ASC,
                upload_time DESC,
                COALESCE(NULLIF(updated_at, ''), NULLIF(recorded_at, ''), NULLIF(created_time, ''), printf('%012d', id)) DESC,
                id DESC
            LIMIT ? OFFSET ?
        """
        try:
            rows = [self._row_to_item(row) for row in self.get_connection().execute(sql, params).fetchall()]
            if self.logger:
                self.logger.info(
                    "查询网盘同步记录成功：status=%s, keyword=%s, limit=%s, offset=%s, count=%s",
                    status or "全部",
                    keyword_text,
                    safe_limit,
                    safe_offset,
                    len(rows),
                )
            return rows
        except Exception:
            if self.logger:
                self.logger.exception("查询网盘同步记录失败：status=%s, keyword=%s", status or "全部", keyword_text)
            return []

    def count_upload_history(self, upload_status: str | None = None, keyword: str = "") -> int:
        conditions = ["COALESCE(upload_status, ?) IN (?, ?)"]
        params: list[Any] = [UPLOAD_PENDING, UPLOAD_DONE, UPLOAD_FAILED]
        status = str(upload_status or "").strip()
        if status and status in {UPLOAD_DONE, UPLOAD_FAILED}:
            conditions.append("COALESCE(upload_status, ?) = ?")
            params.extend([UPLOAD_PENDING, status])
        keyword_text = str(keyword or "").strip()
        if keyword_text:
            conditions.append("order_no LIKE ?")
            params.append(f"%{keyword_text}%")
        sql = f"SELECT COUNT(*) FROM videos WHERE {' AND '.join(conditions)}"
        try:
            row = self.get_connection().execute(sql, params).fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            if self.logger:
                self.logger.exception("统计网盘同步记录失败：status=%s, keyword=%s", status or "全部", keyword_text)
            return 0

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
            self._apply_query_scoped_duplicates(rows, filters)
            self.last_query_truncated = False
            elapsed_ms = (time.perf_counter() - started) * 1000
            if self.logger:
                self.logger.info(
                    "查询视频列表成功：db=%s, 数量=%s, limit=%s, offset=%s, 耗时=%.2fms, filters=%s",
                    self.db_path,
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

    def _apply_query_scoped_duplicates(self, rows: list[dict[str, Any]], filters: dict[str, Any]) -> None:
        query_dir = filters.get("query_dir")
        if not query_dir or not rows:
            return
        order_numbers = sorted({str(row.get("order_no") or "").strip() for row in rows if str(row.get("order_no") or "").strip()})
        if not order_numbers:
            return
        path_condition, path_params = self._directory_filter_clause(query_dir)
        connection = self.get_connection()
        scoped: dict[int, tuple[int, int]] = {}
        for order_no in order_numbers:
            scoped_rows = connection.execute(
                f"""
                SELECT id
                FROM videos
                WHERE order_no = ?
                  AND status <> ?
                  AND {path_condition}
                ORDER BY
                    COALESCE(NULLIF(recorded_at, ''), NULLIF(created_time, ''), printf('%012d', id)) ASC,
                    file_name ASC,
                    id ASC
                """,
                [order_no, MISSING_STATUS] + path_params,
            ).fetchall()
            count = len(scoped_rows)
            for sequence, row in enumerate(scoped_rows, start=1):
                scoped[int(row["id"])] = (sequence, count)
        for row in rows:
            record_id = int(row.get("id") or 0)
            sequence, count = scoped.get(record_id, (0, 0))
            if count > 1:
                row["is_duplicate"] = True
                row["duplicate_count"] = count
                row["duplicate_sequence"] = sequence
            else:
                row["is_duplicate"] = False
                row["duplicate_count"] = 1 if count == 1 else 0
                row["duplicate_sequence"] = 1 if count == 1 else 0

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
            resolved = normalize_file_path(path)
            scanned_paths.add(resolved)
            try:
                self.upsert_video_file(path)
            except Exception:
                if self.logger:
                    self.logger.exception("刷新目录时写入视频记录失败：%s", path)

        for row in self.query_videos({"query_dir": directory, "limit": 5000}):
            path = Path(str(row.get("file_path", "")))
            row_path = str(row.get("normalized_file_path") or "") or normalize_file_path(path)
            if row_path not in scanned_paths and not path.exists():
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
            path_condition, path_params = self._directory_filter_clause(video_dir)
            conditions.append(path_condition)
            params.extend(path_params)
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
            path_condition, path_params = self._directory_filter_clause(video_dir)
            conditions.append(path_condition)
            params.extend(path_params)
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
        path_clause, path_params = self._path_match_clause(file_path)
        row = self.get_connection().execute(
            f"SELECT * FROM videos WHERE {path_clause} ORDER BY id ASC LIMIT 1",
            path_params,
        ).fetchone()
        return self._row_to_item(row) if row else None

    def get_video_by_id(self, record_id: int) -> dict[str, Any] | None:
        row = self.get_connection().execute(
            "SELECT * FROM videos WHERE id = ?",
            (int(record_id),),
        ).fetchone()
        return self._row_to_item(row) if row else None

    def get_videos_by_order_no(self, order_no: str, query_dir: str | Path | None = None) -> list[dict[str, Any]]:
        order_no = str(order_no or "").strip()
        if not order_no:
            return []
        conditions = ["order_no = ?"]
        params: list[Any] = [order_no]
        if query_dir:
            path_condition, path_params = self._directory_filter_clause(query_dir)
            conditions.append(path_condition)
            params.extend(path_params)
        try:
            with self._lock:
                rows = self.get_connection().execute(
                    f"""
                    SELECT *
                    FROM videos
                    WHERE {' AND '.join(conditions)}
                    ORDER BY
                        COALESCE(NULLIF(recorded_at, ''), NULLIF(created_time, ''), printf('%012d', id)) DESC,
                        id DESC
                    """,
                    params,
                ).fetchall()
            items = [self._row_to_item(row) for row in rows]
            if query_dir:
                self._apply_query_scoped_duplicates(items, {"query_dir": query_dir})
            return items
        except Exception:
            if self.logger:
                self.logger.exception("按单号查询视频记录失败：order_no=%s", order_no)
            return []

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _video_filter_conditions(self, filters: dict[str, Any]) -> tuple[list[str], list[Any]]:
        conditions = ["1=1"]
        params: list[Any] = []

        query_dir = filters.get("query_dir")
        if query_dir:
            path_condition, path_params = self._directory_filter_clause(query_dir)
            conditions.append(path_condition)
            params.extend(path_params)

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

        upload_status = str(filters.get("upload_status") or "").strip()
        if upload_status and upload_status in VALID_UPLOAD_STATUSES:
            conditions.append("COALESCE(upload_status, ?) = ?")
            params.extend([UPLOAD_PENDING, upload_status])

        local_status = str(filters.get("status") or "").strip()
        if local_status:
            conditions.append("status = ?")
            params.append(local_status)

        return conditions, params

    def _directory_filter_clause(self, directory: str | Path) -> tuple[str, list[Any]]:
        normalized_prefix = normalize_file_path(directory).rstrip("\\/")
        resolved_prefix = str(Path(str(directory)).resolve()).rstrip("\\/")
        separator = "\\" if os.name == "nt" else "/"
        return (
            "(normalized_file_path = ? OR normalized_file_path LIKE ? OR file_path = ? OR file_path LIKE ?)",
            [
                normalized_prefix,
                normalized_prefix + separator + "%",
                resolved_prefix,
                resolved_prefix + "\\%",
            ],
        )

    def _path_match_clause(self, file_path: str | Path) -> tuple[str, list[Any]]:
        normalized = normalize_file_path(file_path)
        resolved = str(Path(str(file_path)).resolve())
        return "(normalized_file_path = ? OR file_path = ?)", [normalized, resolved]

    def _update_fields(self, file_path: str | Path, values: dict[str, Any], action_name: str) -> bool:
        if not values:
            return False
        path_text = str(Path(file_path).resolve())
        path_clause, path_params = self._path_match_clause(file_path)
        assignments = ", ".join(f"{key} = ?" for key in values)
        params = list(values.values()) + path_params
        with self._lock:
            connection = self.get_connection()
            try:
                cursor = connection.execute(f"UPDATE videos SET {assignments} WHERE {path_clause}", params)
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
        validation_status = "未校验"
        validation_error = ""
        validation_warning = ""
        validated_at = ""

        if exists:
            try:
                stat_result = path.stat()
                file_size = int(stat_result.st_size)
                created_time = format_datetime(datetime.fromtimestamp(stat_result.st_ctime or stat_result.st_mtime))
            except OSError:
                exists = False

        if not exists:
            validation_status = MISSING_STATUS
            validation_error = "视频文件不存在"
            validated_at = now_text

        if exists:
            check = VideoChecker(self.logger).check_video(path)
            duration_seconds = float(check.duration_seconds or 0.0)
            duration_text = format_duration(int(round(duration_seconds))) if duration_seconds > 0 else "-"
            status = NORMAL_STATUS if check.is_valid else ERROR_STATUS
            validation_status = getattr(check, "status", "") or status
            validation_error = getattr(check, "error", "") or ""
            validation_warning = getattr(check, "warning", "") or ""
            validated_at = getattr(check, "validated_at", "") or now_text
            width = int(getattr(check, "width", 0) or 0)
            height = int(getattr(check, "height", 0) or 0)
            fps = float(getattr(check, "fps", 0.0) or 0.0)
            codec = str(getattr(check, "codec", "") or "-")
            resolution = f"{width} x {height}" if width > 0 and height > 0 else "-"
            if width <= 0 or height <= 0 or fps <= 0:
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
            "validation_status": validation_status,
            "validation_error": validation_error,
            "validation_warning": validation_warning,
            "validated_at": validated_at,
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
        item["upload_status"] = item.get("upload_status") or UPLOAD_PENDING
        item["upload_time"] = item.get("upload_time") or ""
        item["upload_remote_path"] = item.get("upload_remote_path") or ""
        item["upload_error"] = item.get("upload_error") or ""
        item["upload_retry_count"] = int(item.get("upload_retry_count") or 0)
        item["validation_status"] = item.get("validation_status") or "未校验"
        item["validation_error"] = item.get("validation_error") or ""
        item["validation_warning"] = item.get("validation_warning") or ""
        item["validated_at"] = item.get("validated_at") or ""
        item["file_hash"] = item.get("file_hash") or ""
        item["hash_algorithm"] = item.get("hash_algorithm") or ""
        item["hash_generated_at"] = item.get("hash_generated_at") or ""
        item["hash_verify_status"] = item.get("hash_verify_status") or ""
        item["hash_verify_at"] = item.get("hash_verify_at") or ""
        item["normalized_file_path"] = item.get("normalized_file_path") or normalize_file_path(item.get("file_path"))
        item["is_important"] = bool(item.get("is_important"))
        item["important_note"] = item.get("important_note") or ""
        item["important_at"] = item.get("important_at") or ""
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
