from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any


ALLOWED_CODE_CHAR = re.compile(r"[A-Za-z0-9_-]")


@dataclass(frozen=True)
class ScannerGuardResult:
    raw_code: str
    cleaned_code: str
    is_empty: bool
    is_duplicate: bool
    is_cleaned: bool
    should_warn: bool
    warning_message: str
    should_ignore: bool
    removed_chars_count: int


class ScannerGuard:
    def __init__(self, config: dict[str, Any] | None = None, logger: logging.Logger | None = None) -> None:
        self.config = dict(config or {})
        self.logger = logger
        self._last_code = ""
        self._last_time = 0.0

    def update_config(self, config: dict[str, Any] | None) -> None:
        self.config = dict(config or {})

    def process(self, raw_code: str, *, debounce: bool = True) -> ScannerGuardResult:
        guard_config = self._guard_config()
        raw = str(raw_code or "")
        cleaned, removed_count = self._clean(raw, guard_config)
        is_empty = cleaned == ""
        is_cleaned = cleaned != raw.strip()
        now = time.monotonic()

        debounce_enabled = bool(guard_config.get("debounce_enabled", True)) and debounce
        debounce_seconds = float(guard_config.get("debounce_seconds", 1) or 1)
        is_duplicate = (
            debounce_enabled
            and not is_empty
            and cleaned == self._last_code
            and now - self._last_time <= debounce_seconds
        )

        warnings: list[str] = []
        if is_duplicate:
            warnings.append("检测到重复扫码，已忽略。")
        elif is_cleaned:
            warnings.append("扫码内容包含特殊字符，已自动清洗。")

        if not is_empty and not is_duplicate:
            min_length = int(guard_config.get("min_length_warn", 6) or 6)
            max_length = int(guard_config.get("max_length_warn", 40) or 40)
            if len(cleaned) < min_length:
                warnings.append("单号长度较短，已继续录制。")
            elif len(cleaned) > max_length:
                warnings.append("单号长度较长，已继续录制。")

        if not is_duplicate:
            self._last_code = cleaned
            self._last_time = now

        result = ScannerGuardResult(
            raw_code=raw,
            cleaned_code=cleaned,
            is_empty=is_empty,
            is_duplicate=is_duplicate,
            is_cleaned=is_cleaned,
            should_warn=bool(warnings),
            warning_message=" ".join(warnings),
            should_ignore=is_duplicate,
            removed_chars_count=removed_count,
        )

        if self.logger:
            self.logger.info("扫码原始内容：%s", raw or "<空>")
            self.logger.info("扫码清洗后内容：%s", cleaned or "<空>")
            if is_duplicate:
                self.logger.warning("扫码重复触发被忽略：%s", cleaned)
            if result.should_warn and not is_duplicate:
                self.logger.warning("扫码软提示：%s", result.warning_message)

        return result

    def _guard_config(self) -> dict[str, Any]:
        if "scanner_guard" in self.config and isinstance(self.config.get("scanner_guard"), dict):
            return dict(self.config.get("scanner_guard") or {})
        return dict(self.config)

    @staticmethod
    def _clean(raw: str, guard_config: dict[str, Any]) -> tuple[str, int]:
        text = raw.strip().replace("\r", "").replace("\n", "").replace("\t", "")
        if not bool(guard_config.get("clean_special_chars", True)):
            return text, 0

        cleaned_chars: list[str] = []
        removed = 0
        for char in text:
            if ALLOWED_CODE_CHAR.fullmatch(char):
                cleaned_chars.append(char)
            else:
                removed += 1
        return "".join(cleaned_chars), removed
