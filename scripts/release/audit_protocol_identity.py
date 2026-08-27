from __future__ import annotations

import json
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[2] / "license-server"
IDENTITY_SOURCE = SERVER_ROOT / "app/core/product_identity.py"
MODEL_ROOT = SERVER_ROOT / "app/db/models"


def audit() -> dict[str, object]:
    identity = IDENTITY_SOURCE.read_text(encoding="utf-8")
    license_model = (MODEL_ROOT / "license.py").read_text(encoding="utf-8")
    release_model = (MODEL_ROOT / "client_release.py").read_text(encoding="utf-8")
    policy_model = (MODEL_ROOT / "app_version_policy.py").read_text(encoding="utf-8")
    active_is_current = (
        'TARGET_LICENSE_PROTOCOL_PRODUCT = "iVRec"' in identity
        and "ACTIVE_LICENSE_PROTOCOL_PRODUCT = TARGET_LICENSE_PROTOCOL_PRODUCT" in identity
        and 'TARGET_UPDATE_PROTOCOL_PRODUCT = "iVRec"' in identity
        and "ACTIVE_UPDATE_PROTOCOL_PRODUCT = TARGET_UPDATE_PROTOCOL_PRODUCT" in identity
    )
    if not active_is_current:
        raise RuntimeError("server protocol identity is not fully switched to iVRec")
    return {
        "mode": "OFFLINE_SCHEMA_DRY_RUN",
        "productionConnected": False,
        "productionWrites": False,
        "activeLicenseProduct": "iVRec",
        "activeUpdateProduct": "iVRec",
        "legacyLicenseProduct": "DDREC",
        "legacyUpdateProduct": "DDREC",
        "databasePlan": {
            "licenses": "NO_ROW_REWRITE; table has no product column; re-sign on refresh/activation",
            "licenseEvents": "NO_HISTORY_REWRITE",
            "clientReleases": "NO_HISTORY_REWRITE; retain DDREC rows and create iVRec rows",
            "appVersionPolicies": "CREATE_IVREC_ROW_IF_ABSENT; retain DDREC row",
        },
        "schemaChecks": {
            "licenseHasProductColumn": "product: Mapped" in license_model,
            "clientReleaseHasProductColumn": "product: Mapped" in release_model,
            "appVersionPolicyHasProductColumn": "product: Mapped" in policy_model,
        },
    }


def main() -> int:
    print(json.dumps(audit(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
