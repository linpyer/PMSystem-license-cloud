from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(value: str, fallback: str = "未命名单号") -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip(" ._")
    if not cleaned:
        cleaned = fallback
    return cleaned[:120]


def normalize_extension(extension: str) -> str:
    extension = extension.lower().strip().lstrip(".")
    return extension or "mp4"


def dated_video_dir(video_dir: Path, timestamp: datetime | None = None) -> Path:
    recorded_at = timestamp or datetime.now()
    return video_dir / recorded_at.strftime("%Y") / recorded_at.strftime("%m") / recorded_at.strftime("%d")


def unique_video_path(
    video_dir: Path,
    order_id: str,
    extension: str = "mp4",
    timestamp: datetime | None = None,
) -> Path:
    recorded_at = timestamp or datetime.now()
    save_dir = dated_video_dir(video_dir, recorded_at)
    save_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(order_id)
    ext = normalize_extension(extension)
    timestamp_text = recorded_at.strftime("%Y%m%d_%H%M%S")
    candidate = save_dir / f"{safe_name}_{timestamp_text}.{ext}"
    if not candidate.exists():
        return candidate

    counter = 1
    while candidate.exists():
        candidate = save_dir / f"{safe_name}_{timestamp_text}_{counter}.{ext}"
        counter += 1
    return candidate


def unique_temp_recording_path(
    video_dir: Path,
    order_id: str,
    extension: str = "mp4",
    timestamp: datetime | None = None,
) -> Path:
    save_dir = dated_video_dir(video_dir, timestamp)
    save_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(order_id)
    ext = normalize_extension(extension)
    candidate = save_dir / f"{safe_name}.recording.{ext}"
    if not candidate.exists():
        return candidate

    timestamp_text = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = save_dir / f"{safe_name}_{timestamp_text}.recording.{ext}"
    counter = 1
    while candidate.exists():
        candidate = save_dir / f"{safe_name}_{timestamp_text}_{counter}.recording.{ext}"
        counter += 1
    return candidate


def tracking_number_from_video_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"\.recording$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_\d{8}_\d{6}(?:_\d+)?$", "", stem)
    return stem
