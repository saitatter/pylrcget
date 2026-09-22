from __future__ import annotations

import sys

from tests import test_support as _test_support  # noqa: F401
from ui.dialogs.ai_dependencies_dialog import resolve_ai_install_command


def test_resolve_ai_install_command_for_source_runtime(monkeypatch):
    monkeypatch.setenv("PYLRCGET_AI_RUNTIME_DIR", r"C:\PyLrcGet\ai-runtime")
    monkeypatch.setattr(sys, "executable", sys.executable)
    monkeypatch.setattr(sys, "version_info", (3, 13, 15))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr("ui.workers.ai.ai_runtime._is_supported_python", lambda path: True)

    cmd, error = resolve_ai_install_command(["torch", "openai-whisper"])

    assert error == ""
    assert cmd is not None
    assert cmd[:2] == [sys.executable, "-c"]
    assert cmd[-2:] == ["torch", "openai-whisper"]
    assert "venv.EnvBuilder" in cmd[2]


def test_resolve_ai_install_command_for_packaged_exe(monkeypatch):
    monkeypatch.setattr(sys, "executable", r"C:\dist\pylrcget-portable-noai.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("ui.workers.ai.ai_runtime.shutil.which", lambda name: None)

    cmd, error = resolve_ai_install_command(["torch"])

    assert cmd is None
    assert "PYLRCGET_AI_BOOTSTRAP_PYTHON" in error


def test_resolve_ai_install_command_rejects_python_314(monkeypatch):
    monkeypatch.setattr(sys, "executable", sys.executable)
    monkeypatch.setattr(sys, "version_info", (3, 14, 0))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    cmd, error = resolve_ai_install_command(["torch", "whisperx"])

    assert cmd is None
    assert "Python 3.13.15" in error
    assert "PYLRCGET_AI_BOOTSTRAP_PYTHON" in error


def test_resolve_ai_runtime_python_rejects_python_314(tmp_path, monkeypatch):
    runtime_python = tmp_path / "python.exe"
    runtime_python.touch()
    monkeypatch.setenv("PYLRCGET_AI_RUNTIME_PYTHON", str(runtime_python))
    monkeypatch.setattr(
        "ui.workers.ai.ai_runtime.subprocess.run",
        lambda *args, **kwargs: type(
            "Result", (), {"returncode": 0, "stdout": "3.14.0"}
        )(),
    )

    from ui.workers.ai.ai_runtime import resolve_ai_runtime_python

    assert resolve_ai_runtime_python() is None


def test_ai_runtime_accepts_only_python_31315(tmp_path, monkeypatch):
    from ui.workers.ai.ai_runtime import _is_supported_python

    runtime_python = tmp_path / "python.exe"
    runtime_python.touch()

    for version, expected in (
        ("3.13.15", True),
        ("3.13.14", False),
        ("3.14.0", False),
    ):
        monkeypatch.setattr(
            "ui.workers.ai.ai_runtime.subprocess.run",
            lambda *args, _version=version, **kwargs: type(
                "Result", (), {"returncode": 0, "stdout": _version}
            )(),
        )
        assert _is_supported_python(runtime_python) is expected


def test_default_ai_runtime_dir_reuses_the_existing_runtime_for_the_pinned_python(
    tmp_path, monkeypatch
):
    from ui.workers.ai.ai_runtime import default_ai_runtime_dir

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_ai_runtime_dir() == tmp_path / "PyLrcGet" / "ai-runtime"
