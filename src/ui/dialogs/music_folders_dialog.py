from __future__ import annotations

from dataclasses import replace
import re

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from core.lyrics_sidecar import DEFAULT_LYRICS_FILE_PATTERN
from db.database import get_config, get_directories, set_config, set_directories
from db.models import Config
from library.scan_library import preview_audio_path_exclusions
from ui.theme_tokens import get_available_themes


class MusicFoldersDialog(QDialog):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(700, 700)
        self.app_state = app_state

        layout = QVBoxLayout(self)

        folders_box = QGroupBox("Music Folders")
        folders_layout = QVBoxLayout(folders_box)
        self.list_widget = QListWidget()
        folders_layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Folder")
        self.remove_btn = QPushButton("Remove Selected")
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        folders_layout.addLayout(btn_layout)
        layout.addWidget(folders_box)

        appearance_box = QGroupBox("Appearance")
        appearance_layout = QGridLayout(appearance_box)
        self.theme_combo = QComboBox()
        for theme_key, theme_name in get_available_themes():
            self.theme_combo.addItem(theme_name, theme_key)
        appearance_layout.addWidget(QLabel("Theme"), 0, 0)
        appearance_layout.addWidget(self.theme_combo, 0, 1)
        layout.addWidget(appearance_box)

        lyrics_box = QGroupBox("Lyrics Export")
        lyrics_layout = QGridLayout(lyrics_box)

        self.save_sidecars_chk = QCheckBox("Save lyrics files")
        self.save_sidecars_chk.setChecked(True)
        lyrics_layout.addWidget(self.save_sidecars_chk, 0, 0, 1, 4)

        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Leave empty to save next to the audio file")
        self.browse_output_btn = QPushButton("Browse")
        self.clear_output_btn = QPushButton("Use Track Folder")

        lyrics_layout.addWidget(QLabel("Download directory"), 1, 0)
        lyrics_layout.addWidget(self.output_dir_edit, 1, 1)
        lyrics_layout.addWidget(self.browse_output_btn, 1, 2)
        lyrics_layout.addWidget(self.clear_output_btn, 1, 3)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText(DEFAULT_LYRICS_FILE_PATTERN)
        lyrics_layout.addWidget(QLabel("Filename pattern"), 2, 0)
        lyrics_layout.addWidget(self.pattern_edit, 2, 1, 1, 3)

        hint = QLabel(
            "Available placeholders: {artist}, {title}, {album}, {track}. "
            "Extensions are added automatically as .lrc and .txt."
        )
        hint.setWordWrap(True)
        lyrics_layout.addWidget(hint, 3, 0, 1, 4)

        layout.addWidget(lyrics_box)

        embed_box = QGroupBox("Audio File")
        embed_layout = QGridLayout(embed_box)
        self.embed_chk = QCheckBox("Embed lyrics into the audio file")
        self.embed_chk.setChecked(True)
        embed_layout.addWidget(self.embed_chk, 0, 0, 1, 2)

        self.reaction_delay_spin = QSpinBox()
        self.reaction_delay_spin.setRange(-2000, 2000)
        self.reaction_delay_spin.setSingleStep(10)
        self.reaction_delay_spin.setSuffix(" ms")
        embed_layout.addWidget(QLabel("Reaction delay"), 1, 0)
        embed_layout.addWidget(self.reaction_delay_spin, 1, 1)

        reaction_hint = QLabel("Negative values stamp earlier. Positive values stamp later.")
        reaction_hint.setWordWrap(True)
        embed_layout.addWidget(reaction_hint, 2, 0, 1, 2)
        layout.addWidget(embed_box)

        scan_box = QGroupBox("Library Scan")
        scan_layout = QGridLayout(scan_box)

        self.excluded_paths_edit = QTextEdit()
        self.excluded_paths_edit.setPlaceholderText(
            "One path per line.\n"
            "Example:\n"
            "D:\\Music\\Podcasts\n"
            "D:\\Music\\Temporary"
        )
        self.add_excluded_path_btn = QPushButton("Add Excluded Path")
        self.add_excluded_file_btn = QPushButton("Add Excluded File")
        self.remove_excluded_path_btn = QPushButton("Remove Selected Lines")
        self.test_exclusions_btn = QPushButton("Test Exclusions")
        self.excluded_patterns_edit = QTextEdit()
        self.excluded_patterns_edit.setPlaceholderText(
            "One regex per line.\n"
            "Examples:\n"
            "\\\\Podcasts\\\\\n"
            "sample|demo\n"
            "\\.(cue|log)$"
        )

        scan_layout.addWidget(QLabel("Excluded paths"), 0, 0)
        scan_layout.addWidget(self.excluded_paths_edit, 1, 0)
        excluded_paths_btn_row = QHBoxLayout()
        excluded_paths_btn_row.addWidget(self.add_excluded_path_btn)
        excluded_paths_btn_row.addWidget(self.add_excluded_file_btn)
        excluded_paths_btn_row.addWidget(self.remove_excluded_path_btn)
        excluded_paths_btn_row.addWidget(self.test_exclusions_btn)
        excluded_paths_btn_row.addStretch(1)
        scan_layout.addLayout(excluded_paths_btn_row, 2, 0)
        scan_layout.addWidget(QLabel("Excluded regex patterns"), 0, 1)
        scan_layout.addWidget(self.excluded_patterns_edit, 1, 1)
        self.regex_validation_label = QLabel("")
        self.regex_validation_label.setObjectName("SettingsValidationHint")
        self.regex_validation_label.setVisible(False)
        scan_layout.addWidget(self.regex_validation_label, 2, 1)

        scan_hint = QLabel(
            "Paths skip exact files or entire folders. Regex patterns are matched against the full file path."
        )
        scan_hint.setWordWrap(True)
        scan_layout.addWidget(scan_hint, 3, 0, 1, 2)
        layout.addWidget(scan_box)

        self.save_btn = QPushButton("Save")
        layout.addWidget(self.save_btn)

        self._load()

        self.add_btn.clicked.connect(self.add_folder)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.save_btn.clicked.connect(self.save)
        self.browse_output_btn.clicked.connect(self._browse_output_dir)
        self.clear_output_btn.clicked.connect(lambda: self.output_dir_edit.setText(""))
        self.save_sidecars_chk.toggled.connect(self._update_export_fields_enabled)
        self.add_excluded_path_btn.clicked.connect(self._add_excluded_path)
        self.add_excluded_file_btn.clicked.connect(self._add_excluded_file)
        self.remove_excluded_path_btn.clicked.connect(self._remove_selected_excluded_path_lines)
        self.test_exclusions_btn.clicked.connect(self._test_exclusions)
        self.excluded_patterns_edit.textChanged.connect(self._validate_regex_patterns)

    def _load(self):
        self.list_widget.clear()
        for directory in get_directories(self.app_state.db):
            self.list_widget.addItem(directory)

        config = get_config(self.app_state.db)
        theme_idx = self.theme_combo.findData(config.theme_mode or "auto")
        self.theme_combo.setCurrentIndex(max(0, theme_idx))
        self.save_sidecars_chk.setChecked(config.save_lyrics_sidecars)
        self.output_dir_edit.setText(config.lyrics_output_dir)
        self.pattern_edit.setText(config.lyrics_file_pattern or DEFAULT_LYRICS_FILE_PATTERN)
        self.embed_chk.setChecked(config.try_embed_lyrics)
        self.reaction_delay_spin.setValue(int(config.reaction_delay_ms or 0))
        self.excluded_paths_edit.setPlainText(config.scan_excluded_paths)
        self.excluded_patterns_edit.setPlainText(config.scan_excluded_patterns)
        self._update_export_fields_enabled()
        self._validate_regex_patterns()

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Music Folder")
        if not path:
            return

        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).text() == path:
                return

        self.list_widget.addItem(path)

    def remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Lyrics Download Directory")
        if path:
            self.output_dir_edit.setText(path)

    def _add_excluded_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Excluded Folder")
        if not path:
            return

        self._append_excluded_path(path)

    def _add_excluded_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Excluded File")
        if not path:
            return
        self._append_excluded_path(path)

    def _append_excluded_path(self, path: str):
        existing = [line.strip() for line in self.excluded_paths_edit.toPlainText().splitlines() if line.strip()]
        if path not in existing:
            existing.append(path)
            self.excluded_paths_edit.setPlainText("\n".join(existing))

    def _remove_selected_excluded_path_lines(self):
        cursor = self.excluded_paths_edit.textCursor()
        if not cursor.hasSelection():
            return

        start_block = self.excluded_paths_edit.document().findBlock(cursor.selectionStart()).blockNumber()
        end_block = self.excluded_paths_edit.document().findBlock(max(cursor.selectionEnd() - 1, cursor.selectionStart())).blockNumber()

        lines = self.excluded_paths_edit.toPlainText().splitlines()
        kept = [line for idx, line in enumerate(lines) if idx < start_block or idx > end_block]
        self.excluded_paths_edit.setPlainText("\n".join(kept))

    def _validate_regex_patterns(self):
        invalid: list[str] = []
        for line in self.excluded_patterns_edit.toPlainText().splitlines():
            pattern = line.strip()
            if not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error as exc:
                invalid.append(f"{pattern}: {exc}")

        if invalid:
            self.regex_validation_label.setProperty("validationState", "error")
            self.regex_validation_label.setText("Invalid regex:\n" + "\n".join(invalid[:3]))
            self.regex_validation_label.setVisible(True)
            self.save_btn.setEnabled(False)
        else:
            self.regex_validation_label.setProperty("validationState", "success")
            self.regex_validation_label.setText("Regex patterns look valid.")
            self.regex_validation_label.setVisible(bool(self.excluded_patterns_edit.toPlainText().strip()))
            self.save_btn.setEnabled(True)

        self.regex_validation_label.style().unpolish(self.regex_validation_label)
        self.regex_validation_label.style().polish(self.regex_validation_label)
        self.regex_validation_label.update()

    def _test_exclusions(self):
        self._validate_regex_patterns()
        if not self.save_btn.isEnabled():
            QMessageBox.warning(
                self,
                "Invalid regex",
                "Please fix the invalid regex patterns before testing exclusions.",
            )
            return

        folders = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        if not folders:
            QMessageBox.warning(self, "No folders", "Please add at least one music folder.")
            return

        included, excluded = preview_audio_path_exclusions(
            folders,
            excluded_paths=self.excluded_paths_edit.toPlainText().strip(),
            excluded_patterns=self.excluded_patterns_edit.toPlainText().strip(),
        )

        total = len(included) + len(excluded)
        lines = [
            f"Audio files found: {total}",
            f"Included in scan: {len(included)}",
            f"Excluded from scan: {len(excluded)}",
        ]

        if excluded:
            sample_count = min(10, len(excluded))
            lines.append("")
            lines.append(f"Examples of excluded files ({sample_count} shown):")
            lines.extend(excluded[:sample_count])
        else:
            lines.append("")
            lines.append("No audio files are excluded by the current rules.")

        QMessageBox.information(self, "Exclusion Preview", "\n".join(lines))

    def _update_export_fields_enabled(self):
        enabled = self.save_sidecars_chk.isChecked()
        self.output_dir_edit.setEnabled(enabled)
        self.pattern_edit.setEnabled(enabled)
        self.browse_output_btn.setEnabled(enabled)
        self.clear_output_btn.setEnabled(enabled)

    def save(self):
        folders = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        if not folders:
            QMessageBox.warning(self, "No folders", "Please add at least one music folder.")
            return

        config = get_config(self.app_state.db)
        new_config = replace(
            config,
            theme_mode=str(self.theme_combo.currentData() or "auto"),
            save_lyrics_sidecars=self.save_sidecars_chk.isChecked(),
            try_embed_lyrics=self.embed_chk.isChecked(),
            lyrics_output_dir=self.output_dir_edit.text().strip(),
            lyrics_file_pattern=self.pattern_edit.text().strip() or DEFAULT_LYRICS_FILE_PATTERN,
            scan_excluded_paths=self.excluded_paths_edit.toPlainText().strip(),
            scan_excluded_patterns=self.excluded_patterns_edit.toPlainText().strip(),
            reaction_delay_ms=int(self.reaction_delay_spin.value()),
        )

        set_directories(self.app_state.db, folders)
        set_config(self.app_state.db, new_config)
        self.accept()
