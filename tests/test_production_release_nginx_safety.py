from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
AUDITOR = ROOT / "deploy" / "production-release" / "audit-nginx-config.py"
IMMUTABLE = ROOT / "deploy" / "production-release" / "verify-immutable-release.py"
EXECUTOR = ROOT / "deploy" / "production-release" / "deploy-release.sh"


BASE_CONFIG = """server {
    listen 443 ssl;
    server_name download.aixcc.top;
    ssl_certificate /cert/fullchain.pem;
    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        add_header X-Content-Type-Options nosniff always;
    }
}
"""


def audit(tmp_path: Path, expected: str, active: str) -> subprocess.CompletedProcess[str]:
    expected_path = tmp_path / "expected.conf"
    active_path = tmp_path / "active.conf"
    expected_path.write_text(expected, encoding="utf-8")
    active_path.write_text(active, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(AUDITOR),
            "--name",
            "fixture.conf",
            "--expected",
            str(expected_path),
            "--active",
            str(active_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_nginx_identical_is_unchanged(tmp_path: Path) -> None:
    result = audit(tmp_path, BASE_CONFIG, BASE_CONFIG)
    assert result.returncode == 0
    assert "semantic=unchanged" in result.stdout


def test_nginx_line_endings_are_not_a_change(tmp_path: Path) -> None:
    result = audit(tmp_path, BASE_CONFIG.replace("\n", "\r\n"), BASE_CONFIG)
    assert result.returncode == 0


def test_nginx_comments_and_formatting_are_not_a_change(tmp_path: Path) -> None:
    reformatted = "# generated\nserver{listen 443 ssl; server_name download.aixcc.top; ssl_certificate /cert/fullchain.pem; location /api/{proxy_pass http://127.0.0.1:8080; proxy_set_header Host $host; add_header X-Content-Type-Options nosniff always;}}"
    result = audit(tmp_path, reformatted, BASE_CONFIG)
    assert result.returncode == 0


def test_unrendered_template_is_rejected_instead_of_compared(tmp_path: Path) -> None:
    result = audit(tmp_path, BASE_CONFIG.replace("download.aixcc.top", "${DOMAIN}"), BASE_CONFIG)
    assert result.returncode == 10
    assert "must be rendered before comparison" in result.stderr


@pytest.mark.parametrize(
    "old,new",
    [
        ("listen 443 ssl", "listen 8443 ssl"),
        ("location /api/", "location /v2/"),
        ("proxy_pass http://127.0.0.1:8080", "proxy_pass http://127.0.0.1:9090"),
        ("proxy_set_header Host $host", "proxy_set_header Host example.invalid"),
        ("ssl_certificate /cert/fullchain.pem", "ssl_certificate /cert/new.pem"),
    ],
)
def test_true_nginx_semantic_changes_are_blocked(tmp_path: Path, old: str, new: str) -> None:
    result = audit(tmp_path, BASE_CONFIG.replace(old, new), BASE_CONFIG)
    assert result.returncode == 40
    assert "NGINX_CHANGE" in result.stdout


def write_release(root: Path, content: str = "payload") -> None:
    (root / "nested").mkdir(parents=True)
    (root / "RELEASE-VERSION.txt").write_text("1.3.0\n", encoding="ascii")
    (root / "nested" / "file.txt").write_text(content, encoding="utf-8")


def verify_immutable(installed: Path, staging: Path, archive_sha: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(IMMUTABLE),
            "--installed",
            str(installed),
            "--staging",
            str(staging),
            "--archive-sha",
            archive_sha,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_equal_legacy_immutable_release_can_be_reused(tmp_path: Path) -> None:
    installed, staging = tmp_path / "installed", tmp_path / "staging"
    write_release(installed)
    write_release(staging)
    result = verify_immutable(installed, staging, "a" * 64)
    assert result.returncode == 0
    assert "verified-content-legacy" in result.stdout


def test_equal_marked_immutable_release_can_be_reused(tmp_path: Path) -> None:
    installed, staging = tmp_path / "installed", tmp_path / "staging"
    write_release(installed)
    write_release(staging)
    (installed / ".DDREC-ARCHIVE-SHA256").write_text("a" * 64 + "\n", encoding="ascii")
    result = verify_immutable(installed, staging, "a" * 64)
    assert result.returncode == 0
    assert "archive-sha+content" in result.stdout


def test_immutable_release_with_different_archive_sha_is_blocked(tmp_path: Path) -> None:
    installed, staging = tmp_path / "installed", tmp_path / "staging"
    write_release(installed)
    write_release(staging)
    (installed / ".DDREC-ARCHIVE-SHA256").write_text("b" * 64 + "\n", encoding="ascii")
    assert verify_immutable(installed, staging, "a" * 64).returncode == 40


def test_immutable_release_with_different_content_is_blocked(tmp_path: Path) -> None:
    installed, staging = tmp_path / "installed", tmp_path / "staging"
    write_release(installed, "old")
    write_release(staging, "new")
    result = verify_immutable(installed, staging, "a" * 64)
    assert result.returncode == 40
    assert "content mismatch" in result.stderr


def test_application_executor_never_writes_or_reloads_nginx() -> None:
    executor = EXECUTOR.read_text(encoding="utf-8")
    assert "systemctl reload nginx" not in executor
    assert "nginx-before-change.conf" not in executor
    assert "--allow-nginx-change is disabled for application releases" in executor
    assert "configuration write and reload skipped" in executor


def test_nginx_audit_runs_before_any_backup_or_application_switch() -> None:
    executor = EXECUTOR.read_text(encoding="utf-8")
    audit_index = executor.index("audit_nginx_config 'ddrec-downloads-http.conf'")
    backup_index = executor.index('backup-production.sh')
    switch_index = executor.index("switch_started=true")
    assert audit_index < backup_index < switch_index


def test_license_bootstrap_template_is_not_compared_with_rendered_tls_config() -> None:
    executor = EXECUTOR.read_text(encoding="utf-8")
    assert "nginxConfig=ddrec-license.conf policy=bootstrap-template" in executor
    assert '"${final}/nginx/ddrec-license.conf" "${DDREC_LICENSE_NGINX_CONF}"' not in executor
