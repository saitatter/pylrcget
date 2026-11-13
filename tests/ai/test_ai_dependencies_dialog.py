from __future__ import annotations

import hashlib
import io
import sys
import tarfile

import pytest

from tests import test_support as _test_support
from ui.workers.ai.ai_bootstrap import (
    BootstrapRuntimeArtifact,
    _download_archive,
    _extract_verified_archive,
    bootstrap_python_path,
    ensure_bootstrap_python,
    resolve_bootstrap_artifact,
)
from ui.workers.ai.ai_runtime import AIInstallPlan, resolve_ai_install_plan


def test_installer_does_not_leak_source_python_paths_into_the_isolated_runtime(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from ui.dialogs.ai_dependencies_dialog import _InstallAIDependenciesWorker

    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "PYTHONUSERBASE"):
        monkeypatch.setenv(name, "source-environment")
    popen = Mock(return_value=SimpleNamespace(stdout=iter([]), wait=lambda: 0))
    monkeypatch.setattr("ui.dialogs.ai_dependencies_dialog.subprocess.Popen", popen)
    worker = _InstallAIDependenciesWorker(AIInstallPlan(command=[sys.executable, "-c", "pass"]))
    worker.run()
    environment = popen.call_args.kwargs["env"]
    assert not any(name in environment for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "PYTHONUSERBASE"))
    assert environment["PYTHONUTF8"] == "1"


def test_resolve_ai_install_command_for_source_runtime(monkeypatch):
    monkeypatch.setenv("PYLRCGET_AI_RUNTIME_DIR", r"C:\PyLrcGet\ai-runtime")
    monkeypatch.setattr(sys, "executable", sys.executable)
    monkeypatch.setattr(sys, "version_info", (3, 13, 15))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        "ui.workers.ai.ai_runtime._is_supported_python", lambda path: True
    )

    plan = resolve_ai_install_plan(["torch", "openai-whisper"])

    assert plan.error == ""
    assert plan.command is not None
    cmd = plan.command
    assert cmd[:2] == [sys.executable, "-c"]
    assert cmd[-2:] == ["torch", "openai-whisper"]
    assert "venv.EnvBuilder" in cmd[2]


def test_packaged_runtime_can_install_without_system_python(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\dist\pylrcget-portable-noai.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("ui.workers.ai.ai_bootstrap.platform.machine", lambda: "AMD64")
    monkeypatch.setattr("ui.workers.ai.ai_runtime.shutil.which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    plan = resolve_ai_install_plan(["torch"])

    assert plan.can_install
    assert plan.command is None
    assert plan.error == ""
    assert plan.bootstrap_artifact is not None
    assert plan.bootstrap_artifact.platform_key == "windows-x86_64"
    assert plan.bootstrap_runtime_root == (
        tmp_path / "PyLrcGet" / "python-bootstrap" / "windows-x86_64"
    )
    assert plan.bootstrap_arguments[-1] == "torch"


def test_ai_setup_dialog_enables_install_for_bootstrap_plan(tmp_path, monkeypatch):
    app = _test_support.qt_app()
    if app is None:
        pytest.skip("PySide6 is unavailable")

    from ui.dialogs.ai_dependencies_dialog import AIDependenciesDialog

    artifact = resolve_bootstrap_artifact("win32", "AMD64")
    assert artifact is not None
    plan = AIInstallPlan(
        bootstrap_artifact=artifact,
        bootstrap_runtime_root=tmp_path / "python-bootstrap" / artifact.platform_key,
        bootstrap_arguments=("-c", "pass", "torch"),
    )
    monkeypatch.setattr(
        "ui.dialogs.ai_dependencies_dialog.resolve_ai_install_plan",
        lambda _packages: plan,
    )

    dialog = AIDependenciesDialog(["torch"], "Missing dependencies", None)
    try:
        assert dialog.btn_install.isEnabled()
        assert not dialog.btn_copy.isEnabled()
        assert "setup downloads" in dialog.btn_copy.toolTip()
    finally:
        dialog.close()


def test_resolve_ai_install_command_rejects_python_314(monkeypatch):
    monkeypatch.setattr(sys, "executable", sys.executable)
    monkeypatch.setattr(sys, "version_info", (3, 14, 0))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        "ui.workers.ai.ai_runtime._is_supported_python", lambda path: True
    )

    plan = resolve_ai_install_plan(["torch", "whisperx"])

    assert plan.command is None
    assert "Python 3.13.15" in plan.error


def test_bootstrap_artifacts_are_pinned_for_release_platforms():
    expected = {
        ("win32", "AMD64"): "windows-x86_64",
        ("win32", "arm64"): "windows-aarch64",
        ("linux", "x86_64"): "linux-x86_64",
        ("linux", "aarch64"): "linux-aarch64",
        ("darwin", "x86_64"): "macos-x86_64",
        ("darwin", "arm64"): "macos-aarch64",
    }
    for (platform_name, machine), platform_key in expected.items():
        artifact = resolve_bootstrap_artifact(platform_name, machine)
        assert artifact is not None
        assert artifact.platform_key == platform_key
        assert len(artifact.sha256) == 64
        assert artifact.url.endswith(artifact.filename)


def test_bootstrap_python_path_uses_platform_layout(tmp_path):
    assert bootstrap_python_path(tmp_path, "win32") == tmp_path / "python.exe"
    assert bootstrap_python_path(tmp_path, "linux") == (tmp_path / "bin" / "python3.13")


def test_bootstrap_download_checks_sha256(tmp_path, monkeypatch):
    import requests

    payload = b"pinned test payload"
    artifact = BootstrapRuntimeArtifact(
        "test", "python.tar.gz", hashlib.sha256(payload).hexdigest()
    )

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield self.read(chunk_size)

    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _Response(payload),
    )
    target = tmp_path / "python.tar.gz"
    _download_archive(artifact, target, None)
    assert target.read_bytes() == payload

    incorrect_artifact = BootstrapRuntimeArtifact("test", "python.tar.gz", "0" * 64)
    try:
        _download_archive(incorrect_artifact, target, None)
    except RuntimeError as exc:
        assert "SHA-256" in str(exc)
    else:
        raise AssertionError("A bad bootstrap checksum must be rejected")


def test_bootstrap_archive_rejects_paths_outside_python_root(tmp_path):
    archive_path = tmp_path / "bad.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))

    try:
        _extract_verified_archive(
            BootstrapRuntimeArtifact("test", "bad.tar.gz", "0" * 64),
            archive_path,
            tmp_path / "extract",
            None,
        )
    except RuntimeError as exc:
        assert "unexpected layout" in str(exc)
    else:
        raise AssertionError("Paths outside the expected archive root must be rejected")


def test_bootstrap_runtime_is_extracted_into_stable_cache(tmp_path, monkeypatch):
    from ui.workers.ai import ai_bootstrap

    artifact = BootstrapRuntimeArtifact("windows-x86_64", "python.tar.gz", "0" * 64)
    runtime_root = tmp_path / "cache" / artifact.platform_key

    def write_archive(_artifact, archive_path, _progress):
        with tarfile.open(archive_path, "w:gz") as archive:
            payload = b"test interpreter placeholder"
            info = tarfile.TarInfo("python/python.exe")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(ai_bootstrap, "_download_archive", write_archive)
    monkeypatch.setattr(ai_bootstrap, "_supported_python", lambda _path: True)

    executable = ensure_bootstrap_python(artifact, runtime_root)

    assert executable == runtime_root / "python.exe"
    assert executable.read_bytes() == b"test interpreter placeholder"


def test_bootstrap_cache_hit_skips_download(tmp_path, monkeypatch):
    from ui.workers.ai import ai_bootstrap

    artifact = BootstrapRuntimeArtifact("windows-x86_64", "python.tar.gz", "0" * 64)
    runtime_root = tmp_path / artifact.platform_key
    runtime_root.mkdir()
    cached_python = runtime_root / "python.exe"
    cached_python.write_bytes(b"cached")
    monkeypatch.setattr(ai_bootstrap, "_supported_python", lambda _path: True)
    monkeypatch.setattr(
        ai_bootstrap,
        "_download_archive",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected download")),
    )

    assert ensure_bootstrap_python(artifact, runtime_root) == cached_python


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
