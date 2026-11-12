"""Shared entry point for installing optional AI dependencies before a sync."""

from PySide6.QtWidgets import QDialog, QWidget

from ui.dialogs.ai_dependencies_dialog import AIDependenciesDialog
from ui.workers.ai.ai_runtime import nvidia_gpu_available
from ui.workers.ai.ai_sync_runtime import (
    _check_ai_sync_available,
    get_missing_ai_dependencies,
)


def ensure_ai_sync_dependencies(parent: QWidget, settings: dict) -> bool:
    device = str(settings.get("device") or "auto")
    prefer_cuda = device == "cuda" or (device == "auto" and nvidia_gpu_available())

    def missing_packages():
        return get_missing_ai_dependencies(
            prefer_cuda=prefer_cuda,
            require_lyrics_aligner=True,
            require_demucs=bool(settings.get("enable_demucs_candidate", True)),
        )

    missing = missing_packages()
    available, message = _check_ai_sync_available()
    if available and not missing:
        return True
    if prefer_cuda and "torch-cuda" in missing:
        message += "\n\nCUDA-enabled Torch is required for the selected GPU mode."
    if AIDependenciesDialog(missing, message, parent).exec() != QDialog.DialogCode.Accepted:
        return False
    available, _ = _check_ai_sync_available()
    return available and not missing_packages()
