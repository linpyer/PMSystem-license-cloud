from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/release/audit_protocol_identity.py"
SPEC = importlib.util.spec_from_file_location("audit_protocol_identity", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_protocol_identity_dry_run_is_offline_and_preserves_history():
    result = module.audit()
    assert result["mode"] == "OFFLINE_SCHEMA_DRY_RUN"
    assert result["productionConnected"] is False
    assert result["productionWrites"] is False
    assert result["activeLicenseProduct"] == "iVRec"
    assert result["activeUpdateProduct"] == "iVRec"
    assert result["legacyLicenseProduct"] == "DDREC"
    assert result["schemaChecks"] == {
        "licenseHasProductColumn": False,
        "clientReleaseHasProductColumn": True,
        "appVersionPolicyHasProductColumn": True,
    }
    assert result["databasePlan"]["licenses"].startswith("NO_ROW_REWRITE")
    assert result["databasePlan"]["clientReleases"].startswith("NO_HISTORY_REWRITE")
