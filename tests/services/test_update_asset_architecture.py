"""Prefer architecture-qualified downloads without selecting another CPU target."""
import pytest

from tests import test_support as _test_support  # noqa: F401
from ui.services import update_service


@pytest.mark.parametrize(("system", "machine", "name"), [
    ("win32", "AMD64", "pylrcget-windows-x64-installer.exe"),
    ("darwin", "arm64", "pylrcget-macos-arm64.pkg"),
    ("darwin", "x86_64", "pylrcget-macos-x64.pkg"),
    ("linux", "x86_64", "pylrcget-linux-x64.deb"),
    ("linux", "aarch64", "pylrcget-linux-arm64.deb"),
])
def test_selects_native_download_before_legacy_alias(monkeypatch, system, machine, name):
    monkeypatch.setattr(update_service.sys, "platform", system)
    monkeypatch.setattr(update_service.platform, "machine", lambda: machine)
    legacy = update_service._legacy_platform_asset_names()[0]
    assets = [{"name": item, "browser_download_url": "https://example.com/" + item} for item in [legacy, name]]
    selected = update_service.select_platform_asset(assets)
    assert selected is not None and selected.name == name


def test_does_not_select_other_architecture_or_ambiguous_legacy_alias(monkeypatch):
    monkeypatch.setattr(update_service.sys, "platform", "darwin")
    monkeypatch.setattr(update_service.platform, "machine", lambda: "x86_64")
    assert update_service.select_platform_asset([
        {"name": "pylrcget-macos-arm64.pkg"}, {"name": "pylrcget-macos.pkg"},
    ]) is None


def test_unknown_architecture_does_not_select_modern_assets(monkeypatch):
    monkeypatch.setattr(update_service.sys, "platform", "linux")
    monkeypatch.setattr(update_service.platform, "machine", lambda: "unrecognized")
    assert update_service.select_platform_asset([{"name": "pylrcget-linux-x64.deb"}]) is None


def test_native_installer_is_preferred_over_native_archive(monkeypatch):
    monkeypatch.setattr(update_service.sys, "platform", "win32")
    monkeypatch.setattr(update_service.platform, "machine", lambda: "AMD64")
    selected = update_service.select_platform_asset([
        {"name": "pylrcget-windows-x64.zip"}, {"name": "pylrcget-windows-x64-installer.exe"},
    ])
    assert selected is not None and selected.name == "pylrcget-windows-x64-installer.exe"
    assert update_service.is_windows_installer_asset(selected)
