from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
COMMON = ROOT / "deploy" / "production-release" / "common-release.sh"
GUARD = ROOT / "deploy" / "production-release" / "verify-api-image-identity.py"
COMPOSE = ROOT / "deploy" / "production-nginx" / "compose.yml"
DEPLOY = ROOT / "deploy" / "production-release" / "deploy-release.sh"
HEALTH = ROOT / "deploy" / "production-release" / "health-check.sh"

COMMIT = "a" * 40
IMAGE = "ddrec-license-api:1.4.0-aaaaaaa-production"
IMAGE_ID = "sha256:" + "b" * 64


def run_guard(**overrides: str) -> subprocess.CompletedProcess[str]:
    values = {
        "expected_image": IMAGE,
        "compose_image": IMAGE,
        "running_image": IMAGE,
        "running_image_id": IMAGE_ID,
        "expected_image_id": IMAGE_ID,
        "oci_revision": COMMIT,
        "expected_commit": COMMIT,
    }
    values.update(overrides)
    args = [sys.executable, str(GUARD)]
    for key, value in values.items():
        args.extend(("--" + key.replace("_", "-"), value))
    return subprocess.run(args, capture_output=True, text=True, check=False)


def resolve_with_shell_value(tmp_path: Path, shell_value: str | None) -> str:
    env_file = tmp_path / "production.env"
    env_file.write_text("DDREC_API_IMAGE_TAG=NEW_IMAGE\n", encoding="utf-8")
    exported = (
        "export DDREC_API_IMAGE_TAG=OLD_IMAGE"
        if shell_value is not None
        else "unset DDREC_API_IMAGE_TAG"
    )
    script = f"""
set -Eeuo pipefail
source '{COMMON.as_posix()}'
docker() {{
  local env_file='' tag=''
  while (($#)); do
    if [[ "$1" == '--env-file' ]]; then env_file="$2"; shift 2; else shift; fi
  done
  tag="${{DDREC_API_IMAGE_TAG:-}}"
  if [[ -z "${{tag}}" ]]; then
    tag="$(sed -n 's/^DDREC_API_IMAGE_TAG=//p' "${{env_file}}" | tail -1)"
  fi
  printf 'ddrec-license-api:%s\n' "${{tag}}"
}}
{exported}
compose_at /fixture '{env_file.as_posix()}' config --images
"""
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False, env=os.environ
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_stale_shell_image_tag_cannot_override_new_env_file(tmp_path: Path) -> None:
    assert resolve_with_shell_value(tmp_path, "OLD_IMAGE") == "ddrec-license-api:NEW_IMAGE"


def test_clean_shell_resolves_new_env_file(tmp_path: Path) -> None:
    assert resolve_with_shell_value(tmp_path, None) == "ddrec-license-api:NEW_IMAGE"


def test_compose_managed_vars_cover_every_production_substitution() -> None:
    substitutions = set(re.findall(r"\$\{([A-Z0-9_]+)", COMPOSE.read_text(encoding="utf-8")))
    common = COMMON.read_text(encoding="utf-8")
    managed_block = common.split("COMPOSE_MANAGED_ENV_VARS=(", 1)[1].split(")", 1)[0]
    managed = set(re.findall(r"^\s+([A-Z0-9_]+)\s*$", managed_block, re.MULTILINE))
    assert substitutions <= managed
    assert {"LICENSE_SERVICE_VERSION", "LICENSE_BUILD_COMMIT"} <= managed


def test_all_deployment_identities_match() -> None:
    result = run_guard()
    assert result.returncode == 0
    assert "DEPLOY_IDENTITY=PASS" in result.stdout


def test_new_health_metadata_cannot_hide_old_running_image() -> None:
    result = run_guard(running_image="ddrec-license-api:1.3.0-old-production")
    assert result.returncode == 40
    assert "reason=running-image" in result.stdout


def test_compose_image_reference_mismatch_fails_closed() -> None:
    result = run_guard(compose_image="ddrec-license-api:stale")
    assert result.returncode == 40
    assert "reason=compose-image" in result.stdout


def test_running_image_id_mismatch_fails_closed() -> None:
    result = run_guard(running_image_id="sha256:" + "c" * 64)
    assert result.returncode == 40
    assert "reason=image-id" in result.stdout


def test_oci_revision_mismatch_fails_closed() -> None:
    result = run_guard(oci_revision="d" * 40)
    assert result.returncode == 40
    assert "reason=oci-revision" in result.stdout


@pytest.mark.parametrize("field", ["running_image_id", "expected_image_id", "expected_commit"])
def test_malformed_identity_input_fails_closed(field: str) -> None:
    result = run_guard(**{field: "invalid"})
    assert result.returncode == 10
    assert "DEPLOY_IDENTITY=FAIL" in result.stdout


def test_untrusted_expected_image_reference_fails_closed() -> None:
    result = run_guard(expected_image="example.invalid/foreign:latest")
    assert result.returncode == 10
    assert "invalid-expected-image-reference" in result.stdout


def test_deploy_and_health_both_enforce_image_identity() -> None:
    deploy = DEPLOY.read_text(encoding="utf-8")
    health = HEALTH.read_text(encoding="utf-8")
    recreate = deploy.index('up -d --no-deps --pull never license-api')
    identity = deploy.index('verify_application_image_identity "${final}"', recreate)
    success = deploy.index("release deployed successfully")
    assert recreate < identity < success
    assert "DEPLOY_SEMANTIC_FAILURE" in deploy
    assert "verify_application_image_identity" in health
    assert "API version mismatch" in health
    assert "HEALTH_BUILD_COMMIT" in health
