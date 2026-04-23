from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QProgressBar,
)

from ui.services.update_service import (
    choose_update_download_path,
    UpdateInfo,
    cleanup_stale_update_downloads,
    current_app_version,
    default_update_download_dir,
    launch_platform_installer,
)
from ui.workers.update_workers import UpdateCheckWorker, UpdateDownloadWorker


class AboutDialog(QDialog):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._update_info: UpdateInfo | None = None
        self._check_worker: UpdateCheckWorker | None = None
        self._download_worker: UpdateDownloadWorker | None = None
        self._pending_install = False

        self.setWindowTitle("About PyLrcGet")
        self.resize(760, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("PyLrcGet")
        title.setObjectName("DialogTitle")
        current_version = QLabel(f"Current version: v{current_app_version()}")
        current_version.setObjectName("DialogSubtle")
        summary = QLabel(
            "Desktop-native lyrics manager with local library browsing, editing, playback, and LRCLIB integration."
        )
        summary.setWordWrap(True)
        summary.setObjectName("DialogSubtle")
        root.addWidget(title)
        root.addWidget(current_version)
        root.addWidget(summary)

        self.status_label = QLabel("Check for updates to compare your current build with the latest GitHub release.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        info_row = QWidget()
        info_layout = QHBoxLayout(info_row)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(12)
        self.latest_version_label = QLabel("Latest release: unknown")
        self.asset_label = QLabel("Platform asset: unknown")
        self.asset_label.setWordWrap(True)
        info_layout.addWidget(self.latest_version_label, 1)
        info_layout.addWidget(self.asset_label, 1)
        root.addWidget(info_row)

        self.release_notes = QTextBrowser()
        self.release_notes.setOpenExternalLinks(True)
        self.release_notes.setPlaceholderText("Release notes will appear here after checking for updates.")
        root.addWidget(self.release_notes, 1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self.btn_check = QPushButton("Check for updates")
        self.btn_release = QPushButton("Open release page")
        self.btn_download = QPushButton("Download update")
        self.btn_install = QPushButton("Install update")
        self.btn_close = QPushButton("Close")
        self.btn_check.clicked.connect(self.check_for_updates)
        self.btn_release.clicked.connect(self._open_release_page)
        self.btn_download.clicked.connect(lambda: self._download_update(install=False))
        self.btn_install.clicked.connect(lambda: self._download_update(install=True))
        self.btn_close.clicked.connect(self.accept)
        button_row.addWidget(self.btn_check)
        button_row.addWidget(self.btn_release)
        button_row.addWidget(self.btn_download)
        button_row.addWidget(self.btn_install)
        button_row.addStretch(1)
        button_row.addWidget(self.btn_close)
        root.addLayout(button_row)

        note = QLabel(
            "Automatic install is available for packaged builds when a supported platform installer asset is "
            "published."
        )
        note.setWordWrap(True)
        note.setObjectName("DialogSubtle")
        root.addWidget(note)

        self._refresh_actions()
        QTimer.singleShot(0, self.check_for_updates)

    def check_for_updates(self) -> None:
        if self._check_worker is not None and self._check_worker.isRunning():
            return
        self.status_label.setText("Checking GitHub releases...")
        self.progress.setVisible(False)
        self.btn_check.setEnabled(False)
        self._check_worker = UpdateCheckWorker(self)
        self._check_worker.finishedCheck.connect(self._on_check_finished)
        self._check_worker.start()

    def _on_check_finished(self, info, error: str) -> None:
        self.btn_check.setEnabled(True)
        self._check_worker = None
        if error:
            self._update_info = None
            self.status_label.setText(f"Update check failed: {error}")
            self.latest_version_label.setText("Latest release: unavailable")
            self.asset_label.setText("Platform asset: unavailable")
            self.release_notes.setPlainText("")
            self._refresh_actions()
            return

        self._update_info = info
        assert isinstance(info, UpdateInfo)
        self.latest_version_label.setText(f"Latest release: v{info.latest_version}")
        if info.asset is not None:
            self.asset_label.setText(f"Platform asset: {info.asset.name}")
        else:
            self.asset_label.setText(f"Platform asset: not available for {info.platform_label}")

        if info.is_update_available:
            self.status_label.setText(
                f"Update available: v{info.current_version} -> v{info.latest_version}"
            )
        else:
            self.status_label.setText(f"You're up to date on v{info.current_version}.")

        notes = info.body.strip() or "No changelog text was published for this release."
        self.release_notes.setMarkdown(notes)
        self._refresh_actions()

    def _download_update(self, *, install: bool) -> None:
        info = self._update_info
        if info is None or info.asset is None:
            return
        if self._download_worker is not None and self._download_worker.isRunning():
            return

        download_dir = default_update_download_dir(getattr(self.app_state, "app_data_dir", None))
        cleanup_stale_update_downloads(download_dir)
        destination = choose_update_download_path(download_dir, info.asset.name)
        self._pending_install = bool(install)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText(f"Downloading {info.asset.name}...")
        self._download_worker = UpdateDownloadWorker(info.asset, destination, self)
        self._download_worker.progressChanged.connect(self._on_download_progress)
        self._download_worker.finishedDownload.connect(self._on_download_finished)
        self._refresh_actions()
        self._download_worker.start()

    def _on_download_progress(self, received: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(received)
        else:
            self.progress.setRange(0, 0)

    def _on_download_finished(self, path: str, error: str) -> None:
        self._download_worker = None
        self._refresh_actions()
        if error:
            self.status_label.setText(f"Download failed: {error}")
            return

        download_path = Path(path)
        if self._pending_install and self._update_info is not None and self._update_info.install_supported:
            QMessageBox.information(
                self,
                "Ready to install",
                "The update installer will now launch.\n"
                "The application will close automatically.\n"
                "Follow the on-screen prompts to proceed with the installation.",
            )
            try:
                launch_platform_installer(download_path)
            except (RuntimeError, FileNotFoundError, OSError) as exc:
                self.status_label.setText(f"Could not stage the update: {exc}")
                return

            # Do NOT quit here — let the Inno Setup installer close the app
            # via /CLOSEAPPLICATIONS so that Restart Manager can reopen it
            # after the update finishes.
            self.status_label.setText("Waiting for installer…")
            return

        self.status_label.setText(f"Update downloaded to {download_path}")
        if download_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(download_path.parent)))

    def _open_release_page(self) -> None:
        info = self._update_info
        if info is None or not info.html_url:
            return
        QDesktopServices.openUrl(QUrl(info.html_url))

    def _refresh_actions(self) -> None:
        info = self._update_info
        busy = self._check_worker is not None or self._download_worker is not None
        has_release = info is not None and bool(info.html_url)
        has_update_asset = info is not None and info.is_update_available and info.asset is not None
        self.btn_release.setEnabled(has_release and not busy)
        self.btn_download.setEnabled(has_update_asset and not busy)
        self.btn_install.setEnabled(
            bool(info is not None and info.install_supported and info.is_update_available and not busy)
        )
        self.btn_check.setEnabled(not busy)
