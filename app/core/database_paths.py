from __future__ import annotations

import os
import sys
from pathlib import Path

from app.core.version import APP_DATA_DIR_NAME

DATABASE_DIR_NAME = "data"
DATABASE_FILE_NAME = "pmsystem.db"
LEGACY_DATABASE_FILE_NAME = "pm_system.db"
APP_VENDOR_DIR_NAME = "JsonLin"


def local_app_data_dir() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def source_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    return local_app_data_dir() / APP_VENDOR_DIR_NAME / APP_DATA_DIR_NAME


def database_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else app_data_dir()
    return root / DATABASE_DIR_NAME


def database_path(base_dir: str | Path | None = None) -> Path:
    return database_dir(base_dir) / DATABASE_FILE_NAME


def legacy_database_candidates(base_dir: str | Path | None = None) -> list[Path]:
    root = Path(base_dir) if base_dir is not None else app_data_dir()
    legacy_local_root = local_app_data_dir() / APP_DATA_DIR_NAME
    candidates = [
        root / LEGACY_DATABASE_FILE_NAME,
        legacy_local_root / LEGACY_DATABASE_FILE_NAME,
        legacy_local_root / DATABASE_DIR_NAME / DATABASE_FILE_NAME,
        source_app_dir() / LEGACY_DATABASE_FILE_NAME,
        Path.cwd() / LEGACY_DATABASE_FILE_NAME,
    ]
    result: list[Path] = []
    seen: set[str] = set()
    target = database_path(root).resolve()
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
