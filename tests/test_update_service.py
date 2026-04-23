from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock
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
        self.calls: list[dict] = []

    def get(self, *args, **kwargs):
        call = dict(kwargs)
        call["url"] = args[0] if args else ""
        self.calls.append(call)
        return _FakeResponse(self.payload)


class UpdateServiceTests(unittest.TestCase):
    def test_current_app_version_reads_bundled_pyproject_for_frozen_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle_root = Path(tmp)
            (bundle_root / "pyproject.toml").write_text(
                "[project]\nname = 'pylrcget'\nversion = '9.8.7'\n",
                encoding="utf-8",
            )
            with patch.object(
                update_service.importlib.metadata,
                "version",
                side_effect=update_service.importlib.metadata.PackageNotFoundError,
            ), patch.object(update_service.sys, "_MEIPASS", str(bundle_root), create=True):
                version = update_service.current_app_version()

        self.assertEqual(version, "9.8.7")

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
                        "name": "pylrcget-windows-installer.exe",
                        "browser_download_url": "https://example.com/pylrcget-windows-installer.exe",
                        "size": 1024,
                        "content_type": "application/octet-stream",
                    },
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
        self.assertEqual(info.asset.name, "pylrcget-windows-installer.exe")
        self.assertTrue(info.install_supported)

    def test_check_for_updates_zip_only_is_download_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe_path = Path(tmp) / "pylrcget.exe"
            exe_path.write_bytes(b"exe")
            payload = {
                "tag_name": "v0.8.0",
                "name": "v0.8.0",
                "html_url": "https://github.com/saitatter/pylrcget/releases/tag/v0.8.0",
                "body": "",
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
        self.assertFalse(info.install_supported)

    def test_check_for_updates_reports_up_to_date_when_versions_match(self):
        payload = {
            "tag_name": "v0.7.0",
            "name": "v0.7.0",
            "html_url": "https://github.com/saitatter/pylrcget/releases/tag/v0.7.0",
            "body": "",
            "published_at": "2026-04-12T10:00:00Z",
            "assets": [],
        }

        session = _FakeSession(payload)
        with patch.object(update_service, "current_app_version", return_value="0.7.0"):
            info = update_service.check_for_updates(session=session)

        self.assertFalse(info.is_update_available)
        self.assertIsNone(info.asset)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(
            session.calls[0]["headers"]["User-Agent"],
            update_service.GITHUB_API_USER_AGENT,
        )

    def test_check_for_updates_uses_env_override_for_latest_url(self):
        payload = {
            "tag_name": "v0.7.0",
            "name": "v0.7.0",
            "html_url": "https://example.local/releases/v0.7.0",
            "body": "",
            "published_at": "2026-04-12T10:00:00Z",
            "assets": [],
        }
        session = _FakeSession(payload)
        local_url = "http://127.0.0.1:8765/latest.json"
        with patch.object(update_service, "current_app_version", return_value="0.7.0"), patch.dict(
            update_service.os.environ,
            {update_service.UPDATE_LATEST_URL_ENV: local_url},
            clear=False,
        ):
            update_service.check_for_updates(session=session)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]["url"], local_url)
        self.assertEqual(session.calls[0]["headers"]["User-Agent"], update_service.GITHUB_API_USER_AGENT)

    def test_default_update_download_dir_falls_back_when_preferred_not_writable(self):
        with patch.object(update_service.tempfile, "gettempdir", return_value="C:/Temp"), patch.object(
            update_service, "_can_write_directory", side_effect=[False, True]
        ) as can_write:
            selected = update_service.default_update_download_dir("C:/Users/test/AppData/Roaming/PyLrcGet")

        self.assertEqual(selected, Path("C:/Temp") / update_service.APP_PATH_NAME / "updates")
        self.assertEqual(can_write.call_count, 2)

    def test_choose_update_download_path_uses_unique_name_when_target_not_replaceable(self):
        with tempfile.TemporaryDirectory() as tmp:
            download_dir = Path(tmp)
            blocked_target = download_dir / "pylrcget-windows-installer.exe"
            blocked_target.mkdir()

            selected = update_service.choose_update_download_path(download_dir, "pylrcget-windows-installer.exe")

        self.assertEqual(selected.parent, download_dir)
        self.assertNotEqual(selected.name, "pylrcget-windows-installer.exe")
        self.assertEqual(selected.suffix, ".exe")

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
            ), patch.object(
                update_service, "_is_probably_valid_pyinstaller_binary", return_value=True
            ):
                script_path = update_service.stage_self_update(archive, pid=1234)

            self.assertTrue(script_path.exists())
            self.assertEqual(script_path.parent, current_exe.parent)
            script_text = script_path.read_text(encoding="utf-8")
            self.assertIn("1234", script_text)
            self.assertIn("current.exe", script_text)
            self.assertIn("$target = '", script_text)
            self.assertIn("$newExe = '", script_text)
            self.assertIn("pylrcget-update.log", script_text)
            self.assertIn("Get-FileHash", script_text)
            self.assertIn("previous.exe", script_text)
            self.assertIn("-WorkingDirectory $targetDir", script_text)
            extracted_exe = script_path.parent / "pylrcget.exe"
            if not extracted_exe.exists():
                extracted_exe = next(tmp_path.glob("**/pylrcget.exe"))
            self.assertTrue(extracted_exe.exists())
            self.assertEqual(extracted_exe.parent.parent, archive.parent)

    def test_launch_staged_update_uses_detached_windows_process(self):
        fake_popen = MagicMock()
        script_path = Path("C:/Temp/apply-update.ps1")
        with patch.object(update_service.sys, "platform", "win32"), patch.object(
            update_service.subprocess,
            "Popen",
            fake_popen,
        ), patch.object(update_service.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200), patch.object(
            update_service.subprocess,
            "DETACHED_PROCESS",
            0x8,
        ), patch.object(update_service.subprocess, "CREATE_NO_WINDOW", 0x08000000):
            update_service.launch_staged_update(script_path)

        _, kwargs = fake_popen.call_args
        self.assertEqual(kwargs["cwd"], str(script_path.parent))
        self.assertTrue(kwargs["creationflags"] & 0x200)
        self.assertTrue(kwargs["creationflags"] & 0x8)

    def test_launch_windows_installer_uses_visible_progress_flags(self):
        fake_startfile = MagicMock()
        installer_path = Path("C:/Temp/pylrcget-windows-installer.exe")
        with patch.object(update_service.sys, "platform", "win32"), patch.object(
            update_service.os,
            "startfile",
            fake_startfile,
            create=True,
        ), patch.object(
            update_service.Path,
            "exists",
            return_value=True,
        ):
            update_service.launch_windows_installer(installer_path)

        args, kwargs = fake_startfile.call_args
        self.assertEqual(args[0], str(installer_path))
        self.assertEqual(kwargs["operation"], "runas")
        self.assertIn("/CLOSEAPPLICATIONS", kwargs["arguments"])
        self.assertIn("/FORCECLOSEAPPLICATIONS", kwargs["arguments"])
        self.assertIn("/RESTARTAPPLICATIONS", kwargs["arguments"])
        self.assertNotIn("/VERYSILENT", kwargs["arguments"])

    def test_check_for_updates_macos_pkg_enables_install(self):
        payload = {
            "tag_name": "v1.0.0",
            "name": "v1.0.0",
            "html_url": "https://example.com",
            "body": "",
            "published_at": "2026-04-12T10:00:00Z",
            "assets": [
                {
                    "name": "pylrcget-macos.pkg",
                    "browser_download_url": "https://example.com/pylrcget-macos.pkg",
                    "size": 1234,
                    "content_type": "application/octet-stream",
                }
            ],
        }
        with patch.object(update_service, "current_app_version", return_value="0.9.0"), patch.object(
            update_service.sys, "platform", "darwin"
        ), patch.object(update_service.sys, "frozen", True, create=True):
            info = update_service.check_for_updates(session=_FakeSession(payload))
        self.assertTrue(info.install_supported)

    def test_check_for_updates_linux_appimage_enables_install(self):
        payload = {
            "tag_name": "v1.0.0",
            "name": "v1.0.0",
            "html_url": "https://example.com",
            "body": "",
            "published_at": "2026-04-12T10:00:00Z",
            "assets": [
                {
                    "name": "pylrcget-linux.AppImage",
                    "browser_download_url": "https://example.com/pylrcget-linux.AppImage",
                    "size": 1234,
                    "content_type": "application/octet-stream",
                }
            ],
        }
        with patch.object(update_service, "current_app_version", return_value="0.9.0"), patch.object(
            update_service.sys, "platform", "linux"
        ), patch.object(update_service.sys, "frozen", True, create=True):
            info = update_service.check_for_updates(session=_FakeSession(payload))
        self.assertTrue(info.install_supported)

    def test_launch_platform_installer_macos_uses_open(self):
        fake_popen = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            installer_path = Path(tmp) / "pylrcget-macos.pkg"
            installer_path.write_bytes(b"pkg")
            with patch.object(update_service.sys, "platform", "darwin"), patch.object(
                update_service.subprocess, "Popen", fake_popen
            ):
                update_service.launch_platform_installer(installer_path)
        args, _ = fake_popen.call_args
        self.assertEqual(args[0][0], "open")

    def test_launch_platform_installer_linux_deb_uses_xdg_open(self):
        fake_popen = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            installer_path = Path(tmp) / "pylrcget-linux.deb"
            installer_path.write_bytes(b"deb")
            with patch.object(update_service.sys, "platform", "linux"), patch.object(
                update_service.subprocess, "Popen", fake_popen
            ):
                update_service.launch_platform_installer(installer_path)
        args, _ = fake_popen.call_args
        self.assertEqual(args[0][0], "xdg-open")

    def test_launch_staged_update_debug_uses_visible_console(self):
        fake_popen = MagicMock()
        script_path = Path("C:/Temp/apply-update.ps1")
        with patch.object(update_service.sys, "platform", "win32"), patch.object(
            update_service.subprocess,
            "Popen",
            fake_popen,
        ), patch.object(update_service.subprocess, "CREATE_NEW_CONSOLE", 0x10), patch.dict(
            update_service.os.environ,
            {update_service.UPDATE_DEBUG_ENV: "1"},
            clear=False,
        ):
            update_service.launch_staged_update(script_path)

        args, kwargs = fake_popen.call_args
        self.assertEqual(kwargs["cwd"], str(script_path.parent))
        self.assertTrue(kwargs["creationflags"] & 0x10)
        self.assertIn("-NoExit", args[0])
        self.assertNotIn("-WindowStyle", args[0])

    def test_stage_self_update_debug_keeps_cleanup_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "pylrcget-windows.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("pylrcget.exe", b"new-binary")

            current_exe = tmp_path / "current.exe"
            current_exe.write_bytes(b"old-binary")

            with patch.object(update_service.sys, "platform", "win32"), patch.object(
                update_service, "current_executable_path", return_value=current_exe
            ), patch.object(
                update_service, "_is_probably_valid_pyinstaller_binary", return_value=True
            ), patch.dict(
                update_service.os.environ,
                {update_service.UPDATE_DEBUG_ENV: "1"},
                clear=False,
            ):
                script_path = update_service.stage_self_update(archive, pid=1234)

            script_text = script_path.read_text(encoding="utf-8")
            self.assertNotIn("Remove-Item -LiteralPath $newExe", script_text)
            self.assertNotIn("Remove-Item -LiteralPath $PSCommandPath", script_text)


if __name__ == "__main__":
    unittest.main()
