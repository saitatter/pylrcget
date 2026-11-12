from __future__ import annotations

import logging
import subprocess
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ui.button_roles import set_button_role
from ui.spacing import SPACE_2, SPACE_3, SPACE_4, set_layout_spacing
from ui.workers.ai.ai_aligner_bootstrap import ensure_lyrics_aligner
from ui.workers.ai.ai_bootstrap import ensure_bootstrap_python
from ui.workers.ai.ai_runtime import AIInstallPlan, resolve_ai_install_plan
from ui.workers.ai.ai_sync_worker import get_missing_ai_dependencies

logger = logging.getLogger(__name__)


class _InstallAIDependenciesWorker(QThread):
    lineReady = Signal(str)
    finishedInstall = Signal(bool, str)

    def __init__(self, plan: AIInstallPlan, parent=None) -> None:
        super().__init__(parent)
        self._plan = plan

    def run(self) -> None:
        if (
            self._plan.bootstrap_artifact is not None
            and self._plan.bootstrap_runtime_root is not None
        ):
            try:
                self.lineReady.emit(
                    "Preparing standalone Python 3.13.15; the first download is "
                    "about 20Ã¢â‚¬â€œ35 MB."
                )
                executable = ensure_bootstrap_python(
                    self._plan.bootstrap_artifact,
                    self._plan.bootstrap_runtime_root,
                    self.lineReady.emit,
                )
            except (OSError, RuntimeError) as exc:
                self.finishedInstall.emit(False, str(exc))
                return
            cmd = [str(executable), *self._plan.bootstrap_arguments]
        elif self._plan.command is not None:
            cmd = list(self._plan.command)
        else:
            self.finishedInstall.emit(
                False, self._plan.error or "No AI installation plan is available."
            )
            return

        if self._plan.lyrics_aligner_root is not None:
            try:
                ensure_lyrics_aligner(self._plan.lyrics_aligner_root, self.lineReady.emit)
            except (OSError, RuntimeError) as exc:
                self.finishedInstall.emit(False, str(exc))
                return

        self.lineReady.emit(f"Running: {' '.join(cmd)}")
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            self.finishedInstall.emit(
                False, f"Could not start AI dependency installation: {exc}"
            )
            return

        assert process.stdout is not None
        for line in process.stdout:
            self.lineReady.emit(line.rstrip())
        exit_code = process.wait()
        if exit_code == 0:
            self.finishedInstall.emit(True, "AI dependencies installed successfully.")
            return
        self.finishedInstall.emit(
            False, f"pip install failed with exit code {exit_code}."
        )


class AIDependenciesDialog(QDialog):
    def __init__(
        self, missing_packages: list[str], check_message: str, parent=None
    ) -> None:
        super().__init__(parent)
        self._missing_packages = list(missing_packages)
        self._check_message = (check_message or "").strip()
        self._worker: _InstallAIDependenciesWorker | None = None
        self._install_succeeded = False
        self._install_plan = resolve_ai_install_plan(self._missing_packages)

        self.setWindowTitle("AI Sync setup")
        self.resize(760, 520)

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=SPACE_4, spacing=SPACE_3)

        title = QLabel("AI dependencies are missing")
        title.setObjectName("DialogTitle")
        root.addWidget(title)

        if (
            self._install_plan.bootstrap_artifact is not None
            and self._install_plan.command is None
        ):
            summary_text = (
                "PyLrcGet will set up its pinned Python runtime automatically on "
                "the first install, then install the required AI packages. "
                "After installation, use Retry AI Sync to continue."
            )
        elif self._install_plan.can_install:
            summary_text = (
                "You can install required packages directly from this dialog. "
                "After installation, use Retry AI Sync to continue."
            )
        else:
            summary_text = (
                "Automatic install is unavailable for this runtime. "
                "Use the instructions below, then reopen AI Sync."
            )
        summary = QLabel(summary_text)
        summary.setWordWrap(True)
        summary.setObjectName("DialogSubtle")
        root.addWidget(summary)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.details.setPlainText(self._build_intro_text())
        root.addWidget(self.details, 1)

        button_row = QHBoxLayout()
        set_layout_spacing(button_row, spacing=SPACE_2)
        self.btn_install = QPushButton("Install Missing Dependencies")
        self.btn_copy = QPushButton("Copy Install Command")
        self.btn_retry = QPushButton("Retry AI Sync")
        self.btn_close = QPushButton("Close")
        set_button_role(self.btn_install, "primary")
        set_button_role(self.btn_copy, "ghost")
        set_button_role(self.btn_retry, "primary")
        set_button_role(self.btn_close, "secondary")
        self.btn_retry.setEnabled(False)
        self.btn_install.setEnabled(self._install_plan.can_install)
        self.btn_copy.setEnabled(bool(self._install_command_text()))
        if not self._install_command_text():
            self.btn_copy.setToolTip(
                "A command is available after the automatic setup downloads are prepared."
            )

        self.btn_install.clicked.connect(self._start_install)
        self.btn_copy.clicked.connect(self._copy_install_command)
        self.btn_retry.clicked.connect(self.accept)
        self.btn_close.clicked.connect(self.reject)

        button_row.addWidget(self.btn_install)
        button_row.addWidget(self.btn_copy)
        button_row.addStretch(1)
        button_row.addWidget(self.btn_retry)
        button_row.addWidget(self.btn_close)
        root.addLayout(button_row)

    def _build_intro_text(self) -> str:
        command = self._install_command_text()
        lines = [
            self._check_message or "Missing dependencies were detected.",
            "",
            f"Missing packages: {', '.join(self._missing_packages)}",
            "",
            f"Python runtime used by app:\n{sys.executable}",
        ]
        if (
            self._install_plan.bootstrap_artifact is not None
            and self._install_plan.command is None
        ):
            lines.extend(
                [
                    "",
                    (
                        "On first install, PyLrcGet will download and verify Python "
                        "3.13.15 for this device. The bootstrap is cached locally; AI "
                        "packages are then installed into the app's isolated runtime."
                    ),
                ]
            )
        elif command:
            lines.extend(["", "Install command:", command])
        elif self._install_plan.error:
            lines.extend(["", self._install_plan.error])
        return "\n".join(lines)

    def _install_command_text(self) -> str:
        aligner_root = self._install_plan.lyrics_aligner_root
        if aligner_root is not None and not (aligner_root / "model_parameters.pth").is_file():
            return ""
        if not self._install_plan.command:
            return ""
        return " ".join(self._install_plan.command)

    def _copy_install_command(self) -> None:
        command = self._install_command_text()
        if not command:
            return
        QGuiApplication.clipboard().setText(command)
        self.details.append("\nInstall command copied to clipboard.")

    def _start_install(self) -> None:
        if not self._missing_packages:
            self.details.append("\nNo missing AI dependencies were detected.")
            self.btn_retry.setEnabled(True)
            return
        if not self._install_plan.can_install:
            if self._install_plan.error:
                self.details.append(f"\n{self._install_plan.error}")
            return
        if self._worker is not None and self._worker.isRunning():
            return

        self._install_succeeded = False
        self.btn_install.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.btn_retry.setEnabled(False)
        self.btn_close.setEnabled(False)

        worker = _InstallAIDependenciesWorker(self._install_plan, self)
        worker.lineReady.connect(self._append_line)
        worker.finishedInstall.connect(self._on_install_finished)
        self._worker = worker
        worker.start()

    def _append_line(self, line: str) -> None:
        if not line:
            return
        self.details.append(line)

    def _on_install_finished(self, ok: bool, message: str) -> None:
        if self._install_plan.bootstrap_artifact is not None:
            refreshed_plan = resolve_ai_install_plan(self._missing_packages)
            if refreshed_plan.command is not None:
                self._install_plan = refreshed_plan
        self.details.append(f"\n{message}")
        self.btn_install.setEnabled(self._install_plan.can_install)
        self.btn_copy.setEnabled(bool(self._install_command_text()))
        self.btn_copy.setToolTip(
            "A command is available after the automatic setup downloads are prepared."
            if not self._install_command_text()
            else ""
        )
        self.btn_close.setEnabled(True)

        if ok and not get_missing_ai_dependencies():
            self._install_succeeded = True
            self.details.append(
                "Dependencies are now available. You can retry AI Sync."
            )
            self.btn_retry.setEnabled(True)
            return

        if ok:
            self.details.append(
                "Install completed, but dependencies still appear missing in this runtime. "
                "Restart the app and retry."
            )
        else:
            logger.warning("AI dependency install failed.")
        self.btn_retry.setEnabled(False)

    def closeEvent(self, event) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)
