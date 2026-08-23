from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_cloud_product_versions_are_1_3_0() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.3.0"
    package = json.loads((ROOT / "license-admin" / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (ROOT / "license-admin" / "package-lock.json").read_text(encoding="utf-8")
    )
    assert package["version"] == "1.3.0"
    assert package_lock["version"] == "1.3.0"
    assert package_lock["packages"][""]["version"] == "1.3.0"
    pyproject = (ROOT / "license-server" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.3.0"' in pyproject


def test_production_branch_and_image_tag_are_consistent() -> None:
    config = (ROOT / "scripts" / "cloud_release_config.psd1").read_text(encoding="utf-8")
    build = (ROOT / "scripts" / "build_cloud_release.ps1").read_text(encoding="utf-8")
    loader = (
        ROOT / "deploy" / "production-nginx" / "scripts" / "load-images.sh"
    ).read_text(encoding="utf-8")
    env_template = (
        ROOT / "deploy" / "production-nginx" / "env.production.example"
    ).read_text(encoding="utf-8")
    assert "ProductionBranch = 'v1.3'" in config
    assert '"ddrec-license-api:$script:releaseVersion-$Environment"' in build
    assert '"ddrec-license-api:${version}-production"' in loader
    assert '"ddrec-license-api:${version}"' not in loader
    assert "DDREC_API_IMAGE_TAG=1.3.0-production" in env_template
    assert "LICENSE_SERVICE_VERSION=1.3.0" in env_template


def test_admin_build_receives_the_canonical_version() -> None:
    build = (ROOT / "scripts" / "build_cloud_release.ps1").read_text(encoding="utf-8")
    layout = (
        ROOT / "license-admin" / "src" / "layouts" / "AdminLayout.vue"
    ).read_text(encoding="utf-8")
    assert "$env:VITE_APP_VERSION = $script:releaseVersion" in build
    assert 'data-testid="app-version">V{{ appVersion }}' in layout


def test_cloud_builder_exposes_production_only() -> None:
    build = (ROOT / "scripts" / "build_cloud_release.ps1").read_text(encoding="utf-8-sig")
    menu = (ROOT / "scripts" / "build_cloud_menu.ps1").read_text(encoding="utf-8-sig")
    config = (ROOT / "scripts" / "cloud_release_config.psd1").read_text(encoding="utf-8-sig")
    assert "[ValidateSet('production')]" in build
    assert "License-Production" in menu
    assert "本地环境" not in menu
    assert "local = @{" not in config
    assert not (ROOT / "license-server" / "docker-compose.yml").exists()
    assert not (ROOT / "deploy" / "staging" / "compose.yml").exists()
