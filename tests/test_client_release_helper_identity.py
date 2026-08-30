from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
NGINX_TEMPLATE = ROOT / "deploy" / "production-nginx" / "nginx" / "ddrec-downloads-https.conf.template"
INSTALL_HELPER = ROOT / "deploy" / "production-release" / "install-client-package.sh"
TRANSITION = ROOT / "deploy" / "production-release" / "verify-client-download-nginx-transition.py"
NGINX_DEPLOY = ROOT / "deploy" / "production-release" / "deploy-client-download-nginx.sh"
BOOTSTRAP = ROOT / "scripts" / "release" / "bootstrap-server-tools.ps1"

CURRENT = (
    r"^/releases/stable/(standard|license)/[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:/[1-9][0-9]*)?/(?:DDREC|iVRec)-[0-9]+\.[0-9]+\.[0-9]+"
    r"-(standard|license)-Setup\.exe$"
)
LEGACY = (
    r"^/releases/stable/(standard|license)/[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:/[1-9][0-9]*)?/DDREC-[0-9]+\.[0-9]+\.[0-9]+"
    r"-(standard|license)-Setup\.exe$"
)


def run_transition(active: Path, expected: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TRANSITION), "--active", str(active), "--expected", str(expected)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_new_write_path_is_ivrec_only_and_historical_read_is_explicit() -> None:
    helper = INSTALL_HELPER.read_text(encoding="utf-8")
    nginx = NGINX_TEMPLATE.read_text(encoding="utf-8")
    assert "^iVRec-[0-9]+\\.[0-9]+\\.[0-9]+" in helper
    assert "^DDREC-" not in helper
    assert "(?:DDREC|iVRec)-" in nginx
    assert "HISTORICAL READ PATH" in nginx


def test_exact_historical_to_current_nginx_transition_is_approved(tmp_path: Path) -> None:
    expected = tmp_path / "expected.conf"
    active = tmp_path / "active.conf"
    current_text = NGINX_TEMPLATE.read_text(encoding="utf-8")
    expected.write_text(current_text, encoding="utf-8")
    active.write_text(current_text.replace(CURRENT, LEGACY), encoding="utf-8")
    result = run_transition(active, expected)
    assert result.returncode == 0
    assert "APPROVED_DDREC_HISTORY_PLUS_IVREC_CURRENT" in result.stdout


def test_already_current_nginx_rule_is_idempotent(tmp_path: Path) -> None:
    expected = tmp_path / "expected.conf"
    active = tmp_path / "active.conf"
    content = NGINX_TEMPLATE.read_text(encoding="utf-8")
    expected.write_text(content, encoding="utf-8")
    active.write_text(content, encoding="utf-8")
    result = run_transition(active, expected)
    assert result.returncode == 0
    assert "ALREADY_CURRENT" in result.stdout


def test_unrelated_nginx_change_is_rejected(tmp_path: Path) -> None:
    expected = tmp_path / "expected.conf"
    active = tmp_path / "active.conf"
    current_text = NGINX_TEMPLATE.read_text(encoding="utf-8")
    expected.write_text(current_text, encoding="utf-8")
    active.write_text(current_text.replace(CURRENT, LEGACY).replace("limit_rate 4m", "limit_rate 8m"), encoding="utf-8")
    assert run_transition(active, expected).returncode == 40


def test_nginx_helper_is_atomic_backed_up_and_fail_closed() -> None:
    script = NGINX_DEPLOY.read_text(encoding="utf-8")
    assert "client-download-nginx-${SESSION_ID}" in script
    assert 'mv -f -- "${candidate}" "${active}"' in script
    assert "nginx -t" in script
    assert "previous config restored" in script
    assert "nginx -s reload" in script
    assert "sed " not in script


def test_bootstrap_versions_all_release_helpers_and_expected_nginx_config() -> None:
    script = BOOTSTRAP.read_text(encoding="utf-8")
    assert "client-download-nginx.conf" in script
    assert "SHA256SUMS.txt" in script
    assert "release-tools-$($context.SessionId)" in script
