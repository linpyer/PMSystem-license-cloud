from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
GUARD = ROOT / "deploy" / "production-release" / "verify-postgres-image.py"
EXECUTOR = ROOT / "deploy" / "production-release" / "deploy-release.sh"


def load_guard():
    spec = importlib.util.spec_from_file_location("verify_postgres_image", GUARD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NORMALIZE = load_guard().normalize_image_reference


def run_guard(current: str, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GUARD),
            "--current",
            current,
            "--target",
            target,
            "--current-image-id",
            "sha256:" + "a" * 64,
            "--current-repo-digests",
            "[]",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "value",
    [
        "postgres:17.5-alpine",
        '"postgres:17.5-alpine"',
        "postgres:17.5-alpine\n",
        "postgres:17.5-alpine\r\n",
        "  postgres:17.5-alpine  ",
    ],
)
def test_valid_equivalent_references_normalize_identically(value: str) -> None:
    assert NORMALIZE(value) == "postgres:17.5-alpine"


def test_equal_postgres_references_pass_the_guard() -> None:
    result = run_guard("postgres:17.5-alpine", "postgres:17.5-alpine\r")
    assert result.returncode == 0
    assert "PostgreSQLImageCheck=PASS" in result.stdout


@pytest.mark.parametrize("target", ["postgres:18-alpine", "postgres:17.6-alpine"])
def test_real_postgres_version_changes_are_blocked(target: str) -> None:
    result = run_guard("postgres:17.5-alpine", target)
    assert result.returncode == 40
    assert "PostgreSQL image change prohibited" in result.stdout
    assert "CurrentReference: postgres:17.5-alpine" in result.stdout
    assert f"TargetReference: {target}" in result.stdout


@pytest.mark.parametrize(
    ("current", "target"),
    [("", "postgres:17.5-alpine"), ("not an image", "postgres:17.5-alpine"), ("postgres:17.5-alpine", "")],
)
def test_unparseable_reference_fails_closed(current: str, target: str) -> None:
    result = run_guard(current, target)
    assert result.returncode == 10
    assert "Unable to verify PostgreSQL image identity" in result.stdout


def test_application_release_never_pulls_or_targets_postgres_for_reconcile() -> None:
    executor = EXECUTOR.read_text(encoding="utf-8")
    assert "docker pull" not in executor
    assert "pull postgres" not in executor
    assert "up -d --no-deps --pull never license-api" in executor
    assert "up -d --no-deps --pull never postgres" not in executor
    assert "restart postgres" not in executor
    assert "down -v" not in executor


def test_application_release_guards_postgres_container_and_image_id_after_api_update() -> None:
    executor = EXECUTOR.read_text(encoding="utf-8")
    api_update = executor.index("up -d --no-deps --pull never license-api")
    identity_check = executor.index("PostgreSQL container or Image ID changed unexpectedly")
    assert identity_check > api_update
    assert "postgres_container_after" in executor
    assert "postgres_image_id_after" in executor


def test_postgres_guard_runs_after_nginx_audit_and_before_backup_or_migration() -> None:
    executor = EXECUTOR.read_text(encoding="utf-8")
    nginx_audit = executor.index("audit_nginx_config 'ddrec-downloads-http.conf'")
    postgres_guard = executor.index("verify-postgres-image.py")
    migration = executor.index("audit-pending-migrations.py")
    backup = executor.index("backup-production.sh")
    assert nginx_audit < postgres_guard < migration < backup
