from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

from app.licensing.errors import LicenseApiError, LicenseValidationError, localized_error


class LicenseOperationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, operation: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self.operation = operation

    def run(self) -> None:  # type: ignore[override]
        try:
            self.succeeded.emit(self.operation())
        except LicenseApiError as exc:
            self.failed.emit(exc.code, localized_error(exc))
        except LicenseValidationError as exc:
            self.failed.emit("CLIENT_VALIDATION_ERROR", str(exc))
        except Exception as exc:
            self.failed.emit("CLIENT_LICENSE_ERROR", str(exc) or "授权操作失败")
