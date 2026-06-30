from __future__ import annotations

from pathlib import Path


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def human_file_size(size_bytes: int) -> str:
    size = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def find_unfinished_recordings(video_dir: Path) -> list[Path]:
    if not video_dir.exists():
        return []

    patterns = [
        "*.recording.mp4",
        "*.recording.avi",
        "*.recording.mov",
        "*_temp.mp4",
        "*_temp.avi",
        "*_temp.mov",
    ]
    found: list[Path] = []
    for pattern in patterns:
        found.extend(video_dir.glob(pattern))

    def modified_time(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0

    return sorted(set(found), key=modified_time, reverse=True)
