from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests import test_support as _test_support  # noqa: F401
from ui.services import update_service


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, payload: dict):
        self.payload = payload

    def get(self, *_args, **_kwargs):
        return _FakeResponse(self.payload)


class UpdateServiceTests(unittest.TestCase):
    def test_check_for_updates_detects_newer_release_and_selects_windows_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe_path = Path(tmp) / "pylrcget.exe"
            exe_path.write_bytes(b"exe")
            payload = {
                "tag_name": "v0.8.0",
                "name": "v0.8.0",
                "html_url": "https://github.com/saitatter/pylrcget/releases/tag/v0.8.0",
                "body": "## Changes\n- Something new",
                "published_at": "2026-04-12T10:00:00Z",
                "assets": [
                    {
                        "name": "pylrcget-windows.zip",
                        "browser_download_url": "https://example.com/pylrcget-windows.zip",
                        "size": 1024,
                        "content_type": "application/zip",
                    }
                ],
            }

            with patch.object(update_service, "current_app_version", return_value="0.7.0"), patch.object(
                update_service.sys, "platform", "win32"
            ), patch.object(update_service.sys, "frozen", True, create=True), patch.object(
                update_service, "current_executable_path", return_value=exe_path
            ):
                info = update_service.check_for_updates(session=_FakeSession(payload))

        self.assertTrue(info.is_update_available)
        self.assertIsNotNone(info.asset)
        assert info.asset is not None
        self.assertEqual(info.asset.name, "pylrcget-windows.zip")
        self.assertTrue(info.install_supported)

    def test_check_for_updates_reports_up_to_date_when_versions_match(self):
        payload = {
            "tag_name": "v0.7.0",
            "name": "v0.7.0",
            "html_url": "https://github.com/saitatter/pylrcget/releases/tag/v0.7.0",
            "body": "",
            "published_at": "2026-04-12T10:00:00Z",
            "assets": [],
        }

        with patch.object(update_service, "current_app_version", return_value="0.7.0"):
            info = update_service.check_for_updates(session=_FakeSession(payload))

        self.assertFalse(info.is_update_available)
        self.assertIsNone(info.asset)

    def test_stage_self_update_creates_windows_updater_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "pylrcget-windows.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("pylrcget.exe", b"new-binary")

            current_exe = tmp_path / "current.exe"
            current_exe.write_bytes(b"old-binary")

            with patch.object(update_service.sys, "platform", "win32"), patch.object(
                update_service, "current_executable_path", return_value=current_exe
            ):
                script_path = update_service.stage_self_update(archive, pid=1234)

            self.assertTrue(script_path.exists())
            script_text = script_path.read_text(encoding="utf-8")
            self.assertIn("1234", script_text)
            self.assertIn("current.exe", script_text)
            extracted_exe = script_path.parent / "pylrcget.exe"
            self.assertTrue(extracted_exe.exists())


if __name__ == "__main__":
    unittest.main()
