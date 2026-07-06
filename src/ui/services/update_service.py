from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.metadata
import logging
import os
from pathlib import Path
from contextlib import nullcontext
import json
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import uuid
import zipfile

import requests
from packaging.version import InvalidVersion, Version


logger = logging.getLogger(__name__)

GITHUB_REPOSITORY = "saitatter/pylrcget"
GITHUB_RELEASES_LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
GITHUB_API_USER_AGENT = "pylrcget-updater/1.0"
UPDATE_LATEST_URL_ENV = "PYLRCGET_UPDATE_LATEST_URL"
UPDATE_DEBUG_ENV = "PYLRCGET_UPDATE_DEBUG"
APP_PATH_NAME = "PyLrcGet"


@dataclass(frozen=True)
class ReleaseAssetInfo:
    name: str
    download_url: str
    size: int
    content_type: str


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    tag_name: str
    release_name: str
    html_url: str
    body: str
    published_at: str
    is_update_available: bool
    asset: ReleaseAssetInfo | None
    install_supported: bool
    platform_label: str


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _bundled_resource_root() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    try:
        return Path(base).resolve()
    except (OSError, ValueError):
        return None


def _version_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    bundled_root = _bundled_resource_root()
    if bundled_root is not None:
        candidates.append(bundled_root / "pyproject.toml")

    try:
        candidates.append(project_root() / "pyproject.toml")
    except (OSError, ValueError):
        pass

    try:
        candidates.append(Path(sys.executable).resolve().parent / "pyproject.toml")
    except (OSError, ValueError):
        pass

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        rendered = os.path.normcase(str(candidate))
        if rendered in seen:
            continue
        seen.add(rendered)
        unique.append(candidate)
    return unique


def current_app_version() -> str:
    try:
        return importlib.metadata.version("pylrcget")
    except importlib.metadata.PackageNotFoundError:
        pass
    for candidate in _version_file_candidates():
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
            version = str(data.get("project", {}).get("version", "")).strip()
            if version:
                return version
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue
    return "0.0.0"


def current_executable_path() -> Path | None:
    try:
        return Path(sys.executable).resolve()
    except (OSError, ValueError):
        return None


def _can_write_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".pylrcget-write-test.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def is_frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def platform_label() -> str:
    if sys.platform.startswith("win"):
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    if sys.platform.startswith("linux"):
        return "Linux"
    return sys.platform


def normalize_version_tag(tag_name: str) -> str:
    text = (tag_name or "").strip()
    if text.lower().startswith("v"):
        text = text[1:]
    return text


def platform_asset_names() -> list[str]:
    if sys.platform.startswith("win"):
        return [
            "pylrcget-windows-installer.exe",
            "pylrcget-windows.zip",
        ]
    if sys.platform == "darwin":
        return [
            "pylrcget-macos.pkg",
            "pylrcget-macos.dmg",
            "pylrcget-macos.tar.gz",
        ]
    if sys.platform.startswith("linux"):
        return [
            "pylrcget-linux.AppImage",
            "pylrcget-linux.deb",
            "pylrcget-linux.rpm",
            "pylrcget-linux.tar.gz",
        ]
    return []


def select_platform_asset(assets_payload: list[dict]) -> ReleaseAssetInfo | None:
    expected_names = platform_asset_names()
    if not expected_names:
        return None

    for expected_name in expected_names:
        for asset in assets_payload:
            if str(asset.get("name") or "") != expected_name:
                continue
            return ReleaseAssetInfo(
                name=str(asset.get("name") or ""),
                download_url=str(asset.get("browser_download_url") or ""),
                size=int(asset.get("size") or 0),
                content_type=str(asset.get("content_type") or ""),
            )
    return None


def is_windows_installer_asset(asset: ReleaseAssetInfo | None) -> bool:
    if asset is None:
        return False
    return str(asset.name).lower().endswith("-installer.exe")


def is_macos_installer_asset(asset: ReleaseAssetInfo | None) -> bool:
    if asset is None:
        return False
    name = str(asset.name).lower()
    return name.endswith(".pkg")


def is_linux_installer_asset(asset: ReleaseAssetInfo | None) -> bool:
    if asset is None:
        return False
    name = str(asset.name).lower()
    return name.endswith(".appimage") or name.endswith(".deb") or name.endswith(".rpm")


def can_auto_install_update(asset: ReleaseAssetInfo | None) -> bool:
    if asset is None:
        return False
    if not is_frozen_build() and not is_update_debug_enabled():
        return False
    if sys.platform.startswith("win"):
        return is_windows_installer_asset(asset)
    if sys.platform == "darwin":
        return is_macos_installer_asset(asset)
    if sys.platform.startswith("linux"):
        return is_linux_installer_asset(asset)
    return False


def _powershell_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def is_update_debug_enabled() -> bool:
    raw = str(os.environ.get(UPDATE_DEBUG_ENV, "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def check_for_updates(*, timeout_s: float = 10.0, session: requests.Session | None = None) -> UpdateInfo:
    latest_url = str(os.environ.get(UPDATE_LATEST_URL_ENV) or "").strip() or GITHUB_RELEASES_LATEST_URL
    manager = nullcontext(session) if session is not None else requests.Session()
    with manager as http:
        response = http.get(
            latest_url,
            timeout=timeout_s,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": GITHUB_API_USER_AGENT,
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            payload = json.loads(response.content.decode("utf-8-sig"))

    tag_name = str(payload.get("tag_name") or "")
    latest_version = normalize_version_tag(tag_name)
    current_version = current_app_version()
    asset = select_platform_asset(list(payload.get("assets") or []))

    try:
        is_update_available = Version(latest_version) > Version(current_version)
    except InvalidVersion:
        is_update_available = latest_version != current_version

    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        tag_name=tag_name,
        release_name=str(payload.get("name") or tag_name or "Latest release"),
        html_url=str(payload.get("html_url") or ""),
        body=str(payload.get("body") or "").strip(),
        published_at=str(payload.get("published_at") or ""),
        is_update_available=is_update_available,
        asset=asset,
        install_supported=can_auto_install_update(asset) and is_update_available,
        platform_label=platform_label(),
    )


def launch_windows_installer(installer_path: Path) -> None:
    if not sys.platform.startswith("win"):
        raise RuntimeError("Installer launch is only supported on Windows.")
    if not installer_path.exists():
        raise FileNotFoundError(f"Installer not found: {installer_path}")
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        raise RuntimeError("os.startfile is unavailable on this Python runtime.")
    try:
        # Current Windows releases use Inno Setup installers.
        # Keep installer UI visible so users can see progress, and explicitly request
        # application restart after install when supported by the installer script.
        # If packaging switches to MSI/NSIS, this should branch by installer type.
        startfile(
            str(installer_path),
            operation="runas",
            arguments="/CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /RESTARTAPPLICATIONS",
        )
    except OSError as exc:
        # 1223: "The operation was canceled by the user" (typically UAC prompt canceled).
        if getattr(exc, "winerror", None) == 1223:
            raise RuntimeError("Installer launch was canceled in the UAC confirmation dialog.") from exc
        raise RuntimeError(f"Failed to launch installer: {exc}") from exc
    except (TypeError, AttributeError) as exc:
        raise RuntimeError(f"Failed to launch installer: {exc}") from exc


def launch_platform_installer(installer_path: Path) -> None:
    if not installer_path.exists():
        raise FileNotFoundError(f"Installer not found: {installer_path}")

    lower_name = installer_path.name.lower()
    if sys.platform.startswith("win"):
        if not is_windows_installer_asset(ReleaseAssetInfo(lower_name, "", 0, "")):
            raise RuntimeError("Windows auto-install requires a Windows installer executable asset.")
        launch_windows_installer(installer_path)
        return

    if sys.platform == "darwin":
        if not lower_name.endswith(".pkg"):
            raise RuntimeError("macOS auto-install supports only .pkg assets.")
        subprocess.Popen(
            ["open", str(installer_path)],
            start_new_session=True,
            close_fds=True,
        )
        return

    if sys.platform.startswith("linux"):
        if lower_name.endswith(".appimage"):
            os.chmod(installer_path, 0o755)
            subprocess.Popen(
                [str(installer_path)],
                cwd=str(installer_path.parent),
                start_new_session=True,
                close_fds=True,
            )
            return
        if lower_name.endswith(".deb") or lower_name.endswith(".rpm"):
            subprocess.Popen(
                ["xdg-open", str(installer_path)],
                start_new_session=True,
                close_fds=True,
            )
            return
        raise RuntimeError("Linux auto-install supports only AppImage, .deb, and .rpm assets.")

    raise RuntimeError("Auto-install is not supported on this platform.")


def download_release_asset(
    asset: ReleaseAssetInfo,
    destination: Path,
    *,
    timeout_s: float = 30.0,
    session: requests.Session | None = None,
    progress_callback=None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    manager = nullcontext(session) if session is not None else requests.Session()
    with manager as http:
        with http.get(asset.download_url, stream=True, timeout=timeout_s) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or asset.size or 0)
            downloaded = 0
            hasher = hashlib.sha256()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total)
    digest = hasher.hexdigest()
    logger.info("Download complete: %s (SHA-256: %s, %d bytes)", destination.name, digest, downloaded)
    if total > 0 and downloaded != total:
        raise IOError(f"Incomplete download: expected {total} bytes, got {downloaded} bytes.")
    if asset.size > 0 and destination.stat().st_size != asset.size:
        raise IOError(
            f"Downloaded asset size mismatch: expected {asset.size} bytes, got {destination.stat().st_size} bytes."
        )
    return destination


def _extract_updated_binary(archive_path: Path) -> Path:
    staging_dir = Path(tempfile.mkdtemp(prefix="pylrcget-update-", dir=str(archive_path.parent)))
    if archive_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            members = [name for name in zf.namelist() if name.lower().endswith("pylrcget.exe")]
            if not members:
                members = [name for name in zf.namelist() if name.lower().endswith(".exe")]
            if not members:
                raise FileNotFoundError("No executable found inside the update archive.")
            member = members[0]
            zf.extract(member, staging_dir)
            return staging_dir / member

    if archive_path.name.lower().endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tf:
            members = [m for m in tf.getmembers() if m.name.endswith("/pylrcget") or m.name == "pylrcget"]
            if not members:
                members = [m for m in tf.getmembers() if os.path.basename(m.name) == "pylrcget"]
            if not members:
                raise FileNotFoundError("No application binary found inside the update archive.")
            member = members[0]
            tf.extract(member, staging_dir)
            return staging_dir / member.name

    raise ValueError(f"Unsupported update archive format: {archive_path.name}")


def _is_probably_valid_pyinstaller_binary(path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size < 1024 * 1024:
            return False
        with path.open("rb") as handle:
            head = handle.read(2)
            if head != b"MZ" and sys.platform.startswith("win"):
                return False
            if sys.platform.startswith("linux") and head != b"\x7fE":
                return False

            # PyInstaller onefile archives include this marker in their trailer.
            handle.seek(max(0, path.stat().st_size - 8192))
            tail = handle.read()
            return b"MEI\x0c\x0b\x0a\x0b\x0e" in tail
    except OSError:
        return False


def _write_windows_updater_script(target_exe: Path, new_exe: Path, pid: int, *, debug: bool = False) -> Path:
    script_path = target_exe.parent / "apply-update.ps1"
    cleanup_block = ""
    if not debug:
        cleanup_block = """
    Remove-Item -LiteralPath $newExe -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
""".rstrip()
    script = f"""
$ErrorActionPreference = 'Stop'
$debugMode = {'$true' if debug else '$false'}
$pidToWait = {int(pid)}
$target = {_powershell_single_quoted(str(target_exe))}
$newExe = {_powershell_single_quoted(str(new_exe))}
$targetDir = Split-Path -Path $target -Parent
$backup = Join-Path $targetDir (([System.IO.Path]::GetFileNameWithoutExtension($target)) + '.previous.exe')
$baseAppData = if ($env:LOCALAPPDATA) {{ $env:LOCALAPPDATA }} elseif ($env:APPDATA) {{ $env:APPDATA }} else {{ $env:TEMP }}
$logDir = Join-Path $baseAppData {_powershell_single_quoted(APP_PATH_NAME)}
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logPath = Join-Path $logDir 'pylrcget-update.log'
$runtimeTempDir = Join-Path $logDir ('runtime-temp-' + [guid]::NewGuid().ToString('N'))
Get-ChildItem -Path $logDir -Directory -Filter 'runtime-temp-*' -ErrorAction SilentlyContinue | ForEach-Object {{
    if ($_.FullName -ne $runtimeTempDir) {{
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }}
}}
New-Item -ItemType Directory -Path $runtimeTempDir -Force | Out-Null

function Write-UpdateLog([string]$message) {{
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $logPath -Value "[$timestamp] $message"
}}

while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{
    Start-Sleep -Milliseconds 400
}}
Start-Sleep -Milliseconds 300

try {{
    Write-UpdateLog "Applying staged update from $newExe to $target"

    if (!(Test-Path -LiteralPath $newExe)) {{
        throw "Staged executable was not found."
    }}
    $newSize = (Get-Item -LiteralPath $newExe).Length
    Write-UpdateLog "Staged executable size: $newSize bytes"

    if (Test-Path -LiteralPath $backup) {{
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }}

    if (Test-Path -LiteralPath $target) {{
        Move-Item -LiteralPath $target -Destination $backup -Force
        Write-UpdateLog "Backed up current executable to $backup"
    }}

    Copy-Item -LiteralPath $newExe -Destination $target -Force

    $sourceHash = (Get-FileHash -LiteralPath $newExe -Algorithm SHA256).Hash
    $targetHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    $targetSize = (Get-Item -LiteralPath $target).Length
    Write-UpdateLog "Target executable size after copy: $targetSize bytes"
    Write-UpdateLog "Source hash: $sourceHash"
    Write-UpdateLog "Target hash: $targetHash"
    if ($sourceHash -ne $targetHash) {{
        throw "Copied executable hash does not match the staged update."
    }}

    Write-UpdateLog "Update copied successfully. Launching new executable."
    Write-UpdateLog "Using runtime temp dir: $runtimeTempDir"
    $env:TEMP = $runtimeTempDir
    $env:TMP = $runtimeTempDir
    Start-Sleep -Milliseconds 800
    Start-Process -FilePath $target -WorkingDirectory $targetDir
}}
catch {{
    Write-UpdateLog "Update failed: $($_.Exception.Message)"
    Write-Error $_
    try {{
        if (Test-Path -LiteralPath $backup) {{
            if (Test-Path -LiteralPath $target) {{
                Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
            }}
            Move-Item -LiteralPath $backup -Destination $target -Force
            Write-UpdateLog "Restored previous executable."
        }}
    }}
    catch {{
        Write-UpdateLog "Rollback failed: $($_.Exception.Message)"
    }}
    throw
}}
finally {{
{cleanup_block}
    if ($debugMode) {{
        Write-Host "Update script finished. Check log at: $logPath"
        Read-Host "Press Enter to close updater window"
    }}
}}
""".strip()
    script_path.write_text(script, encoding="utf-8")
    return script_path


def _write_unix_updater_script(target_exe: Path, new_exe: Path, pid: int, *, debug: bool = False) -> Path:
    script_path = target_exe.parent / "apply-update.sh"
    cleanup_lines = ""
    if not debug:
        cleanup_lines = """
rm -f "$NEW_EXE"
rm -f "$0"
""".strip()
    script = f"""#!/bin/sh
set -e
PID_TO_WAIT="{int(pid)}"
TARGET={shlex_quote(str(target_exe))}
NEW_EXE={shlex_quote(str(new_exe))}
TARGET_DIR=$(dirname "$TARGET")
LOG_DIR="${{XDG_STATE_HOME:-$HOME/.local/state}}/{APP_PATH_NAME}"
LOG_PATH="$LOG_DIR/pylrcget-update.log"
BACKUP_PATH="$TARGET.bak"

mkdir -p "$LOG_DIR"

log() {{
  printf '[%s] %s\\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG_PATH"
}}

while kill -0 "$PID_TO_WAIT" 2>/dev/null; do
  sleep 1
done
log "Applying staged update from $NEW_EXE to $TARGET"
if [ -f "$TARGET" ]; then
  cp "$TARGET" "$BACKUP_PATH"
  log "Backed up current executable to $BACKUP_PATH"
fi
if ! cp "$NEW_EXE" "$TARGET"; then
  log "Update copy failed. Attempting rollback from backup."
  if [ -f "$BACKUP_PATH" ]; then
    cp "$BACKUP_PATH" "$TARGET"
    chmod +x "$TARGET"
    log "Rollback completed."
  fi
  exit 1
fi
chmod +x "$TARGET"
log "Update copied successfully. Launching new executable."
(
  cd "$TARGET_DIR"
  "$TARGET" >/dev/null 2>&1 &
)
{cleanup_lines}
"""
    script_path.write_text(script, encoding="utf-8")
    os.chmod(script_path, 0o755)
    return script_path


def shlex_quote(value: str) -> str:
    return shlex.quote(value)


def stage_self_update(archive_path: Path, *, pid: int | None = None) -> Path:
    target_exe = current_executable_path()
    if target_exe is None or not target_exe.exists():
        raise FileNotFoundError("Could not locate the current application executable.")
    if not _can_write_directory(target_exe.parent):
        raise PermissionError(
            f"Update requires write access to '{target_exe.parent}'. "
            "Run from a writable location or start the app with elevated permissions."
        )

    new_exe = _extract_updated_binary(archive_path)
    if not _is_probably_valid_pyinstaller_binary(new_exe):
        raise ValueError(
            "Extracted update binary is invalid or corrupted (PyInstaller archive marker not found)."
        )
    wait_pid = int(pid or os.getpid())
    debug = is_update_debug_enabled()
    if sys.platform.startswith("win"):
        return _write_windows_updater_script(target_exe, new_exe, wait_pid, debug=debug)
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        return _write_unix_updater_script(target_exe, new_exe, wait_pid, debug=debug)
    raise RuntimeError("Self-update is not supported on this platform.")


def launch_staged_update(script_path: Path) -> None:
    debug = is_update_debug_enabled()
    if sys.platform.startswith("win"):
        if debug:
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            args = [
                "powershell.exe",
                "-NoProfile",
                "-NoExit",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ]
        else:
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            args = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script_path),
            ]
        subprocess.Popen(
            args,
            creationflags=creationflags,
            cwd=str(script_path.parent),
            close_fds=True,
        )
        return

    subprocess.Popen(
        ["/bin/sh", str(script_path)],
        start_new_session=True,
        cwd=str(script_path.parent),
        close_fds=True,
    )


def default_update_download_dir(app_data_dir: str | None = None) -> Path:
    candidates: list[Path] = []
    if app_data_dir:
        candidates.append(Path(app_data_dir) / "updates")
    candidates.append(Path(tempfile.gettempdir()) / APP_PATH_NAME / "updates")

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        rendered = os.path.normcase(str(candidate))
        if rendered in seen:
            continue
        seen.add(rendered)
        unique_candidates.append(candidate)

    for candidate in unique_candidates:
        if _can_write_directory(candidate):
            return candidate

    raise PermissionError(
        "No writable update download directory is available. "
        f"Tried: {', '.join(str(path) for path in unique_candidates)}"
    )


def choose_update_download_path(download_dir: Path, asset_name: str) -> Path:
    destination = download_dir / asset_name
    if not destination.exists():
        return destination

    try:
        destination.unlink()
        return destination
    except OSError:
        stem = Path(asset_name).stem or "update"
        suffix = Path(asset_name).suffix
        unique_name = f"{stem}-{os.getpid()}-{uuid.uuid4().hex[:8]}{suffix}"
        return download_dir / unique_name


def cleanup_stale_update_downloads(download_dir: Path) -> None:
    if not download_dir.exists():
        return
    for path in download_dir.iterdir():
        if path.is_dir() and path.name.startswith("pylrcget-update-"):
            shutil.rmtree(path, ignore_errors=True)
