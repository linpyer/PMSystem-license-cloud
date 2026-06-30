from __future__ import annotations

from datetime import datetime


def format_datetime(value: datetime | None = None) -> str:
    value = value or datetime.now()
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
