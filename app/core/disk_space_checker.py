from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DiskSpaceResult:
    path: str
    total_gb: float
    used_gb: float
    free_gb: float
    level: str
    message: str


class DiskSpaceChecker:
    def __init__(self, config: dict[str, Any] | None = None, logger: logging.Logger | None = None) -> None:
        self.config = dict(config or {})
        self.logger = logger

    def check(self, path: str | Path) -> DiskSpaceResult:
        target = Path(path)
        try:
            target.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(str(target))
            total_gb = usage.total / 1024**3
            used_gb = usage.used / 1024**3
            free_gb = usage.free / 1024**3

            disk_config = self._disk_config()
            warning_gb = float(disk_config.get("warning_gb", 20) or 20)
            critical_gb = float(disk_config.get("critical_gb", 10) or 10)

            if free_gb <= critical_gb:
                level = "critical"
                message = f"当前视频保存盘剩余空间不足 {critical_gb:g}GB，可能导致录制失败，请尽快处理。"
            elif free_gb <= warning_gb:
                level = "warning"
                message = f"当前视频保存盘剩余空间不足 {warning_gb:g}GB，请及时转移或扩容。"
            else:
                level = "ok"
                message = f"磁盘空间正常，剩余 {free_gb:.2f}GB。"

            result = DiskSpaceResult(str(target), total_gb, used_gb, free_gb, level, message)
            if self.logger and level in {"warning", "critical"}:
                self.logger.warning(
                    "硬盘空间不足提醒：path=%s, total=%.2fGB, used=%.2fGB, free=%.2fGB, level=%s",
                    result.path,
                    result.total_gb,
                    result.used_gb,
                    result.free_gb,
                    result.level,
                )
            return result
        except Exception as exc:
            if self.logger:
                self.logger.exception("硬盘空间检查异常：%s", target)
            return DiskSpaceResult(str(target), 0.0, 0.0, 0.0, "error", f"硬盘空间检查异常：{exc}")

    def _disk_config(self) -> dict[str, Any]:
        if "disk_space" in self.config and isinstance(self.config.get("disk_space"), dict):
            return dict(self.config.get("disk_space") or {})
        return dict(self.config)
