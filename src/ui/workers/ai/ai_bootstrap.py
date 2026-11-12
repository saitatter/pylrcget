"""On-demand, checksum-verified Python bootstrap for packaged AI setup."""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_PYTHON_VERSION = "3.13.15"
_RELEASE = "20260807"
# SHA-256 values below match the immutable release assets' GitHub API digests.
_DOWNLOAD_BASE = (
    f"https://github.com/astral-sh/python-build-standalone/releases/download/{_RELEASE}"
)
_BOOTSTRAP_LOCK = threading.Lock()


@dataclass(frozen=True)
class BootstrapRuntimeArtifact:
    """A pinned standalone Python distribution for one OS/architecture."""

    platform_key: str
    filename: str
    sha256: str

    @property
    def url(self) -> str:
        return f"{_DOWNLOAD_BASE}/{self.filename}"


_ARTIFACTS = {
    ("win32", "x86_64"): BootstrapRuntimeArtifact(
        "windows-x86_64",
        "cpython-3.13.15+20260807-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
        "44bf9ae71f4b45e3ba3104ae331c6eff3f7002593c26fd12453eb9310c4f259a",
    ),
    ("win32", "aarch64"): BootstrapRuntimeArtifact(
        "windows-aarch64",
        "cpython-3.13.15+20260807-aarch64-pc-windows-msvc-install_only_stripped.tar.gz",
        "aa90bcd4eccbec2753cd6e134d7a0477b23f2f972d83c7894e507bbc874c4fef",
    ),
    ("linux", "x86_64"): BootstrapRuntimeArtifact(
        "linux-x86_64",
        "cpython-3.13.15+20260807-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
        "faae10a9faa9bec06da009ac69326cc1d9691dc138fec6a1b69159dff1781f35",
    ),
    ("linux", "aarch64"): BootstrapRuntimeArtifact(
        "linux-aarch64",
        "cpython-3.13.15+20260807-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz",
        "1dfc9565c26f8892a33202b5966bdf9ff45c56a57b06e8fa65fecf05030afe5b",
    ),
    ("darwin", "x86_64"): BootstrapRuntimeArtifact(
        "macos-x86_64",
        "cpython-3.13.15+20260807-x86_64-apple-darwin-install_only_stripped.tar.gz",
        "187eed2282e9c3a5b6b14953d564ee25a9f35cf2c209c9fa292186ee48b0e4a1",
    ),
    ("darwin", "aarch64"): BootstrapRuntimeArtifact(
        "macos-aarch64",
        "cpython-3.13.15+20260807-aarch64-apple-darwin-install_only_stripped.tar.gz",
        "dbadb0ffe46f8bace50daaf8a0c5fc6903c003690776da9eb5269e33c856bb53",
    ),
}


def _normalized_platform_name(platform_name: str) -> str:
    if platform_name.startswith("win"):
        return "win32"
    if platform_name.startswith("linux"):
        return "linux"
    if platform_name == "darwin":
        return "darwin"
    return platform_name


def _normalized_machine(machine: str) -> str:
    normalized = machine.strip().casefold().replace("-", "_")
    if normalized in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    if normalized in {"arm64", "aarch64"}:
        return "aarch64"
    return normalized


def resolve_bootstrap_artifact(
    platform_name: str | None = None,
    machine: str | None = None,
) -> BootstrapRuntimeArtifact | None:
    """Return the pinned runtime artifact for the requested host platform."""
    platform_key = _normalized_platform_name(platform_name or sys.platform)
    machine_key = _normalized_machine(machine or platform.machine())
    return _ARTIFACTS.get((platform_key, machine_key))


def bootstrap_python_path(
    runtime_root: Path,
    platform_name: str | None = None,
) -> Path:
    platform_key = _normalized_platform_name(platform_name or sys.platform)
    if platform_key == "win32":
        return runtime_root / "python.exe"
    return runtime_root / "bin" / "python3.13"


def _supported_python(executable: Path) -> bool:
    try:
        result = subprocess.run(
            [
                str(executable),
                "-c",
                "import sys; print('.'.join(map(str, sys.version_info[:3])))",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == _PYTHON_VERSION


def ensure_bootstrap_python(
    artifact: BootstrapRuntimeArtifact,
    runtime_root: Path,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Download, verify, and cache the standalone Python runtime if needed."""
    executable = bootstrap_python_path(runtime_root)
    with _BOOTSTRAP_LOCK:
        if executable.is_file() and _supported_python(executable):
            return executable

        runtime_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="pylrcget-ai-bootstrap-", dir=runtime_root.parent
        ) as temporary:
            temporary_root = Path(temporary)
            archive_path = temporary_root / artifact.filename
            _download_archive(artifact, archive_path, on_progress)
            _extract_verified_archive(
                artifact, archive_path, temporary_root, on_progress
            )

            extracted_root = temporary_root / "python"
            extracted_python = bootstrap_python_path(extracted_root)
            if not extracted_python.is_file() or not _supported_python(
                extracted_python
            ):
                raise RuntimeError(
                    "The downloaded Python bootstrap did not contain a working "
                    f"Python {_PYTHON_VERSION} runtime."
                )

            if executable.is_file() and _supported_python(executable):
                return executable

            backup_root: Path | None = None
            if runtime_root.exists():
                backup_root = runtime_root.with_name(
                    f"{runtime_root.name}.invalid-{uuid.uuid4().hex}"
                )
                runtime_root.replace(backup_root)
            try:
                extracted_root.replace(runtime_root)
            except OSError:
                if executable.is_file() and _supported_python(executable):
                    return executable
                if (
                    backup_root is not None
                    and backup_root.exists()
                    and not runtime_root.exists()
                ):
                    backup_root.replace(runtime_root)
                raise
            if backup_root is not None:
                shutil.rmtree(backup_root, ignore_errors=True)

        executable = bootstrap_python_path(runtime_root)
        if not _supported_python(executable):
            raise RuntimeError("The cached Python bootstrap failed its version check.")
        return executable


def _download_archive(
    artifact: BootstrapRuntimeArtifact,
    destination: Path,
    on_progress: Callable[[str], None] | None,
) -> None:
    import requests

    digest = hashlib.sha256()
    downloaded = 0
    last_reported_mb = 0
    try:
        with (
            requests.get(
                artifact.url,
                headers={"User-Agent": "PyLrcGet-AI-bootstrap"},
                stream=True,
                timeout=(15, 45),
            ) as response,
            destination.open("wb") as output,
        ):
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                downloaded_mb = downloaded // (10 * 1024 * 1024)
                if on_progress is not None and downloaded_mb > last_reported_mb:
                    last_reported_mb = downloaded_mb
                    on_progress(
                        f"Downloaded {downloaded_mb * 10} MB of Python {_PYTHON_VERSION}."
                    )
    except Exception as exc:
        raise RuntimeError(f"Could not download the Python bootstrap: {exc}") from exc

    if digest.hexdigest() != artifact.sha256:
        raise RuntimeError(
            "The downloaded Python bootstrap failed its SHA-256 verification; "
            "the archive was discarded."
        )
    if on_progress is not None:
        on_progress("Python bootstrap download verified.")


def _extract_verified_archive(
    artifact: BootstrapRuntimeArtifact,
    archive_path: Path,
    destination: Path,
    on_progress: Callable[[str], None] | None,
) -> None:
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if not members or any(
                member.name != "python" and not member.name.startswith("python/")
                for member in members
            ):
                raise RuntimeError(
                    "The Python bootstrap archive has an unexpected layout."
                )
            archive.extractall(destination, members=members, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise RuntimeError(f"Could not unpack the Python bootstrap: {exc}") from exc
    if on_progress is not None:
        on_progress(
            f"Prepared Python {_PYTHON_VERSION} bootstrap ({artifact.platform_key})."
        )


__all__ = [
    "BootstrapRuntimeArtifact",
    "bootstrap_python_path",
    "ensure_bootstrap_python",
    "resolve_bootstrap_artifact",
]
