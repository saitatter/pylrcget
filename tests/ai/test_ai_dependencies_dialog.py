from __future__ import annotations

import sys

from tests import test_support as _test_support  # noqa: F401

from ui.dialogs.ai_dependencies_dialog import resolve_ai_install_command


def test_resolve_ai_install_command_for_source_runtime(monkeypatch):
    monkeypatch.setattr(sys, "executable", r"C:\Python311\python.exe")
    monkeypatch.setattr(sys, "version_info", (3, 13, 0))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    cmd, error = resolve_ai_install_command(["torch", "openai-whisper"])

    assert error == ""
    assert cmd is not None
    assert cmd[:4] == [r"C:\Python311\python.exe", "-m", "pip", "install"]
    assert cmd[4:] == ["torch", "openai-whisper"]


def test_resolve_ai_install_command_for_packaged_exe(monkeypatch):
    monkeypatch.setattr(sys, "executable", r"C:\dist\pylrcget-portable-noai.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    cmd, error = resolve_ai_install_command(["torch"])

    assert cmd is None
    assert "cannot install Python packages into itself" in error
    assert "pylrcget-windows-portable-ai.exe" in error


def test_resolve_ai_install_command_rejects_python_314(monkeypatch):
    monkeypatch.setattr(sys, "executable", r"C:\Python314\python.exe")
    monkeypatch.setattr(sys, "version_info", (3, 14, 0))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    cmd, error = resolve_ai_install_command(["torch", "whisperx"])

    assert cmd is None
    assert "Python 3.10-3.13" in error
    assert "ctranslate2" in error
    assert "py -3.13 -m venv venv313" in error
