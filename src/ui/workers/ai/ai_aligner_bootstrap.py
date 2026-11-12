"""Install the pinned English aligner without requiring Git on the host."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import tempfile
import threading
import uuid
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import requests

_COMMIT = "72be8a14b9126c201e0b8920513764c44ccd3f9e"
_URL = f"https://codeload.github.com/schufo/lyrics-aligner/tar.gz/{_COMMIT}"
_SHA256 = "ee84a5ce80e52aa958df02e34454d4f232830646cbe49229f60cba8ccd1211a6"
_FILES = ("align.py", "model.py", "model_parameters.pth", "files/phoneme2idx.pickle")
_LOCK = threading.Lock()


def _complete(root: Path) -> bool:
    return all((root / name).is_file() for name in _FILES)


def _download(archive_path: Path) -> None:
    digest = hashlib.sha256()
    with requests.get(_URL, stream=True, timeout=(15, 60)) as response, archive_path.open("wb") as output:
        response.raise_for_status()
        for chunk in response.iter_content(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != _SHA256:
        raise RuntimeError("The English aligner download failed its SHA-256 verification.")


def ensure_lyrics_aligner(root: Path, on_progress: Callable[[str], None] | None = None) -> None:
    with _LOCK:
        if _complete(root):
            return
        if on_progress:
            on_progress("Downloading the English alignment backend (about 36 MB).")
        root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pylrcget-aligner-", dir=root.parent) as temporary:
            staging = Path(temporary)
            archive_path = staging / "aligner.tar.gz"
            try:
                _download(archive_path)
            except requests.RequestException as exc:
                raise RuntimeError(f"Could not download the English aligner: {exc}") from exc
            prefix = f"lyrics-aligner-{_COMMIT}"
            try:
                with tarfile.open(archive_path, "r:gz") as archive:
                    members = archive.getmembers()
                    if not members or any(
                        ".." in PurePosixPath(member.name).parts or (
                            member.name != prefix and not member.name.startswith(prefix + "/")
                        ) for member in members
                    ):
                        raise RuntimeError("The English aligner archive has an unexpected layout.")
                    archive.extractall(staging, members=members, filter="data")
            except tarfile.TarError as exc:
                raise RuntimeError(f"Could not unpack the English aligner: {exc}") from exc
            extracted = staging / prefix
            if not _complete(extracted) or not (extracted / "LICENSE").is_file():
                raise RuntimeError("The English aligner archive is incomplete.")
            backup = root.with_name(f"{root.name}.incomplete-{uuid.uuid4().hex}")
            had_previous = root.exists()
            if had_previous:
                root.replace(backup)
            try:
                extracted.replace(root)
            except OSError:
                if had_previous:
                    backup.replace(root)
                raise
            if had_previous:
                shutil.rmtree(backup)
        if on_progress:
            on_progress("English alignment backend verified and installed.")
