from __future__ import annotations

import sys

from tests import test_support as _test_support  # noqa: F401
from ui.dialogs.ai_dependencies_dialog import resolve_ai_install_command


def test_resolve_ai_install_command_for_source_runtime(monkeypatch):
    monkeypatch.setenv("PYLRCGET_AI_RUNTIME_DIR", r"C:\PyLrcGet\ai-runtime")
    monkeypatch.setattr(sys, "executable", sys.executable)
    monkeypatch.setattr(sys, "version_info", (3, 13, 0))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr("ui.workers.ai_runtime._is_supported_python", lambda path: True)

    cmd, error = resolve_ai_install_command(["torch", "openai-whisper"])

    assert error == ""
    assert cmd is not None
    assert cmd[:2] == [sys.executable, "-c"]
    assert cmd[-2:] == ["torch", "openai-whisper"]
    assert "venv.EnvBuilder" in cmd[2]


def test_resolve_ai_install_command_for_packaged_exe(monkeypatch):
    monkeypatch.setattr(sys, "executable", r"C:\dist\pylrcget-portable-noai.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("ui.workers.ai_runtime.shutil.which", lambda name: None)

    cmd, error = resolve_ai_install_command(["torch"])

    assert cmd is None
    assert "PYLRCGET_AI_BOOTSTRAP_PYTHON" in error


def test_resolve_ai_install_command_rejects_python_314(monkeypatch):
    monkeypatch.setattr(sys, "executable", sys.executable)
    monkeypatch.setattr(sys, "version_info", (3, 14, 0))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    cmd, error = resolve_ai_install_command(["torch", "whisperx"])

    assert cmd is None
    assert "Python 3.10-3.13" in error
    assert "PYLRCGET_AI_BOOTSTRAP_PYTHON" in error


def test_resolve_ai_runtime_python_rejects_python_314(tmp_path, monkeypatch):
    runtime_python = tmp_path / "python.exe"
    runtime_python.touch()
    monkeypatch.setenv("PYLRCGET_AI_RUNTIME_PYTHON", str(runtime_python))
    monkeypatch.setattr(
        "ui.workers.ai_runtime.subprocess.run",
        lambda *args, **kwargs: type(
            "Result", (), {"returncode": 0, "stdout": "3.14"}
        )(),
    )

    from ui.workers.ai_runtime import resolve_ai_runtime_python

    assert resolve_ai_runtime_python() is None
