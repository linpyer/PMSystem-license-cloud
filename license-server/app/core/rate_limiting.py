from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.core.errors import ErrorCode, LicenseServiceError


@dataclass(frozen=True, slots=True)
class LimitRule:
    namespace: str
    key: str
    maximum: int
    window_seconds: int


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


class ApplicationRateLimiter:
    """Single-instance limiter for the initial one-API-container deployment."""

    def __init__(self) -> None:
        self._entries: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def enforce(self, request: Request, body: bytes, client_ip: str | None) -> None:
        for rule in self._rules(request, body, client_ip):
            await self._consume(rule)

    async def _consume(self, rule: LimitRule) -> None:
        bucket_key = f"{rule.namespace}:{rule.key}"
        now = time.monotonic()
        cutoff = now - rule.window_seconds
        async with self._lock:
            entries = self._entries[bucket_key]
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= rule.maximum:
                raise LicenseServiceError(
                    ErrorCode.RATE_LIMITED,
                    "Too many requests. Please retry later.",
                    retryable=True,
                )
            entries.append(now)
            if len(self._entries) > 20_000:
                self._prune(cutoff)

    def _prune(self, cutoff: float) -> None:
        for key in list(self._entries):
            entries = self._entries[key]
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if not entries:
                self._entries.pop(key, None)

    @staticmethod
    def _rules(request: Request, body: bytes, client_ip: str | None) -> list[LimitRule]:
        path = request.url.path
        if request.method not in {"POST", "PATCH", "PUT", "DELETE"}:
            return []
        ip_key = client_ip or "unknown"
        payload: dict[str, Any] = {}
        if body:
            try:
                decoded = json.loads(body)
                if isinstance(decoded, dict):
                    payload = decoded
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass

        if path.endswith("/admin/auth/login"):
            return [
                LimitRule("admin-login-ip", ip_key, 15, 300),
                LimitRule("admin-login-account", _digest(payload.get("username")), 10, 300),
            ]
        if path.endswith("/admin/auth/totp/verify"):
            return [
                LimitRule("admin-totp-ip", ip_key, 20, 300),
                LimitRule("admin-totp-challenge", _digest(payload.get("challenge")), 8, 300),
            ]
        if path.endswith("/licenses/activate"):
            return [
                LimitRule("activate-ip", ip_key, 40, 300),
                LimitRule("activate-code", _digest(payload.get("licenseCode")), 15, 300),
                LimitRule("activate-device", _digest(payload.get("deviceId")), 20, 300),
            ]
        if path.endswith("/trials/activate"):
            return [
                LimitRule("trial-activate-ip", ip_key, 40, 300),
                LimitRule("trial-activate-device", _digest(payload.get("deviceId")), 10, 300),
            ]
        if path.endswith(("/licenses/verify", "/licenses/refresh", "/licenses/deactivate")):
            return [
                LimitRule("client-license", _digest(payload.get("licenseId")), 180, 60),
                LimitRule("client-device", _digest(payload.get("deviceId")), 180, 60),
            ]
        if path.endswith(("/admin/licenses", "/admin/licenses/batch")):
            cookie = request.cookies.get(request.app.state.settings.admin_cookie_name, "")
            return [LimitRule("admin-create", _digest(cookie or ip_key), 30, 60)]
        return [LimitRule("write-ip", ip_key, 300, 60)]
