from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
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
        "start_text": "已开始录制",
        "stop_text": "录制已结束",
        "switch_text": "已切换录制",
        "duplicate_text": "单号已录过",
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


class ConfigManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.config_path = self.base_dir / "config.json"
        self.config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            self.config = deepcopy(DEFAULT_CONFIG)
            self.save()
            return self.config

        try:
            with self.config_path.open("r", encoding="utf-8") as file:
                loaded = json.load(file)
            self.config = self._merge_defaults(loaded, DEFAULT_CONFIG)
        except (OSError, json.JSONDecodeError):
            self.config = deepcopy(DEFAULT_CONFIG)
            self.save()

        return self.config

    def save(self, config: dict[str, Any] | None = None) -> None:
        if config is not None:
            self.config = self._merge_defaults(config, DEFAULT_CONFIG)

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(self.config, file, ensure_ascii=False, indent=2)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        self.config.update(values)
        recent = self.config.setdefault("recent", {})
        if "video_save_dir" in values:
            recent["last_video_dir"] = values["video_save_dir"]
        if "resolution" in values:
            recent["last_resolution"] = values["resolution"]
        if "camera_index" in values:
            recent["last_camera_index"] = values["camera_index"]
        if "camera_name" in values:
            recent["last_camera_name"] = values["camera_name"]
        self.save()
        return self.config

    def get_video_dir(self) -> Path:
        return self.resolve_path(str(self.config.get("video_save_dir", "videos")))

    def resolve_path(self, path_value: str) -> Path:
        path = Path(path_value).expanduser()
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()

    @staticmethod
    def _merge_defaults(value: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(defaults)
        for key, item in value.items():
            if isinstance(item, dict) and isinstance(merged.get(key), dict):
                merged[key] = ConfigManager._merge_defaults(item, merged[key])
            else:
                merged[key] = item
        return merged
