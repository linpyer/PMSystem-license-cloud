from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import requests

from app.core.version import APP_VERSION
from app.licensing.constants import license_api_base_url
from app.licensing.errors import LicenseApiError


LICENSE_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_license_code(value: str) -> str:
    compact = re.sub(r"[\s-]+", "", str(value or "").upper())
    if compact.startswith("PMS"):
        compact = compact[3:]
    if len(compact) != 16 or any(char not in LICENSE_CODE_ALPHABET for char in compact):
        raise LicenseApiError("INVALID_REQUEST", "Invalid license code format")
    return "PMS-" + "-".join(compact[index : index + 4] for index in range(0, 16, 4))


class LicenseApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        allow_insecure_http: bool | None = None,
        session: requests.Session | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_url = (base_url or license_api_base_url()).rstrip("/")
        self.connect_timeout = float(
            connect_timeout or os.getenv("PMSYSTEM_LICENSE_CONNECT_TIMEOUT", "3")
        )
        self.read_timeout = float(read_timeout or os.getenv("PMSYSTEM_LICENSE_READ_TIMEOUT", "8"))
        if allow_insecure_http is None:
            configured = os.getenv("PMSYSTEM_LICENSE_ALLOW_INSECURE_HTTP")
            if configured is not None:
                allow_insecure_http = configured.lower() in {"1", "true", "yes", "on"}
            else:
                environment = os.getenv("PMSYSTEM_LICENSE_ENVIRONMENT", "development").lower()
                host = (urlparse(self.base_url).hostname or "").lower()
                allow_insecure_http = environment in {"development", "test"} and host in {
                    "127.0.0.1",
                    "localhost",
                    "::1",
                }
        if self.base_url.startswith("http://") and not allow_insecure_http:
            raise LicenseApiError(
                "INVALID_REQUEST", "Insecure license API HTTP is disabled for this environment"
            )
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": f"PMSystem/{APP_VERSION} (Windows)"}
        )
        self.logger = logger or logging.getLogger(__name__)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", None, request_id=str(uuid4()))

    def activate(self, code: str, identity) -> dict[str, Any]:
        return self._request(
            "POST",
            "/licenses/activate",
            {
                "licenseCode": normalize_license_code(code),
                "deviceId": identity.device_id,
                "fingerprintVersion": identity.fingerprint_version,
                "deviceName": identity.device_name,
                "osVersion": identity.os_version,
                "appVersion": APP_VERSION,
                "requestId": str(uuid4()),
                "clientTime": utc_now_iso(),
            },
        )

    def verify(self, record) -> dict[str, Any]:
        return self._credential_request("/licenses/verify", record, include_client_time=True)

    def refresh(self, record) -> dict[str, Any]:
        return self._credential_request("/licenses/refresh", record, include_client_time=True)

    def deactivate(self, record, reason: str) -> dict[str, Any]:
        body = {
            "licenseId": record.license_id,
            "deviceId": record.device_id,
            "credential": record.credential,
            "reason": str(reason or "")[:500],
            "requestId": str(uuid4()),
        }
        return self._request("POST", "/licenses/deactivate", body)

    def _credential_request(self, endpoint: str, record, *, include_client_time: bool) -> dict[str, Any]:
        body = {
            "licenseId": record.license_id,
            "deviceId": record.device_id,
            "credential": record.credential,
            "appVersion": APP_VERSION,
            "requestId": str(uuid4()),
        }
        if include_client_time:
            body["clientTime"] = utc_now_iso()
        return self._request("POST", endpoint, body)

    def _request(
        self,
        method: str,
        endpoint: str,
        body: dict[str, Any] | None,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        request_id = request_id or str((body or {}).get("requestId") or uuid4())
        started = time.perf_counter()
        url = f"{self.base_url}{endpoint}"
        response = None
        for attempt in range(2):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=body,
                    timeout=(self.connect_timeout, self.read_timeout),
                )
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == 0:
                    continue
                self.logger.warning(
                    "授权服务网络请求失败：endpoint=%s, request_id=%s, elapsed_ms=%.1f",
                    endpoint,
                    request_id,
                    (time.perf_counter() - started) * 1000,
                )
                raise LicenseApiError(
                    "SERVER_TEMPORARILY_UNAVAILABLE",
                    "License server is temporarily unavailable",
                    True,
                ) from exc
            except requests.RequestException as exc:
                raise LicenseApiError(
                    "SERVER_TEMPORARILY_UNAVAILABLE",
                    "License service request failed",
                    False,
                ) from exc
        if response is None:
            raise LicenseApiError("SERVER_TEMPORARILY_UNAVAILABLE", "No server response", True)
        try:
            payload = response.json()
        except ValueError as exc:
            raise LicenseApiError(
                "SERVER_TEMPORARILY_UNAVAILABLE",
                "License server returned an invalid response",
                response.status_code >= 500,
                status_code=response.status_code,
            ) from exc
        if response.status_code >= 400 or not bool(payload.get("success", False)):
            error = payload.get("error") if isinstance(payload, dict) else {}
            error = error if isinstance(error, dict) else {}
            raise LicenseApiError(
                str(error.get("code") or "SERVER_TEMPORARILY_UNAVAILABLE"),
                str(error.get("message") or "License request failed"),
                bool(error.get("retryable", response.status_code >= 500)),
                str(payload.get("traceId") or "") if isinstance(payload, dict) else "",
                status_code=response.status_code,
            )
        self.logger.info(
            "授权服务请求完成：endpoint=%s, request_id=%s, elapsed_ms=%.1f",
            endpoint,
            request_id,
            (time.perf_counter() - started) * 1000,
        )
        return payload
