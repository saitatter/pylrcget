from __future__ import annotations

import sys
from pathlib import Path

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai.ai_sync_service import (
    AI_SYNC_PROTOCOL_VERSION,
    PersistentAIRuntime,
    build_runtime_environment,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def test_runtime_environment_replaces_python_path() -> None:
    environment = build_runtime_environment(SRC_ROOT)

    assert environment["PYTHONPATH"] == str(SRC_ROOT)
    assert "PYTHONHOME" not in environment
    assert "PYTHONEXECUTABLE" not in environment
    assert "PYTHONUSERBASE" not in environment


def test_runtime_uses_application_nltk_data_without_losing_user_override(monkeypatch, tmp_path):
    import os

    monkeypatch.setenv("PYLRCGET_AI_RUNTIME_DIR", str(tmp_path / "ai-runtime"))
    monkeypatch.setenv("NLTK_DATA", str(tmp_path / "custom-data"))
    environment = build_runtime_environment(SRC_ROOT)
    assert environment["NLTK_DATA"].split(os.pathsep) == [str(tmp_path / "custom-data"), str(tmp_path / "nltk_data")]
    assert environment["PYTHONUTF8"] == "1"


def test_external_runtime_handshake_and_shutdown() -> None:
    service = PersistentAIRuntime(sys.executable, SRC_ROOT, device="cpu")
    try:
        service._ensure_started_locked()
        assert service.is_running is True
        assert "persistent_runtime" in service.capabilities["capabilities"]
        assert service.capabilities["protocol_version"] == AI_SYNC_PROTOCOL_VERSION
        assert service.capabilities["runtime_python"]
        assert "lyrics-aligner" in service.capabilities["available_backends"]
    finally:
        service.shutdown()

    assert service.is_running is False


def test_protocol_version_is_stable() -> None:
    assert AI_SYNC_PROTOCOL_VERSION == 1
