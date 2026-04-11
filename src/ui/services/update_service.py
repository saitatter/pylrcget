from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

import requests
from packaging.version import InvalidVersion, Version


GITHUB_REPOSITORY = "saitatter/pylrcget"
GITHUB_RELEASES_LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"


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


def current_app_version() -> str:
    try:
        return importlib.metadata.version("pylrcget")
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        data = tomllib.loads((project_root() / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


def current_executable_path() -> Path | None:
    try:
        return Path(sys.executable).resolve()
    except Exception:
        return None


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


def platform_asset_name() -> str | None:
    if sys.platform.startswith("win"):
        return "pylrcget-windows.zip"
    if sys.platform == "darwin":
        return "pylrcget-macos.tar.gz"
    if sys.platform.startswith("linux"):
        return "pylrcget-linux.tar.gz"
    return None


def select_platform_asset(assets_payload: list[dict]) -> ReleaseAssetInfo | None:
    expected_name = platform_asset_name()
    if not expected_name:
        return None

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


def can_self_update(asset: ReleaseAssetInfo | None) -> bool:
    if asset is None or not is_frozen_build():
        return False
    exe_path = current_executable_path()
    if exe_path is None or not exe_path.exists():
        return False
    if sys.platform.startswith("win"):
        return asset.name.endswith(".zip") and exe_path.suffix.lower() == ".exe"
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        return asset.name.endswith(".tar.gz")
    return False


def check_for_updates(*, timeout_s: float = 10.0, session: requests.Session | None = None) -> UpdateInfo:
    http = session or requests.Session()
    response = http.get(
        GITHUB_RELEASES_LATEST_URL,
        timeout=timeout_s,
        headers={"Accept": "application/vnd.github+json"},
    )
    response.raise_for_status()
    payload = response.json()

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
        install_supported=can_self_update(asset) and is_update_available,
        platform_label=platform_label(),
    )


def download_release_asset(
    asset: ReleaseAssetInfo,
    destination: Path,
    *,
    timeout_s: float = 30.0,
    session: requests.Session | None = None,
    progress_callback=None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    http = session or requests.Session()
    with http.get(asset.download_url, stream=True, timeout=timeout_s) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or asset.size or 0)
        downloaded = 0
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                if progress_callback is not None:
                    progress_callback(downloaded, total)
    return destination


def _extract_updated_binary(archive_path: Path) -> Path:
    staging_dir = Path(tempfile.mkdtemp(prefix="pylrcget-update-"))
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


def _write_windows_updater_script(target_exe: Path, new_exe: Path, pid: int) -> Path:
    script_path = new_exe.parent / "apply-update.ps1"
    script = f"""
$ErrorActionPreference = 'Stop'
$pidToWait = {int(pid)}
$target = {str(target_exe)!r}
$newExe = {str(new_exe)!r}
while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{
    Start-Sleep -Milliseconds 400
}}
Copy-Item -LiteralPath $newExe -Destination $target -Force
Start-Process -FilePath $target
Remove-Item -LiteralPath $newExe -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
""".strip()
    script_path.write_text(script, encoding="utf-8")
    return script_path


def _write_unix_updater_script(target_exe: Path, new_exe: Path, pid: int) -> Path:
    script_path = new_exe.parent / "apply-update.sh"
    script = f"""#!/bin/sh
set -e
PID_TO_WAIT="{int(pid)}"
TARGET={shlex_quote(str(target_exe))}
NEW_EXE={shlex_quote(str(new_exe))}
while kill -0 "$PID_TO_WAIT" 2>/dev/null; do
  sleep 1
done
cp "$NEW_EXE" "$TARGET"
chmod +x "$TARGET"
"$TARGET" >/dev/null 2>&1 &
rm -f "$NEW_EXE"
rm -f "$0"
"""
    script_path.write_text(script, encoding="utf-8")
    os.chmod(script_path, 0o755)
    return script_path


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def stage_self_update(archive_path: Path, *, pid: int | None = None) -> Path:
    target_exe = current_executable_path()
    if target_exe is None or not target_exe.exists():
        raise FileNotFoundError("Could not locate the current application executable.")

    new_exe = _extract_updated_binary(archive_path)
    wait_pid = int(pid or os.getpid())
    if sys.platform.startswith("win"):
        return _write_windows_updater_script(target_exe, new_exe, wait_pid)
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        return _write_unix_updater_script(target_exe, new_exe, wait_pid)
    raise RuntimeError("Self-update is not supported on this platform.")


def launch_staged_update(script_path: Path) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        return

    subprocess.Popen(
        ["/bin/sh", str(script_path)],
        start_new_session=True,
        close_fds=True,
    )


def default_update_download_dir(app_data_dir: str | None = None) -> Path:
    base = Path(app_data_dir) if app_data_dir else Path(tempfile.gettempdir())
    target = base / "updates"
    target.mkdir(parents=True, exist_ok=True)
    return target


def cleanup_stale_update_downloads(download_dir: Path) -> None:
    if not download_dir.exists():
        return
    for path in download_dir.iterdir():
        if path.is_dir() and path.name.startswith("pylrcget-update-"):
            shutil.rmtree(path, ignore_errors=True)
