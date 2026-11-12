import io
import tarfile
from unittest.mock import MagicMock

import pytest

from ui.workers.ai import ai_aligner_bootstrap as bootstrap


def write_archive(path, *, names=None):
    prefix = f"lyrics-aligner-{bootstrap._COMMIT}"
    names = names if names is not None else [f"{prefix}/{name}" for name in (*bootstrap._FILES, "LICENSE")]
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))


def test_aligner_installs_without_git_and_repairs_partial_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_download", write_archive)
    root = tmp_path / "aligner"
    root.mkdir()
    (root / "partial").touch()
    bootstrap.ensure_lyrics_aligner(root)
    assert bootstrap._complete(root)
    assert (root / "LICENSE").is_file()
    assert not (root / "partial").exists()
    assert not list(tmp_path.glob("aligner.incomplete-*"))
    monkeypatch.setattr(bootstrap, "_download", lambda _: pytest.fail("Cache must skip download"))
    bootstrap.ensure_lyrics_aligner(root)


def test_aligner_rejects_invalid_checksum(tmp_path, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [b"incorrect archive"]
    monkeypatch.setattr(bootstrap.requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError, match="SHA-256"):
        bootstrap._download(tmp_path / "aligner.tar.gz")


@pytest.mark.parametrize("names", [["../escape"], [f"lyrics-aligner-{bootstrap._COMMIT}/align.py"]])
def test_aligner_rejects_unsafe_or_incomplete_archives(tmp_path, monkeypatch, names):
    monkeypatch.setattr(bootstrap, "_download", lambda path: write_archive(path, names=names))
    root = tmp_path / "aligner"
    with pytest.raises(RuntimeError):
        bootstrap.ensure_lyrics_aligner(root)
    assert not root.exists()
    assert not (tmp_path / "escape").exists()


def test_bad_archive_reports_an_installation_error(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_download", lambda path: path.write_bytes(b"invalid tar"))
    with pytest.raises(RuntimeError, match="Could not unpack"):
        bootstrap.ensure_lyrics_aligner(tmp_path / "aligner")


def test_install_plan_prepares_aligner_outside_the_pip_command(monkeypatch, tmp_path):
    from ui.workers.ai.ai_runtime import resolve_ai_install_plan

    monkeypatch.setenv("PYLRCGET_AI_RUNTIME_DIR", str(tmp_path / "ai-runtime"))
    plan = resolve_ai_install_plan(["lyrics-aligner"])
    assert plan.lyrics_aligner_root == tmp_path / "lyrics-aligner"
    assert "git" not in plan.command[2]
    assert "g2p-en" in plan.command[2]
