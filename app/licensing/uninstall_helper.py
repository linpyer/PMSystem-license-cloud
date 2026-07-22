from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from app.licensing.dpapi_storage import WindowsDpapiProtector
from app.licensing.license_api import LicenseApiClient
from app.licensing.license_storage import default_license_path
from app.licensing.models import LocalLicenseRecord


MAX_UNINSTALL_WAIT_SECONDS = 6.0


def _load_record_without_modifying_storage(
    path: Path,
    protector: WindowsDpapiProtector,
) -> LocalLicenseRecord | None:
    if not path.is_file():
        return None
    plaintext = protector.unprotect(path.read_bytes())
    payload = json.loads(plaintext.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("license data is not an object")
    return LocalLicenseRecord.from_mapping(payload)


def deactivate_before_uninstall(
    *,
    path: Path | None = None,
    protector: WindowsDpapiProtector | None = None,
    api: LicenseApiClient | None = None,
) -> bool:
    license_path = path or default_license_path()
    try:
        record = _load_record_without_modifying_storage(
            license_path,
            protector or WindowsDpapiProtector(),
        )
        if record is None:
            return True
        response = (api or LicenseApiClient(connect_timeout=2, read_timeout=3)).deactivate(
            record,
            "uninstall",
        )
        if not bool(response.get("deactivated", False)):
            return False
        license_path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _run_with_timeout() -> bool:
    result = {"success": False}

    def worker() -> None:
        result["success"] = deactivate_before_uninstall()

    thread = threading.Thread(target=worker, name="license-uninstall-deactivate", daemon=True)
    thread.start()
    thread.join(MAX_UNINSTALL_WAIT_SECONDS)
    return not thread.is_alive() and result["success"]


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["--deactivate-before-uninstall"]:
        return 0
    _run_with_timeout()
    # Uninstall must continue even when deactivation is offline or times out.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
