from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from app.licensing.constants import LicenseCapability, LicenseStatus
from app.licensing.device_fingerprint import DeviceIdentity, WindowsDeviceFingerprint
from app.licensing.errors import LicenseApiError, LicenseStorageError, LicenseValidationError
from app.licensing.license_api import LicenseApiClient
from app.licensing.license_crypto import LicenseVerifier, TrustedPublicKeys
from app.licensing.license_gate import LicenseGate
from app.licensing.license_policy import LicensePolicy
from app.licensing.license_storage import LicenseStorage
from app.licensing.models import LocalLicenseRecord, LicensePayload, SignedLicense
from app.utils.runtime_paths import resource_path


REMOTE_STATUS_ERRORS = {
    "LICENSE_EXPIRED": LicenseStatus.EXPIRED,
    "LICENSE_DISABLED": LicenseStatus.DISABLED,
    "LICENSE_REVOKED": LicenseStatus.REVOKED,
    "DEVICE_MISMATCH": LicenseStatus.DEVICE_MISMATCH,
    "DEVICE_DISABLED": LicenseStatus.DISABLED,
    "INVALID_CREDENTIAL": LicenseStatus.INVALID_LICENSE,
}


class LicenseManager(QObject):
    status_changed = Signal(str)
    license_updated = Signal()

    def __init__(
        self,
        *,
        api: LicenseApiClient | None = None,
        storage: LicenseStorage | None = None,
        verifier: LicenseVerifier | None = None,
        fingerprint_provider=None,
        policy: LicensePolicy | None = None,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__()
        self.logger = logger or logging.getLogger(__name__)
        self.api = api or LicenseApiClient(logger=self.logger)
        self.storage = storage or LicenseStorage(logger=self.logger)
        if verifier is None:
            keys_path = resource_path("app/assets/license/public_keys.json")
            verifier = LicenseVerifier(TrustedPublicKeys.from_json_file(keys_path))
        self.verifier = verifier
        self.fingerprint_provider = fingerprint_provider or WindowsDeviceFingerprint()
        self.policy = policy or LicensePolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._identity: DeviceIdentity | None = None
        self._record: LocalLicenseRecord | None = None
        self._payload: LicensePayload | None = None
        self._status = LicenseStatus.UNLICENSED
        self._server_reachable: bool | None = None
        self._last_error_code = ""
        self.gate = LicenseGate(self.get_status)

    def initialize(self) -> LicenseStatus:
        with self._lock:
            self._identity = self.fingerprint_provider.collect()
            try:
                record = self.storage.load()
            except LicenseStorageError:
                self._record = None
                self._payload = None
                return self._set_status(LicenseStatus.INVALID_LICENSE)
            if record is None:
                return self._set_status(LicenseStatus.UNLICENSED)
            try:
                payload = self.verifier.verify(
                    record.signed_license, expected_device_id=self.identity.device_id
                )
            except LicenseValidationError as exc:
                self.logger.warning("本地许可证验签失败：%s", exc)
                self._record = record
                self._payload = None
                return self._set_status(LicenseStatus.INVALID_LICENSE)
            if record.device_id != self.identity.device_id:
                self._record = record
                self._payload = payload
                return self._set_status(LicenseStatus.DEVICE_MISMATCH)
            self._record = record
            self._payload = payload
            remembered_status = REMOTE_STATUS_ERRORS.get(record.remote_status)
            if remembered_status is not None:
                return self._set_status(remembered_status)
            status = self.policy.evaluate(
                payload, now=self.clock(), last_seen_utc=record.last_seen_utc
            )
            if status != LicenseStatus.CLOCK_ROLLBACK_SUSPECTED:
                record.last_seen_utc = max(record.last_seen_utc, self.clock())
                try:
                    self.storage.save(record)
                except LicenseStorageError:
                    self.logger.exception("更新授权 lastSeenUtc 失败，保留现有授权状态")
            return self._set_status(status)

    @property
    def identity(self) -> DeviceIdentity:
        if self._identity is None:
            self._identity = self.fingerprint_provider.collect()
        return self._identity

    def get_status(self) -> LicenseStatus:
        return self._status

    def get_license_info(self) -> dict[str, Any]:
        payload = self._payload
        return {
            "status": self._status,
            "licenseId": payload.license_id if payload else "",
            "licenseType": payload.license_type if payload else "",
            "edition": payload.edition if payload else "",
            "expiresAt": payload.expires_at if payload else None,
            "lastVerifiedAt": payload.last_verified_at if payload else None,
            "nextRequiredVerifyAt": payload.next_required_verify_at if payload else None,
            "graceUntil": payload.grace_until if payload else None,
            "deviceId": self.identity.device_id,
            "fingerprintVersion": self.identity.fingerprint_version,
            "serverReachable": self._server_reachable,
            "lastErrorCode": self._last_error_code,
        }

    def activate(self, code: str) -> LicenseStatus:
        with self._operation_lock:
            response = self.api.activate(code, self.identity)
            credential = str(response.get("credential") or "")
            if not credential:
                raise LicenseValidationError("Activation response did not include a device credential")
            self._apply_server_license(response, credential=credential)
            self._server_reachable = True
            self._last_error_code = ""
            return self._status

    def verify_online(self) -> LicenseStatus:
        with self._operation_lock:
            record = self._require_record()
            try:
                response = self.api.verify(record)
                self._apply_server_license(response, credential=record.credential)
                self._server_reachable = True
                self._last_error_code = ""
                return self._status
            except LicenseApiError as exc:
                return self._handle_api_error(exc)

    def refresh_license(self) -> LicenseStatus:
        with self._operation_lock:
            record = self._require_record()
            try:
                response = self.api.refresh(record)
                self._apply_server_license(response, credential=record.credential)
                self._server_reachable = True
                self._last_error_code = ""
                return self._status
            except LicenseApiError as exc:
                return self._handle_api_error(exc)

    def deactivate(self, reason: str = "user_requested") -> LicenseStatus:
        with self._operation_lock:
            record = self._require_record()
            response = self.api.deactivate(record, reason)
            if not bool(response.get("deactivated", False)):
                raise LicenseApiError("SERVER_TEMPORARILY_UNAVAILABLE", "Deactivation was not confirmed")
            self.storage.delete()
            with self._lock:
                self._record = None
                self._payload = None
                self._server_reachable = True
                self._last_error_code = ""
                return self._set_status(LicenseStatus.UNLICENSED)

    def can_start_recording(self, record_type: str = "发货") -> bool:
        capability = (
            LicenseCapability.START_RETURN_RECORDING
            if record_type == "退货"
            else LicenseCapability.START_SHIPPING_RECORDING
        )
        return self.gate.allows(capability)

    def can_upload(self) -> bool:
        return self.gate.allows(LicenseCapability.CLOUD_UPLOAD)

    def can_auto_sync(self) -> bool:
        return self.gate.allows(LicenseCapability.AUTO_SYNC)

    def enter_restricted_mode(self) -> LicenseStatus:
        return self._set_status(LicenseStatus.RESTRICTED)

    def subscribe_status_changed(self, callback) -> None:
        self.status_changed.connect(callback)

    def should_verify_in_background(self) -> bool:
        return self._status in {
            LicenseStatus.VERIFY_RECOMMENDED,
            LicenseStatus.OFFLINE_GRACE,
            LicenseStatus.CLOCK_ROLLBACK_SUSPECTED,
        }

    def _apply_server_license(self, response: dict[str, Any], *, credential: str) -> None:
        license_data = response.get("license")
        if not isinstance(license_data, dict):
            raise LicenseValidationError("Server response did not include a signed license")
        envelope = SignedLicense.from_mapping(license_data)
        payload = self.verifier.verify(envelope, expected_device_id=self.identity.device_id)
        now = self.clock().astimezone(timezone.utc)
        record = LocalLicenseRecord(
            schema_version=1,
            license_id=payload.license_id,
            device_id=self.identity.device_id,
            fingerprint_version=self.identity.fingerprint_version,
            signed_license=envelope,
            credential=credential,
            saved_at=now,
            last_seen_utc=now,
            remote_status="",
        )
        self.storage.save(record)
        with self._lock:
            self._record = record
            self._payload = payload
            status = self.policy.evaluate(payload, now=now, last_seen_utc=now)
            self._set_status(status)
            self.license_updated.emit()

    def _handle_api_error(self, error: LicenseApiError) -> LicenseStatus:
        self._last_error_code = error.code
        self._server_reachable = error.code != "SERVER_TEMPORARILY_UNAVAILABLE"
        forced = REMOTE_STATUS_ERRORS.get(error.code)
        if forced is not None:
            if self._record is not None:
                self._record.remote_status = error.code
                try:
                    self.storage.save(self._record)
                except LicenseStorageError:
                    self.logger.exception("保存服务端授权限制状态失败：code=%s", error.code)
            return self._set_status(forced)
        if self._payload is not None and self._record is not None:
            local_status = self.policy.evaluate(
                self._payload, now=self.clock(), last_seen_utc=self._record.last_seen_utc
            )
            return self._set_status(local_status)
        return self._set_status(LicenseStatus.SERVER_UNAVAILABLE)

    def _require_record(self) -> LocalLicenseRecord:
        if self._record is None or not self._record.credential:
            raise LicenseValidationError("No local device license is available")
        return self._record

    def _set_status(self, status: LicenseStatus) -> LicenseStatus:
        changed = status != self._status
        self._status = status
        if changed:
            self.logger.info("授权状态变化：%s", status.value)
            self.status_changed.emit(status.value)
        return status
