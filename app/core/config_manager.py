from __future__ import annotations

import json
import os
import shutil
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from posixpath import normpath
from typing import Any

from app.core.database_paths import database_path, local_app_data_dir, source_app_dir
from app.core.version import APP_DATA_DIR_NAME


DEFAULT_CONFIG: dict[str, Any] = {
    "video_root_dir": "videos",
    "video_save_dir": "videos",
    "camera_index": 0,
    "camera_name": "",
    "resolution": "original",
    "fps": 25,
    "video_format": "mp4",
    "recording_max_long_edge": 1280,
    "current_record_type": "发货",
    "auto_delete_days": 30,
    "auto_continue_recording": True,
    "use_default_player": True,
    "watermark_font_size": 28,
    "watermark_margin": 16,
    "scanner_guard": {
        "enabled": True,
        "soft_prompt_only": True,
        "debounce_enabled": True,
        "debounce_seconds": 1,
        "min_length_warn": 6,
        "max_length_warn": 40,
        "clean_special_chars": True,
        "block_invalid": False,
    },
    "recording_quality": {
        "min_valid_duration_seconds": 3,
        "warn_short_video": True,
    },
    "hash_check": {
        "enabled": True,
        "algorithm": "SHA256",
        "auto_generate_after_recording": True,
    },
    "disk_space": {
        "enabled": True,
        "warning_gb": 20,
        "critical_gb": 10,
    },
    "query": {
        "last_query_dir": "",
        "page_size": 20,
    },
    "preview": {
        "show_recording_watermark": True,
    },
    "voice_prompt": {
        "enabled": True,
        "mode": "system",
        "custom_voice_dir": "%LOCALAPPDATA%/PMSystem/voice",
        "custom_files": {
            "start": "",
            "stop": "",
            "switch": "",
            "duplicate": "",
            "no_order": "",
            "camera_lost": "",
            "record_error": "",
            "disk_full": "",
            "camera_refresh": "",
            "video_missing": "",
            "save_failed": "",
            "save_success": "",
            "list_refresh": "",
        },
        "system_text": {
            "start": "已开始录制",
            "stop": "录制已结束",
            "switch": "已切换录制",
            "duplicate": "单号已录过",
            "no_order": "请先输入或扫描单号",
            "camera_lost": "摄像头连接异常，请检查 iVCam 或摄像头",
            "record_error": "录制异常，请检查摄像头或磁盘空间",
            "disk_full": "磁盘空间不足，请及时清理",
            "camera_refresh": "摄像头已刷新",
            "video_missing": "视频文件不存在",
            "save_failed": "保存失败",
            "save_success": "配置已保存",
            "list_refresh": "列表已刷新",
        },
    },
    "netdisk_sync": {
        "enabled": False,
        "provider": "baidu",
        "remote_root": "/电商溯源/videos/",
        "client_id": "",
        "client_secret": "",
        "access_token": "",
        "refresh_token": "",
        "token_expires_at": "",
        "last_auth_time": "",
        "debug": False,
    },
    "cloud_sync": {
        "auto_sync_enabled": False,
        "auto_sync_trigger": "after_last_recording",
        "auto_sync_delay_minutes": 10,
    },
    "recent": {
        "last_video_dir": "videos",
        "last_resolution": "original",
        "last_camera_index": 0,
        "last_camera_name": "",
    },
    "window": {
        "width": 1600,
        "height": 960,
        "x": 0,
        "y": 0,
        "remember_geometry": True,
        "geometry_saved": False,
    },
}

LEGACY_NO_ORDER_PROMPT = "请先输入或扫描" + "物流" + "单号"
CURRENT_NO_ORDER_PROMPT = "请先输入或扫描单号"

CONFIG_EXPORT_VERSION = 1
CONFIG_EXPORT_APP = "PMSystem"
NETDISK_EXPORT_SECRET_KEYS = {
    "client_secret",
    "access_token",
    "refresh_token",
    "token_expires_at",
    "last_auth_time",
}
EXPORTABLE_CONFIG_KEYS = {
    "video_root_dir",
    "camera_index",
    "camera_name",
    "resolution",
    "fps",
    "video_format",
    "recording_max_long_edge",
    "current_record_type",
    "auto_continue_recording",
    "use_default_player",
    "watermark_font_size",
    "watermark_margin",
    "scanner_guard",
    "recording_quality",
    "hash_check",
    "disk_space",
    "preview",
    "voice_prompt",
    "netdisk_sync",
    "cloud_sync",
}


AUTO_SYNC_DELAY_OPTIONS = (1, 5, 10, 15, 30, 60)


def normalize_cloud_sync_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG["cloud_sync"])
    if isinstance(raw, dict):
        config.update(raw)
    config["auto_sync_enabled"] = bool(config.get("auto_sync_enabled", False))
    config["auto_sync_trigger"] = "after_last_recording"
    try:
        delay = int(config.get("auto_sync_delay_minutes") or 10)
    except (TypeError, ValueError):
        delay = 10
    if delay not in AUTO_SYNC_DELAY_OPTIONS:
        delay = 10
    config["auto_sync_delay_minutes"] = delay
    return config


class ConfigManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.config_path = self.base_dir / "config.json"
        self.database_path = database_path(self.base_dir)
        self.config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)

    def load(self) -> dict[str, Any]:
        self._migrate_legacy_config_if_needed()
        if not self.config_path.exists():
            self.config = deepcopy(DEFAULT_CONFIG)
            self._normalize_video_root_dir_config(self.config)
            self.save()
            return self.config

        try:
            with self.config_path.open("r", encoding="utf-8") as file:
                loaded = json.load(file)
            self.config = self._merge_defaults(loaded, DEFAULT_CONFIG)
            migrated = self._normalize_video_root_dir_config(self.config, loaded)
        except (OSError, json.JSONDecodeError):
            self.config = deepcopy(DEFAULT_CONFIG)
            self._normalize_video_root_dir_config(self.config)
            self.save()
        else:
            if migrated or self._normalize_legacy_display_text():
                self.save()

        return self.config

    def save(self, config: dict[str, Any] | None = None) -> None:
        if config is not None:
            self.config = self._merge_defaults(config, DEFAULT_CONFIG)
        self._normalize_video_root_dir_config(self.config)
        self._normalize_legacy_display_text()

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(self.config, file, ensure_ascii=False, indent=2)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        normalized_values = dict(values)
        if "video_root_dir" in normalized_values or "video_save_dir" in normalized_values:
            raw_dir = normalized_values.get("video_root_dir") or normalized_values.get("video_save_dir")
            normalized_dir = self.normalize_video_root_dir_value(raw_dir)
            normalized_values["video_root_dir"] = normalized_dir
            normalized_values["video_save_dir"] = normalized_dir
        self.config.update(normalized_values)
        self._normalize_video_root_dir_config(self.config)
        recent = self.config.setdefault("recent", {})
        if "video_root_dir" in normalized_values:
            recent["last_video_dir"] = normalized_values["video_root_dir"]
        if "resolution" in normalized_values:
            recent["last_resolution"] = normalized_values["resolution"]
        if "camera_index" in normalized_values:
            recent["last_camera_index"] = normalized_values["camera_index"]
        if "camera_name" in normalized_values:
            recent["last_camera_name"] = normalized_values["camera_name"]
        self.save()
        return self.config

    def _migrate_legacy_config_if_needed(self) -> None:
        candidates = self._legacy_config_candidates()
        source = next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)
        if source is None:
            return

        should_copy = not self.config_path.exists()
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as file:
                    current = json.load(file)
                default_video_dir = str((self.base_dir / "videos").resolve())
                current_video_dir = str(current.get("video_root_dir") or current.get("video_save_dir") or "").strip()
                with source.open("r", encoding="utf-8") as file:
                    legacy = json.load(file)
                legacy_video_dir = str(legacy.get("video_root_dir") or legacy.get("video_save_dir") or "").strip()
                should_copy = (
                    bool(legacy_video_dir)
                    and current_video_dir == default_video_dir
                    and legacy_video_dir != current_video_dir
                )
            except (OSError, json.JSONDecodeError):
                should_copy = False
        if not should_copy:
            return

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            backup = self.config_path.with_name(f"config_before_legacy_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            shutil.copy2(self.config_path, backup)
        shutil.copy2(source, self.config_path)

    def _legacy_config_candidates(self) -> list[Path]:
        candidates = [
            local_app_data_dir() / APP_DATA_DIR_NAME / "config.json",
            source_app_dir() / "config.json",
            Path.cwd() / "config.json",
        ]
        result: list[Path] = []
        seen: set[str] = set()
        target = self.config_path.resolve()
        for candidate in candidates:
            try:
                resolved = candidate.expanduser().resolve()
            except OSError:
                resolved = candidate.expanduser().absolute()
            key = os.path.normcase(os.path.normpath(str(resolved)))
            if key in seen or resolved == target:
                continue
            seen.add(key)
            result.append(resolved)
        return result

    def get_video_dir(self) -> Path:
        return self.resolve_path(str(self.config.get("video_root_dir") or self.config.get("video_save_dir") or "videos"))

    def normalize_video_root_dir_value(self, value: Any) -> str:
        path_value = str(value or "videos").strip() or "videos"
        return str(self.resolve_path(path_value))

    def ensure_video_root_dir_writable(self, value: Any) -> Path:
        video_dir = self.resolve_path(str(value or "videos").strip() or "videos")
        video_dir.mkdir(parents=True, exist_ok=True)
        if not video_dir.is_dir():
            raise ValueError("视频存储目录不是文件夹")
        test_file = video_dir / ".pm_system_write_test"
        try:
            test_file.write_text("ok", encoding="utf-8")
        finally:
            try:
                if test_file.exists():
                    test_file.unlink()
            except OSError:
                pass
        return video_dir.resolve()

    def resolve_path(self, path_value: str) -> Path:
        path = Path(path_value).expanduser()
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()

    def export_config(self, export_path: str | Path) -> dict[str, Any]:
        export_path = Path(export_path)
        if export_path.suffix.lower() != ".zip":
            export_path = export_path.with_suffix(".zip")
        export_path.parent.mkdir(parents=True, exist_ok=True)

        settings = self._exportable_settings()
        voice_result = self._collect_voice_files(settings)
        export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "app": CONFIG_EXPORT_APP,
            "config_version": CONFIG_EXPORT_VERSION,
            "export_time": export_time,
            "settings": settings,
            "voice_files": {
                "folder": "voice",
                "files": voice_result["files"],
                "warnings": voice_result["warnings"],
            },
            "security_note": "网盘 Secret 和授权 Token 已排除，导入后需要重新授权。",
        }
        manifest = {
            "app": CONFIG_EXPORT_APP,
            "export_time": export_time,
            "config_version": CONFIG_EXPORT_VERSION,
            "contains_voice_files": bool(voice_result["files"]),
            "sensitive_fields_excluded": True,
        }

        with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("config.json", json.dumps(payload, ensure_ascii=False, indent=2))
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for event_key, source in voice_result["sources"].items():
                archive.write(source, voice_result["files"][event_key])

        return {
            "path": str(export_path),
            "voice_folder": "voice" if voice_result["files"] else "",
            "voice_files": voice_result["files"],
            "warnings": voice_result["warnings"],
            "excluded_sensitive_fields": sorted(NETDISK_EXPORT_SECRET_KEYS),
            "archive": True,
        }

    def import_config(self, import_path: str | Path) -> dict[str, Any]:
        import_path = Path(import_path)
        is_zip_import = import_path.suffix.lower() == ".zip"
        if is_zip_import:
            payload = self._read_zip_config(import_path)
        else:
            with import_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)

        if not isinstance(payload, dict):
            raise ValueError("配置文件格式不正确")
        if payload.get("app") != CONFIG_EXPORT_APP:
            raise ValueError("不是 PMSystem 配置文件")
        config_version = int(payload.get("config_version") or 0)
        if config_version < 1 or config_version > CONFIG_EXPORT_VERSION:
            raise ValueError(f"不支持的配置版本：{config_version}")
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("配置文件缺少 settings")

        backup_path = self.backup_current_config()
        old_config = deepcopy(self.config)
        warnings: list[str] = []
        try:
            imported = self._sanitize_import_settings(settings)
            if is_zip_import:
                voice_result = self._import_voice_files_from_zip(import_path, payload, imported)
            else:
                voice_result = self._import_voice_files(import_path, payload, imported)
                warnings.append("已导入旧版 JSON 配置，建议后续使用新版 zip 格式导出配置。")
            warnings.extend(voice_result["warnings"])

            merged = deepcopy(self.config)
            self._deep_update(merged, imported)
            self._ensure_imported_video_dir(merged)
            self.save(merged)
        except Exception:
            self.config = old_config
            raise

        return {
            "backup_path": str(backup_path),
            "config_version": config_version,
            "imported_keys": sorted(imported.keys()),
            "voice_files": voice_result["files"],
            "warnings": warnings,
            "requires_netdisk_reauth": "netdisk_sync" in imported,
            "legacy_json": not is_zip_import,
        }

    def backup_current_config(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.config_path.with_name(f"config_backup_{timestamp}.json")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            shutil.copy2(self.config_path, backup_path)
        else:
            with backup_path.open("w", encoding="utf-8") as file:
                json.dump(self.config, file, ensure_ascii=False, indent=2)
        return backup_path

    def _exportable_settings(self) -> dict[str, Any]:
        settings = {
            key: deepcopy(value)
            for key, value in self.config.items()
            if key in EXPORTABLE_CONFIG_KEYS
        }
        if "netdisk_sync" in settings and isinstance(settings["netdisk_sync"], dict):
            settings["netdisk_sync"] = self._sanitize_netdisk_export(settings["netdisk_sync"])
        if "voice_prompt" in settings and isinstance(settings["voice_prompt"], dict):
            voice_config = settings["voice_prompt"]
            voice_config["custom_voice_dir"] = DEFAULT_CONFIG["voice_prompt"]["custom_voice_dir"]
            custom_files = voice_config.get("custom_files")
            if isinstance(custom_files, dict):
                voice_config["custom_files"] = {key: "" for key in custom_files}
        return settings

    def _collect_voice_files(self, settings: dict[str, Any]) -> dict[str, Any]:
        source_voice = self.config.get("voice_prompt", {})
        source_files = source_voice.get("custom_files", {}) if isinstance(source_voice, dict) else {}
        source_files = source_files if isinstance(source_files, dict) else {}
        copied: dict[str, str] = {}
        sources: dict[str, Path] = {}
        warnings: list[str] = []

        for event_key, path_text in source_files.items():
            source = self._config_path_to_path(str(path_text or ""))
            if source is None:
                continue
            if not source.exists() or not source.is_file():
                warnings.append(f"{event_key}: 自定义语音文件不存在，已跳过")
                continue
            if source.stat().st_size <= 0:
                warnings.append(f"{event_key}: 自定义语音文件为空，已跳过")
                continue
            target_name = f"{event_key}{source.suffix.lower()}"
            zip_name = f"voice/{target_name}"
            copied[str(event_key)] = zip_name
            sources[str(event_key)] = source

        voice_settings = settings.get("voice_prompt")
        if isinstance(voice_settings, dict):
            existing = voice_settings.get("custom_files", {})
            if isinstance(existing, dict):
                voice_settings["custom_files"] = {key: copied.get(str(key), "") for key in existing}
        return {
            "files": copied,
            "sources": sources,
            "warnings": warnings,
        }

    def _read_zip_config(self, import_path: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(import_path, "r") as archive:
                if "config.json" not in archive.namelist():
                    raise ValueError("配置压缩包缺少 config.json")
                raw = archive.read("config.json")
        except zipfile.BadZipFile as exc:
            raise ValueError("配置压缩包格式不正确") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("配置压缩包中的 config.json 格式不正确") from exc
        if not isinstance(payload, dict):
            raise ValueError("配置压缩包中的 config.json 格式不正确")
        return payload

    def _import_voice_files_from_zip(self, import_path: Path, payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        voice_settings = settings.get("voice_prompt")
        if not isinstance(voice_settings, dict):
            return {"files": {}, "warnings": []}

        custom_files = voice_settings.get("custom_files")
        if not isinstance(custom_files, dict):
            return {"files": {}, "warnings": []}

        target_dir = self._config_path_to_path(
            str(voice_settings.get("custom_voice_dir") or DEFAULT_CONFIG["voice_prompt"]["custom_voice_dir"])
        ) or self.resolve_path("voice")
        target_dir.mkdir(parents=True, exist_ok=True)

        copied: dict[str, str] = {}
        warnings: list[str] = []
        try:
            with zipfile.ZipFile(import_path, "r") as archive:
                archive_names = set(archive.namelist())
                for event_key, file_name in list(custom_files.items()):
                    zip_name = self._safe_zip_member_name(str(file_name or ""))
                    if not zip_name:
                        custom_files[event_key] = ""
                        continue
                    if not zip_name.startswith("voice/"):
                        zip_name = f"voice/{Path(zip_name).name}"
                    if zip_name not in archive_names:
                        custom_files[event_key] = ""
                        warnings.append(f"{event_key}: 导入包中未找到语音文件 {zip_name}")
                        continue
                    target = target_dir / Path(zip_name).name
                    with archive.open(zip_name, "r") as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    custom_files[event_key] = str(target)
                    copied[str(event_key)] = str(target)
        except zipfile.BadZipFile as exc:
            raise ValueError("配置压缩包格式不正确") from exc

        voice_settings["custom_voice_dir"] = str(target_dir)
        voice_settings["custom_files"] = custom_files
        return {"files": copied, "warnings": warnings}

    @staticmethod
    def _safe_zip_member_name(value: str) -> str:
        raw = str(value or "").replace("\\", "/").strip()
        if not raw:
            return ""
        if raw.startswith("/") or ":" in raw:
            return ""
        normalized = normpath(raw).replace("\\", "/")
        if normalized in {"", ".", ".."} or normalized.startswith("../"):
            return ""
        return normalized

    def _import_voice_files(self, import_path: Path, payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        voice_settings = settings.get("voice_prompt")
        if not isinstance(voice_settings, dict):
            return {"files": {}, "warnings": []}

        custom_files = voice_settings.get("custom_files")
        if not isinstance(custom_files, dict):
            return {"files": {}, "warnings": []}

        voice_meta = payload.get("voice_files", {})
        folder_name = ""
        if isinstance(voice_meta, dict):
            folder_name = str(voice_meta.get("folder") or "")
        voice_folder = import_path.with_name(folder_name) if folder_name else import_path.with_name(f"{import_path.stem}_voice")
        target_dir = self._config_path_to_path(
            str(voice_settings.get("custom_voice_dir") or DEFAULT_CONFIG["voice_prompt"]["custom_voice_dir"])
        ) or self.resolve_path("voice")
        target_dir.mkdir(parents=True, exist_ok=True)

        copied: dict[str, str] = {}
        warnings: list[str] = []
        for event_key, file_name in list(custom_files.items()):
            file_name = Path(str(file_name or "")).name
            if not file_name:
                custom_files[event_key] = ""
                continue
            source = voice_folder / file_name
            if not source.exists() or not source.is_file():
                custom_files[event_key] = ""
                warnings.append(f"{event_key}: 导入包中未找到语音文件 {file_name}")
                continue
            target = target_dir / file_name
            shutil.copy2(source, target)
            custom_files[event_key] = str(target)
            copied[str(event_key)] = str(target)
        voice_settings["custom_voice_dir"] = str(target_dir)
        voice_settings["custom_files"] = custom_files
        return {"files": copied, "warnings": warnings}

    def _sanitize_import_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        imported = {
            key: deepcopy(value)
            for key, value in settings.items()
            if key in EXPORTABLE_CONFIG_KEYS
        }
        if "video_root_dir" not in imported and "video_save_dir" in settings:
            imported["video_root_dir"] = settings.get("video_save_dir")
        query_settings = settings.get("query")
        if "video_root_dir" not in imported and isinstance(query_settings, dict):
            last_query_dir = str(query_settings.get("last_query_dir") or "").strip()
            if last_query_dir:
                imported["video_root_dir"] = last_query_dir
        if "video_root_dir" in imported:
            imported["video_root_dir"] = self.normalize_video_root_dir_value(imported.get("video_root_dir"))
        if "netdisk_sync" in imported and isinstance(imported["netdisk_sync"], dict):
            imported["netdisk_sync"] = self._sanitize_netdisk_import(imported["netdisk_sync"])
        if "voice_prompt" in imported and isinstance(imported["voice_prompt"], dict):
            imported["voice_prompt"] = self._merge_defaults(imported["voice_prompt"], DEFAULT_CONFIG["voice_prompt"])
        return imported

    def _sanitize_netdisk_export(self, config: dict[str, Any]) -> dict[str, Any]:
        sanitized = deepcopy(config)
        for key in NETDISK_EXPORT_SECRET_KEYS:
            sanitized[key] = ""
        return sanitized

    def _sanitize_netdisk_import(self, config: dict[str, Any]) -> dict[str, Any]:
        sanitized = self._merge_defaults(config, DEFAULT_CONFIG["netdisk_sync"])
        for key in NETDISK_EXPORT_SECRET_KEYS:
            sanitized[key] = ""
        return sanitized

    def _ensure_imported_video_dir(self, config: dict[str, Any]) -> None:
        if "video_root_dir" not in config and "video_save_dir" not in config:
            return
        self._normalize_video_root_dir_config(config)
        video_dir = self.resolve_path(str(config.get("video_root_dir") or "videos"))
        video_dir.mkdir(parents=True, exist_ok=True)

    def _normalize_video_root_dir_config(self, config: dict[str, Any], raw_config: dict[str, Any] | None = None) -> bool:
        raw_config = raw_config if isinstance(raw_config, dict) else config
        raw_root = raw_config.get("video_root_dir") if "video_root_dir" in raw_config else config.get("video_root_dir")
        before_root = str(raw_root or "").strip()
        candidates: list[Any] = []
        if before_root:
            candidates.append(before_root)
        if not before_root:
            candidates.append(raw_config.get("video_save_dir"))
            raw_query = raw_config.get("query")
            if isinstance(raw_query, dict):
                candidates.append(raw_query.get("last_query_dir"))
        candidates.append(config.get("video_save_dir"))
        query_config = config.get("query")
        if isinstance(query_config, dict):
            candidates.append(query_config.get("last_query_dir"))
        candidates.append("videos")

        selected = "videos"
        for candidate in candidates:
            candidate_text = str(candidate or "").strip()
            if candidate_text:
                selected = candidate_text
                break
        normalized = self.normalize_video_root_dir_value(selected)
        changed = (
            str(config.get("video_root_dir") or "") != normalized
            or str(config.get("video_save_dir") or "") != normalized
        )
        config["video_root_dir"] = normalized
        config["video_save_dir"] = normalized
        recent = config.setdefault("recent", {})
        if isinstance(recent, dict):
            if str(recent.get("last_video_dir") or "") != normalized:
                recent["last_video_dir"] = normalized
                changed = True
        else:
            config["recent"] = {"last_video_dir": normalized}
            changed = True
        return changed

    def _config_path_to_path(self, value: str) -> Path | None:
        value = str(value or "").strip()
        if not value:
            return None
        expanded = os.path.expandvars(value)
        path = Path(expanded).expanduser()
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()

    @staticmethod
    def _deep_update(target: dict[str, Any], values: dict[str, Any]) -> None:
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                ConfigManager._deep_update(target[key], value)
            else:
                target[key] = value

    def _normalize_legacy_display_text(self) -> bool:
        voice_config = self.config.get("voice_prompt")
        if not isinstance(voice_config, dict):
            return False
        system_text = voice_config.get("system_text")
        if not isinstance(system_text, dict):
            return False
        if system_text.get("no_order") != LEGACY_NO_ORDER_PROMPT:
            return False
        system_text["no_order"] = CURRENT_NO_ORDER_PROMPT
        return True

    @staticmethod
    def _merge_defaults(value: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(defaults)
        for key, item in value.items():
            if isinstance(item, dict) and isinstance(merged.get(key), dict):
                merged[key] = ConfigManager._merge_defaults(item, merged[key])
            else:
                merged[key] = item
        return merged
