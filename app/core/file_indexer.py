from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.utils.file_utils import human_file_size
from app.utils.filename import tracking_number_from_video_name


VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


@dataclass(frozen=True)
class VideoEntry:
    path: Path
    tracking_number: str
    name: str
    extension: str
    size_text: str
    recorded_at: datetime


def scan_video_files(video_dir: Path) -> list[VideoEntry]:
    video_dir.mkdir(parents=True, exist_ok=True)

    entries: list[VideoEntry] = []
    for path in video_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if ".recording." in path.name:
            continue

        try:
            stat_result = path.stat()
        except OSError:
            continue

        created = stat_result.st_ctime or stat_result.st_mtime
        recorded_at = datetime.fromtimestamp(created)
        entries.append(
            VideoEntry(
                path=path,
                tracking_number=tracking_number_from_video_name(path.name),
                name=path.name,
                extension=path.suffix.lstrip(".").upper(),
                size_text=human_file_size(stat_result.st_size),
                recorded_at=recorded_at,
            )
        )

    return sorted(entries, key=lambda entry: entry.recorded_at, reverse=True)
