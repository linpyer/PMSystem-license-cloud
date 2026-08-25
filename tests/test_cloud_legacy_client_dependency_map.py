from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_client_dependency_map_covers_every_required_consumer() -> None:
    text = (ROOT / "docs" / "CLOUD_LEGACY_CLIENT_DEPENDENCY_MAP.md").read_text(encoding="utf-8")
    for consumer in (
        "Current DDREC-Release",
        "Current Cloud Build",
        "Current Admin Build",
        "Current license-server",
        "CI workflows",
        "Cloud root pytest",
        "README and root `main.py`",
        "`build.bat` and `build_installer.bat`",
        "`DDREC.spec` and `scripts/build_production_client.ps1`",
    ):
        assert consumer in text
    for classification in (
        "`runtime dependency`",
        "`build dependency`",
        "`test dependency`",
        "`documentation-only`",
        "`no dependency`",
    ):
        assert classification in text


def test_formal_release_and_cloud_build_do_not_select_historical_client_copy() -> None:
    release_module = (ROOT / "scripts" / "release" / "DDREC.Release.psm1").read_text(encoding="utf-8")
    cloud_builder = (ROOT / "scripts" / "build_cloud_release.ps1").read_text(encoding="utf-8")
    assert "Join-Path $WorkspaceRoot 'client'" in release_module
    assert "Join-Path $WorkspaceRoot 'cloud-license'" in release_module
    assert "Join-Path $projectRoot 'license-server'" in cloud_builder
    assert "Join-Path $projectRoot 'license-admin'" in cloud_builder
    assert "trackedScopes += 'app'" not in cloud_builder


def test_historical_manual_runtime_and_build_entrypoints_still_exist() -> None:
    for relative_path in (
        "main.py",
        "build.bat",
        "build_installer.bat",
        "DDREC.spec",
        "scripts/build_production_client.ps1",
    ):
        assert (ROOT / relative_path).is_file()
    assert "from app.ui.main_window import MainWindow" in (ROOT / "main.py").read_text(encoding="utf-8")
