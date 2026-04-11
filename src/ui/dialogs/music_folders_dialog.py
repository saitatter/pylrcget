from __future__ import annotations

from dataclasses import replace
import os
import re

from PySide6.QtCore import Qt
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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QFontDatabase

from core.lyrics_sidecar import DEFAULT_LYRICS_FILE_PATTERN
from db.database import get_config, get_directories, set_config, set_directories
from db.models import Config
from library.scan_library import preview_audio_path_exclusions
from ui.services.download_modes import missing_lyrics_detail, missing_lyrics_summary
from ui.theme_tokens import get_available_themes


class MusicFoldersDialog(QDialog):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(700, 700)
        self.app_state = app_state
        self._last_browse_dir = os.path.expanduser("~")
        self.directories_changed = False

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("SettingsTabs")
        layout.addWidget(self.tabs, 1)

        library_tab = QWidget()
        library_layout = QVBoxLayout(library_tab)

        lyrics_tab = QWidget()
        lyrics_tab_layout = QVBoxLayout(lyrics_tab)

        appearance_tab = QWidget()
        appearance_layout_root = QVBoxLayout(appearance_tab)

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
        library_layout.addWidget(folders_box)

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
        library_layout.addWidget(scan_box)
        library_layout.addStretch(1)

        appearance_box = QGroupBox("Appearance")
        appearance_layout = QGridLayout(appearance_box)
        self.theme_combo = QComboBox()
        for theme_key, theme_name in get_available_themes():
            self.theme_combo.addItem(theme_name, theme_key)
        appearance_layout.addWidget(QLabel("Theme"), 0, 0)
        appearance_layout.addWidget(self.theme_combo, 0, 1)
        appearance_layout_root.addWidget(appearance_box)
        appearance_layout_root.addStretch(1)

        lyrics_box = QGroupBox("Lyrics Export")
        lyrics_layout = QGridLayout(lyrics_box)

        self.save_sidecars_chk = QCheckBox("Save lyrics files")
        self.save_sidecars_chk.setChecked(True)
        lyrics_layout.addWidget(self.save_sidecars_chk, 0, 0, 1, 4)

        self.download_mode_combo = QComboBox()
        self.download_mode_combo.addItem("Prefer synced, fallback to plain", "prefer_synced")
        self.download_mode_combo.addItem("Synced only", "synced_only")
        self.download_mode_combo.addItem("Plain only", "plain_only")
        lyrics_layout.addWidget(QLabel("Download mode"), 1, 0)
        lyrics_layout.addWidget(self.download_mode_combo, 1, 1, 1, 3)
        self.download_mode_hint_label = QLabel("")
        self.download_mode_hint_label.setObjectName("SettingsValidationHint")
        self.download_mode_hint_label.setWordWrap(True)
        lyrics_layout.addWidget(self.download_mode_hint_label, 2, 0, 1, 4)

        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Leave empty to save next to the audio file")
        self.browse_output_btn = QPushButton("Browse")
        self.clear_output_btn = QPushButton("Use Track Folder")

        lyrics_layout.addWidget(QLabel("Download directory"), 3, 0)
        lyrics_layout.addWidget(self.output_dir_edit, 3, 1)
        lyrics_layout.addWidget(self.browse_output_btn, 3, 2)
        lyrics_layout.addWidget(self.clear_output_btn, 3, 3)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText(DEFAULT_LYRICS_FILE_PATTERN)
        lyrics_layout.addWidget(QLabel("Filename pattern"), 4, 0)
        lyrics_layout.addWidget(self.pattern_edit, 4, 1, 1, 3)

        self.pattern_preview_label = QLabel("")
        self.pattern_preview_label.setObjectName("SettingsValidationHint")
        self.pattern_preview_label.setWordWrap(True)
        self.pattern_preview_label.setTextInteractionFlags(
            self.pattern_preview_label.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.pattern_preview_label.setFont(mono_font)
        lyrics_layout.addWidget(self.pattern_preview_label, 5, 0, 1, 4)

        hint = QLabel(
            "Available placeholders: {artist}, {title}, {album}, {track}. "
            "Extensions are added automatically as .lrc and .txt."
        )
        hint.setWordWrap(True)
        lyrics_layout.addWidget(hint, 6, 0, 1, 4)
        lyrics_tab_layout.addWidget(lyrics_box)
        lyrics_tab_layout.addStretch(1)

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
        lyrics_tab_layout.addWidget(embed_box)
        lyrics_tab_layout.addStretch(1)

        self.tabs.addTab(library_tab, "Library")
        self.tabs.addTab(lyrics_tab, "Lyrics")
        self.tabs.addTab(appearance_tab, "Appearance")

        self.save_btn = QPushButton("Save")
        layout.addWidget(self.save_btn)

        self._load()

        self.add_btn.clicked.connect(self.add_folder)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.save_btn.clicked.connect(self.save)
        self.browse_output_btn.clicked.connect(self._browse_output_dir)
        self.clear_output_btn.clicked.connect(lambda: self.output_dir_edit.setText(""))
        self.save_sidecars_chk.toggled.connect(self._update_export_fields_enabled)
        self.pattern_edit.textChanged.connect(self._update_pattern_preview)
        self.output_dir_edit.textChanged.connect(self._update_pattern_preview)
        self.download_mode_combo.currentIndexChanged.connect(self._update_download_mode_hint)
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
        mode_index = self.download_mode_combo.findData(config.download_lyrics_mode or "prefer_synced")
        self.download_mode_combo.setCurrentIndex(max(0, mode_index))
        self.output_dir_edit.setText(config.lyrics_output_dir)
        self.pattern_edit.setText(config.lyrics_file_pattern or DEFAULT_LYRICS_FILE_PATTERN)
        self.embed_chk.setChecked(config.try_embed_lyrics)
        self.reaction_delay_spin.setValue(int(config.reaction_delay_ms or 0))
        self.excluded_paths_edit.setPlainText(config.scan_excluded_paths)
        self.excluded_patterns_edit.setPlainText(config.scan_excluded_patterns)
        directories = get_directories(self.app_state.db)
        if config.lyrics_output_dir and os.path.isdir(config.lyrics_output_dir):
            self._last_browse_dir = config.lyrics_output_dir
        elif directories:
            first_directory = directories[0]
            if os.path.isdir(first_directory):
                self._last_browse_dir = first_directory
        self._update_export_fields_enabled()
        self._update_download_mode_hint()
        self._update_pattern_preview()
        self._validate_regex_patterns()

    def add_folder(self):
        path = self._pick_directory("Select Music Folder")
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
        path = self._pick_directory("Select Lyrics Download Directory", self.output_dir_edit.text().strip())
        if path:
            self.output_dir_edit.setText(path)

    def _add_excluded_path(self):
        path = self._pick_directory("Select Excluded Folder")
        if not path:
            return

        self._append_excluded_path(path)

    def _add_excluded_file(self):
        path = self._pick_file("Select Excluded File")
        if not path:
            return
        self._append_excluded_path(path)

    def _dialog_start_dir(self, preferred: str = "") -> str:
        preferred = (preferred or "").strip()
        if preferred:
            if os.path.isdir(preferred):
                return preferred
            parent = os.path.dirname(preferred)
            if parent and os.path.isdir(parent):
                return parent
        if os.path.isdir(self._last_browse_dir):
            return self._last_browse_dir
        return os.path.expanduser("~")

    def _pick_directory(self, title: str, preferred: str = "") -> str:
        dialog = QFileDialog(self, title, self._dialog_start_dir(preferred))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.DontUseCustomDirectoryIcons, True)
        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                path = selected[0]
                self._last_browse_dir = path
                return path
        return ""

    def _pick_file(self, title: str, preferred: str = "") -> str:
        dialog = QFileDialog(self, title, self._dialog_start_dir(preferred))
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.DontUseCustomDirectoryIcons, True)
        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                path = selected[0]
                self._last_browse_dir = os.path.dirname(path) or self._last_browse_dir
                return path
        return ""

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
        self._update_pattern_preview()

    def _update_download_mode_hint(self) -> None:
        mode = str(self.download_mode_combo.currentData() or "prefer_synced")
        self.download_mode_hint_label.setText(
            f"{missing_lyrics_summary(mode)} {missing_lyrics_detail(mode)}"
        )

    def _safe_filename_component(self, value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (value or "").strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" .")

    def _render_pattern_preview(self) -> tuple[str, bool]:
        pattern = (self.pattern_edit.text().strip() or DEFAULT_LYRICS_FILE_PATTERN)
        values = {
            "artist": self._safe_filename_component("Radiohead"),
            "title": self._safe_filename_component("Everything In Its Right Place"),
            "album": self._safe_filename_component("Kid A"),
            "track": self._safe_filename_component("01"),
        }
        used_fallback = False
        try:
            rendered = pattern.format(**values).strip()
        except Exception:
            rendered = ""
            used_fallback = True
        rendered = self._safe_filename_component(rendered)
        if not rendered:
            rendered = "Radiohead - Everything In Its Right Place"
            used_fallback = True

        output_dir = self.output_dir_edit.text().strip()
        if output_dir:
            return os.path.join(output_dir, rendered) + " (.lrc / .txt)", used_fallback
        return rendered + " (.lrc / .txt next to the audio file)", used_fallback

    def _update_pattern_preview(self) -> None:
        if not self.save_sidecars_chk.isChecked():
            self.pattern_preview_label.setProperty("validationState", "")
            self.pattern_preview_label.setText("Preview: lyric files will be saved next to the audio file when sidecar saving is disabled.")
        else:
            preview, used_fallback = self._render_pattern_preview()
            self.pattern_preview_label.setProperty("validationState", "error" if used_fallback else "success")
            if used_fallback:
                self.pattern_preview_label.setText(
                    "Preview (fallback used due to invalid or empty result):\n"
                    f"{preview}"
                )
            else:
                self.pattern_preview_label.setText(f"Preview:\n{preview}")

        self.pattern_preview_label.style().unpolish(self.pattern_preview_label)
        self.pattern_preview_label.style().polish(self.pattern_preview_label)
        self.pattern_preview_label.update()

    def save(self):
        previous_folders = get_directories(self.app_state.db)
        folders = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        if not folders:
            QMessageBox.warning(self, "No folders", "Please add at least one music folder.")
            return

        config = get_config(self.app_state.db)
        new_config = replace(
            config,
            theme_mode=str(self.theme_combo.currentData() or "auto"),
            save_lyrics_sidecars=self.save_sidecars_chk.isChecked(),
            download_lyrics_mode=str(self.download_mode_combo.currentData() or "prefer_synced"),
            try_embed_lyrics=self.embed_chk.isChecked(),
            lyrics_output_dir=self.output_dir_edit.text().strip(),
            lyrics_file_pattern=self.pattern_edit.text().strip() or DEFAULT_LYRICS_FILE_PATTERN,
            scan_excluded_paths=self.excluded_paths_edit.toPlainText().strip(),
            scan_excluded_patterns=self.excluded_patterns_edit.toPlainText().strip(),
            reaction_delay_ms=int(self.reaction_delay_spin.value()),
        )

        set_directories(self.app_state.db, folders)
        set_config(self.app_state.db, new_config)
        self.directories_changed = folders != previous_folders
        self.accept()
