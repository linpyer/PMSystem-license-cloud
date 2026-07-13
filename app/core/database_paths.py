from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from app.core.version import APP_DATA_DIR_NAME

DATABASE_DIR_NAME = "data"
DATABASE_FILE_NAME = "pmsystem.db"
APP_VENDOR_DIR_NAME = "JsonLin"
RETIRED_DATABASE_DIR_NAME = "retired_legacy_databases"
DATABASE_TEST_MODE_ENV = "PMSYSTEM_TEST_MODE"


def local_app_data_dir() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def source_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    return local_app_data_dir() / APP_VENDOR_DIR_NAME / APP_DATA_DIR_NAME


def canonical_database_dir() -> Path:
    return local_app_data_dir() / APP_DATA_DIR_NAME / DATABASE_DIR_NAME


def get_canonical_database_path() -> Path:
    """Return the only production database path used by every runtime."""
    return canonical_database_dir() / DATABASE_FILE_NAME


def retired_database_root() -> Path:
    return local_app_data_dir() / APP_DATA_DIR_NAME / RETIRED_DATABASE_DIR_NAME


def database_test_mode_enabled() -> bool:
    return os.environ.get(DATABASE_TEST_MODE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def validate_test_database_path(path: str | Path) -> Path:
    """Reject test databases outside the system temporary directory."""
    resolved = Path(path).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError(f"测试数据库必须位于系统临时目录：{resolved}") from exc

    forbidden_roots = (
        canonical_database_dir().resolve(),
        app_data_dir().resolve(),
        source_app_dir().resolve(),
        retired_database_root().resolve(),
    )
    for forbidden_root in forbidden_roots:
        try:
            resolved.relative_to(forbidden_root)
        except ValueError:
            continue
        raise RuntimeError(f"测试数据库禁止访问真实或隔离数据目录：{resolved}")
    return resolved


def validate_runtime_database_path(path: str | Path) -> Path:
    """Allow production only on the canonical path and tests only in temp."""
    if database_test_mode_enabled():
        return validate_test_database_path(path)
    resolved = Path(path).expanduser().resolve()
    canonical = get_canonical_database_path().expanduser().resolve()
    if os.path.normcase(os.path.normpath(str(resolved))) != os.path.normcase(os.path.normpath(str(canonical))):
        raise RuntimeError(f"PMSystem 只允许使用正式数据库：{canonical}")
    return resolved
