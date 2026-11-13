from unittest.mock import Mock

from PySide6.QtWidgets import QDialog

from ui.services import ai_setup


def test_auto_accepts_cpu_runtime_instead_of_requiring_cuda(monkeypatch):
    missing = Mock(side_effect=lambda **kwargs: ["torch-cuda"] if kwargs["prefer_cuda"] else [])
    dialog = Mock()
    monkeypatch.setattr(ai_setup, "get_missing_ai_dependencies", missing)
    monkeypatch.setattr(ai_setup, "_check_ai_sync_available", lambda: (True, ""))
    monkeypatch.setattr(ai_setup, "nvidia_gpu_available", lambda: True)
    monkeypatch.setattr(ai_setup, "AIDependenciesDialog", dialog)
    assert ai_setup.ensure_ai_sync_dependencies(None, {"device": "auto"})
    assert missing.call_args.kwargs["prefer_cuda"] is False
    dialog.assert_not_called()


def test_fresh_auto_setup_prefers_cuda_on_an_nvidia_host(monkeypatch):
    monkeypatch.setattr(ai_setup, "get_missing_ai_dependencies", Mock(side_effect=[["torch"], []]))
    monkeypatch.setattr(ai_setup, "_check_ai_sync_available", Mock(side_effect=[(False, "Missing Torch"), (True, "")]))
    monkeypatch.setattr(ai_setup, "nvidia_gpu_available", lambda: True)
    dialog = Mock()
    dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
    monkeypatch.setattr(ai_setup, "AIDependenciesDialog", dialog)
    assert ai_setup.ensure_ai_sync_dependencies(None, {"device": "auto"})
    assert dialog.call_args.args[0] == ["torch", "torch-cuda"]


def test_explicit_cuda_still_requires_cuda_and_respects_setup_cancellation(monkeypatch):
    monkeypatch.setattr(ai_setup, "get_missing_ai_dependencies", lambda **kwargs: ["torch-cuda"])
    monkeypatch.setattr(ai_setup, "_check_ai_sync_available", lambda: (True, ""))
    dialog = Mock()
    dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
    monkeypatch.setattr(ai_setup, "AIDependenciesDialog", dialog)
    assert not ai_setup.ensure_ai_sync_dependencies(None, {"device": "cuda"})
    assert "CUDA-enabled Torch is required" in dialog.call_args.args[1]
