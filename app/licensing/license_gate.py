from __future__ import annotations

from collections.abc import Callable

from app.licensing.constants import (
    FULL_ACCESS_STATUSES,
    READ_ONLY_CAPABILITIES,
    LicenseCapability,
    LicenseStatus,
)


class LicenseGate:
    def __init__(self, status_provider: Callable[[], LicenseStatus]) -> None:
        self._status_provider = status_provider

    def allows(self, capability: LicenseCapability) -> bool:
        status = self._status_provider()
        if status in FULL_ACCESS_STATUSES:
            return True
        return capability in READ_ONLY_CAPABILITIES

    def require(self, capability: LicenseCapability) -> None:
        if not self.allows(capability):
            raise PermissionError(f"License status does not allow {capability.value}")
