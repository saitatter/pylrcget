from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ui.services.update_service import (
    ReleaseAssetInfo,
    check_for_updates,
    download_release_asset,
)


class UpdateCheckWorker(QThread):
    finishedCheck = Signal(object, str)  # UpdateInfo | None, error

    def run(self) -> None:
        try:
            info = check_for_updates()
            self.finishedCheck.emit(info, "")
        except Exception as exc:  # noqa: BLE001
            self.finishedCheck.emit(None, str(exc))


class UpdateDownloadWorker(QThread):
    progressChanged = Signal(int, int)  # received, total
    finishedDownload = Signal(str, str)  # path, error

    def __init__(self, asset: ReleaseAssetInfo, destination: Path, parent=None) -> None:
        super().__init__(parent)
        self.asset = asset
        self.destination = destination

    def run(self) -> None:
        try:
            path = download_release_asset(
                self.asset,
                self.destination,
                progress_callback=lambda received, total: self.progressChanged.emit(int(received), int(total)),
            )
            self.finishedDownload.emit(str(path), "")
        except Exception as exc:  # noqa: BLE001
            self.finishedDownload.emit("", str(exc))
