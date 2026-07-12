from __future__ import annotations

import sys
from pathlib import Path

from app.core.database_paths import app_data_dir
from app.core.version import APP_DATA_DIR_NAME

APP_DIR_NAME = APP_DATA_DIR_NAME


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(relative_path: str | Path) -> Path:
    relative = Path(relative_path)
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return (base / relative).resolve()


def user_data_dir() -> Path:
    return app_data_dir()
