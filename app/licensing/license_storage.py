from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.licensing.dpapi_storage import WindowsDpapiProtector
from app.licensing.errors import LicenseStorageError
from app.licensing.models import LocalLicenseRecord


def default_license_path() -> Path:
    override = (
        ""
        if getattr(sys, "frozen", False)
        else os.getenv("DDREC_LICENSE_STORAGE_PATH", "").strip()
    )
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise LicenseStorageError("LOCALAPPDATA is unavailable")
    return Path(local_app_data) / "DDREC" / "license" / "license.dat"


class LicenseStorage:
    def __init__(self, path: str | Path | None = None, protector=None, logger=None) -> None:
        self.path = Path(path) if path is not None else default_license_path()
        self.protector = protector or WindowsDpapiProtector()
        self.logger = logger

    def load(self) -> LocalLicenseRecord | None:
        if not self.path.exists():
            return None
        try:
            encrypted = self.path.read_bytes()
            plaintext = self.protector.unprotect(encrypted)
            payload = json.loads(plaintext.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("license data is not an object")
            return LocalLicenseRecord.from_mapping(payload)
        except Exception as exc:
            isolated = self._isolate_corrupt_file()
            if self.logger:
                self.logger.error("本地授权文件损坏，已隔离：path=%s", isolated)
            raise LicenseStorageError("The local license file is damaged") from exc

    def save(self, record: LocalLicenseRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(
            record.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        encrypted = self.protector.protect(plaintext)
        temporary = self.path.with_name(f"{self.path.name}.tmp-{uuid4().hex}")
        try:
            with temporary.open("xb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise LicenseStorageError("Unable to save the local license atomically") from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise LicenseStorageError("Unable to remove the local license file") from exc

    def _isolate_corrupt_file(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}")
        counter = 1
        while target.exists():
            target = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}-{counter}")
            counter += 1
        try:
            self.path.replace(target)
        except OSError as exc:
            raise LicenseStorageError("Unable to isolate the damaged license file") from exc
        return target
