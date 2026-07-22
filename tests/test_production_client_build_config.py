from __future__ import annotations

from pathlib import Path

from app.core.version import APP_NAME, APP_VERSION
from app.licensing.constants import PRODUCTION_LICENSE_API_BASE_URL, PRODUCTION_LICENSE_KEY_ID
from scripts.check_client_release_security import scan


ROOT = Path(__file__).parents[1]


def test_application_version_and_product_names():
    assert APP_VERSION == "1.0.5"
    assert APP_NAME == "电商打包发货监控溯源系统"
    assert PRODUCTION_LICENSE_API_BASE_URL == "https://license.aixcc.top/api/v1"
    assert PRODUCTION_LICENSE_KEY_ID == "production-2026-01"


def test_pyinstaller_spec_is_onedir_and_bundles_required_runtime_files():
    spec = (ROOT / "PMSystem.spec").read_text(encoding="utf-8")
    assert "COLLECT(" in spec
    assert "ffmpeg.exe" in spec and "ffprobe.exe" in spec
    assert "app\\\\assets" in spec
    assert "uninstall_helper.py" not in spec
    assert "license-server" not in spec
    assert "license-admin" not in spec
    assert "deploy" not in spec


def test_inno_setup_uses_exact_release_name_and_uninstall_helper():
    iss = (ROOT / "installer" / "PMSystem.iss").read_text(encoding="utf-8")
    assert "OutputBaseFilename=PMSystem-Setup-{#MyAppVersion}-x64" in iss
    assert "OutputDir=..\\release\\client\\{#MyAppVersion}" in iss
    assert "--deactivate-before-uninstall" in iss
    assert 'DestName: "{#MyLicenseHelper}"' in iss
    assert "CurUninstallStep = usUninstall" in iss
    assert "DefaultDirName={autopf}\\PMSystem" in iss
    assert "VersionInfoVersion={#MyAppVersion}" in iss
    assert "VersionInfoProductName=PMSystem" in iss
    assert "license.dat" not in iss
    assert "LOCALAPPDATA" not in iss


def test_release_security_scanner_rejects_private_key(tmp_path: Path):
    bad = tmp_path / "production_ed25519_private.pem"
    bad.write_text("-----BEGIN PRIVATE KEY-----\nsecret", encoding="utf-8")
    errors = scan([tmp_path])
    assert any("forbidden file" in error for error in errors)
    assert any("secret marker" in error for error in errors)
