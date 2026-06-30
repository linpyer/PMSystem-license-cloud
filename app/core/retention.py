from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


@dataclass
class RetentionResult:
    checked: int = 0
    deleted: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)


def delete_expired_videos(video_dir: Path, days: int, logger: logging.Logger) -> RetentionResult:
    result = RetentionResult()
    video_dir.mkdir(parents=True, exist_ok=True)

    if days <= 0:
        logger.info("自动清理已跳过：保留天数配置为 %s", days)
        return result

    cutoff = datetime.now() - timedelta(days=days)
    for path in video_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if ".recording." in path.name.lower():
            continue

        result.checked += 1
        try:
            stat_result = path.stat()
            timestamp = stat_result.st_ctime or stat_result.st_mtime
            recorded_at = datetime.fromtimestamp(timestamp)
            if recorded_at >= cutoff:
                continue

            path.unlink()
            result.deleted.append(path)
            logger.info("自动删除过期视频：%s", path)
        except OSError as exc:
            result.failed.append((path, str(exc)))
            logger.exception("自动删除过期视频失败：%s", path)

    logger.info(
        "启动自动清理完成：检查 %s 个视频，删除 %s 个，失败 %s 个，保留天数 %s",
        result.checked,
        len(result.deleted),
        len(result.failed),
        days,
    )
    return result
