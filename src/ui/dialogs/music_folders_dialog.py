from __future__ import annotations

import json
import os
import re
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.lyrics_sidecar import DEFAULT_LYRICS_FILE_PATTERN
from db.database import get_config, get_directories, set_config, set_directories
from library.scan_library import preview_audio_path_exclusions
from ui.ai_sync_settings import (
    AI_SYNC_DEVICE_OPTIONS,
    AI_SYNC_LANGUAGE_OPTIONS,
    load_ai_sync_settings,
    merge_ai_sync_settings,
)
from ui.hotkeys import (
    HOTKEY_SPECS,
    find_duplicate_hotkeys,
    parse_hotkey_bindings,
    serialize_hotkey_bindings,
)
from ui.services.download_modes import missing_lyrics_detail, missing_lyrics_summary
from ui.services.logging_preferences import LOG_VERBOSITY_CHOICES
from ui.theme_tokens import get_available_themes


class MusicFoldersDialog(QDialog):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(760, 760)
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
        self.lyrics_sections_tabs = QTabWidget()
        lyrics_tab_layout.addWidget(self.lyrics_sections_tabs)

        lyrics_download_tab = QWidget()
        lyrics_download_layout = QVBoxLayout(lyrics_download_tab)

        lyrics_files_tab = QWidget()
        lyrics_files_layout = QVBoxLayout(lyrics_files_tab)

        lyrics_embed_tab = QWidget()
        lyrics_embed_layout = QVBoxLayout(lyrics_embed_tab)

        ai_sync_tab = QWidget()
        ai_sync_tab_layout = QVBoxLayout(ai_sync_tab)

        appearance_tab = QWidget()
        appearance_layout_root = QVBoxLayout(appearance_tab)

        shortcuts_tab = QWidget()
        shortcuts_tab_layout = QVBoxLayout(shortcuts_tab)
        self.shortcuts_scroll = QScrollArea()
        self.shortcuts_scroll.setWidgetResizable(True)
        self.shortcuts_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        shortcuts_content = QWidget()
        shortcuts_layout_root = QVBoxLayout(shortcuts_content)
        shortcuts_tab_layout.addWidget(self.shortcuts_scroll)
        self.shortcuts_scroll.setWidget(shortcuts_content)

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
        self._set_text_edit_visible_rows(self.excluded_paths_edit, 5)
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
        self._set_text_edit_visible_rows(self.excluded_patterns_edit, 5)

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
        scan_layout.setColumnStretch(0, 3)
        scan_layout.setColumnStretch(1, 1)
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

        nav_options_box = QGroupBox("Library Grouping & Indexing")
        nav_options_layout = QVBoxLayout(nav_options_box)
        self.ignore_sort_articles_chk = QCheckBox("Ignore lead articles (The, A, An) when indexing/sorting names")
        nav_options_layout.addWidget(self.ignore_sort_articles_chk)
        library_layout.addWidget(nav_options_box)

        library_layout.addStretch(1)

        appearance_box = QGroupBox("Appearance")
        appearance_layout = QGridLayout(appearance_box)
        self.theme_combo = QComboBox()
        for theme_key, theme_name in get_available_themes():
            self.theme_combo.addItem(theme_name, theme_key)
        self.ui_scale_combo = QComboBox()
        for percent in (90, 100, 110, 125):
            self.ui_scale_combo.addItem(f"{percent}%", percent)
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItem("Small", "small")
        self.font_size_combo.addItem("Normal", "normal")
        self.font_size_combo.addItem("Large", "large")
        self.album_art_combo = QComboBox()
        self.album_art_combo.addItem("Show", True)
        self.album_art_combo.addItem("Hide", False)
        self.startup_view_combo = QComboBox()
        self.startup_view_combo.addItem("Remember last view", "remember_last")
        self.startup_view_combo.addItem("Tracks", "tracks")
        self.startup_view_combo.addItem("Albums", "albums")
        self.startup_view_combo.addItem("Artists", "artists")
        self.startup_view_combo.addItem("Album Artists", "album_artists")
        self.startup_view_combo.addItem("My LRCLIB", "my_lrclib")
        appearance_layout.addWidget(QLabel("Theme"), 0, 0)
        appearance_layout.addWidget(self.theme_combo, 0, 1)
        appearance_layout.addWidget(QLabel("UI scale"), 1, 0)
        appearance_layout.addWidget(self.ui_scale_combo, 1, 1)
        appearance_layout.addWidget(QLabel("Font size"), 2, 0)
        appearance_layout.addWidget(self.font_size_combo, 2, 1)
        appearance_layout.addWidget(QLabel("Album art"), 3, 0)
        appearance_layout.addWidget(self.album_art_combo, 3, 1)
        appearance_layout.addWidget(QLabel("Startup view"), 4, 0)
        appearance_layout.addWidget(self.startup_view_combo, 4, 1)
        startup_hint = QLabel("Startup view is applied the next time the app opens.")
        startup_hint.setWordWrap(True)
        appearance_layout.addWidget(startup_hint, 5, 0, 1, 2)
        appearance_layout_root.addWidget(appearance_box)
        appearance_layout_root.addStretch(1)

        self.shortcut_edits: dict[str, QKeySequenceEdit] = {}
        self.shortcut_enabled_checks: dict[str, QCheckBox] = {}

        global_shortcuts_box = QGroupBox("App Shortcuts")
        global_shortcuts_layout = QGridLayout(global_shortcuts_box)
        self._build_shortcut_controls(global_shortcuts_layout, group="global", columns=2)

        shortcuts_box = QGroupBox("Lyrics Sync Shortcuts")
        shortcuts_layout = QGridLayout(shortcuts_box)
        self._build_shortcut_controls(shortcuts_layout, group="lyrics")

        self.shortcuts_reset_btn = QPushButton("Reset All Defaults")
        self.shortcuts_reset_btn.setMaximumWidth(180)
        shortcuts_layout_root.addWidget(global_shortcuts_box)
        shortcuts_layout_root.addWidget(shortcuts_box)
        shortcuts_actions_layout = QHBoxLayout()
        shortcuts_actions_layout.addStretch(1)
        shortcuts_actions_layout.addWidget(self.shortcuts_reset_btn)
        shortcuts_layout_root.addLayout(shortcuts_actions_layout)
        shortcuts_hint = QLabel(
            "Disable any shortcut explicitly, or leave it enabled and assign a custom key combination. "
            "Hover shortcut labels to see the action details and default keys. Changes apply immediately after saving."
        )
        shortcuts_hint.setWordWrap(True)
        shortcuts_layout_root.addWidget(shortcuts_hint)
        shortcuts_layout_root.addStretch(1)

        download_box = QGroupBox("Lyrics Download")
        download_layout = QGridLayout(download_box)
        self.download_mode_combo = QComboBox()
        self.download_mode_combo.addItem("Prefer synced, fallback to plain", "prefer_synced")
        self.download_mode_combo.addItem("Synced only", "synced_only")
        self.download_mode_combo.addItem("Plain only", "plain_only")
        download_layout.addWidget(QLabel("Download mode"), 0, 0)
        download_layout.addWidget(self.download_mode_combo, 0, 1, 1, 3)
        self.download_mode_hint_label = QLabel("")
        self.download_mode_hint_label.setObjectName("SettingsValidationHint")
        self.download_mode_hint_label.setWordWrap(True)
        download_layout.addWidget(self.download_mode_hint_label, 1, 0, 1, 4)
        lyrics_download_layout.addWidget(download_box)

        lyrics_box = QGroupBox("Lyrics Export")
        lyrics_layout = QGridLayout(lyrics_box)

        self.save_sidecars_chk = QCheckBox("Save lyrics files")
        self.save_sidecars_chk.setChecked(True)
        lyrics_layout.addWidget(self.save_sidecars_chk, 0, 0, 1, 4)

        self.sidecar_format_combo = QComboBox()
        self._populate_lyrics_format_combo(self.sidecar_format_combo)
        lyrics_layout.addWidget(QLabel("File contents"), 1, 0)
        lyrics_layout.addWidget(self.sidecar_format_combo, 1, 1, 1, 3)

        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Leave empty to save next to the audio file")
        self.browse_output_btn = QPushButton("Browse")
        self.clear_output_btn = QPushButton("Use Track Folder")

        lyrics_layout.addWidget(QLabel("Download directory"), 2, 0)
        lyrics_layout.addWidget(self.output_dir_edit, 2, 1)
        lyrics_layout.addWidget(self.browse_output_btn, 2, 2)
        lyrics_layout.addWidget(self.clear_output_btn, 2, 3)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText(DEFAULT_LYRICS_FILE_PATTERN)
        lyrics_layout.addWidget(QLabel("Filename pattern"), 3, 0)
        lyrics_layout.addWidget(self.pattern_edit, 3, 1, 1, 3)

        self.pattern_preview_label = QLabel("")
        self.pattern_preview_label.setObjectName("SettingsValidationHint")
        self.pattern_preview_label.setWordWrap(True)
        self.pattern_preview_label.setTextInteractionFlags(
            self.pattern_preview_label.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        mono_font = QFont("Consolas", 9)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        self.pattern_preview_label.setFont(mono_font)
        lyrics_layout.addWidget(self.pattern_preview_label, 4, 0, 1, 4)

        hint = QLabel(
            "Available placeholders: {filename}, {artist}, {title}, {album}, {track}. "
            "Extensions are added automatically based on the selected file contents. "
            "Leave the pattern empty to use the audio filename."
        )
        hint.setWordWrap(True)
        lyrics_layout.addWidget(hint, 5, 0, 1, 4)
        lyrics_files_layout.addWidget(lyrics_box)

        lookup_box = QGroupBox("Lyrics Lookup")
        lookup_layout = QGridLayout(lookup_box)
        self.lookup_subdir_edit = QLineEdit()
        self.lookup_subdir_edit.setPlaceholderText("lyrics")
        lookup_layout.addWidget(QLabel("Lookup subfolder"), 0, 0)
        lookup_layout.addWidget(self.lookup_subdir_edit, 0, 1, 1, 3)

        lookup_hint = QLabel(
            "Lookup uses the audio filename, not the export filename pattern. "
            "Order: embedded lyrics first, then sidecars next to the audio file, "
            "then matching files inside this optional relative subfolder."
        )
        lookup_hint.setWordWrap(True)
        lookup_layout.addWidget(lookup_hint, 1, 0, 1, 4)
        lyrics_files_layout.addWidget(lookup_box)

        scan_box = QGroupBox("Library Scan")
        scan_layout = QGridLayout(scan_box)
        self.scan_worker_spin = QSpinBox()
        self.scan_worker_spin.setRange(1, 16)
        self.scan_worker_spin.setSuffix(" workers")
        scan_layout.addWidget(QLabel("Parallel workers"), 0, 0)
        scan_layout.addWidget(self.scan_worker_spin, 0, 1)
        self.scan_source_combo = QComboBox()
        self.scan_source_combo.addItem("Embedded + sidecar", "both")
        self.scan_source_combo.addItem("Embedded only", "embedded_only")
        self.scan_source_combo.addItem("Sidecar only", "sidecar_only")
        scan_layout.addWidget(QLabel("Lyrics source during scan"), 1, 0)
        scan_layout.addWidget(self.scan_source_combo, 1, 1)
        scan_hint = QLabel(
            "Higher values can speed up SSD scans, while lower values may be better for HDDs or network shares. "
            "Choosing embedded-only or sidecar-only can also reduce scan time on slow network storage."
        )
        scan_hint.setWordWrap(True)
        scan_layout.addWidget(scan_hint, 2, 0, 1, 2)
        self.logging_verbosity_combo = QComboBox()
        self.logging_verbosity_combo.addItem("Errors only", LOG_VERBOSITY_CHOICES[0])
        self.logging_verbosity_combo.addItem("Warnings", LOG_VERBOSITY_CHOICES[1])
        self.logging_verbosity_combo.addItem("Normal (info)", LOG_VERBOSITY_CHOICES[2])
        self.logging_verbosity_combo.addItem("Verbose (debug)", LOG_VERBOSITY_CHOICES[3])
        scan_layout.addWidget(QLabel("Logging verbosity"), 3, 0)
        scan_layout.addWidget(self.logging_verbosity_combo, 3, 1)
        logging_hint = QLabel("Verbose mode shows extra diagnostic details in the log panel and log file.")
        logging_hint.setWordWrap(True)
        scan_layout.addWidget(logging_hint, 4, 0, 1, 2)
        lyrics_files_layout.addWidget(scan_box)

        embed_box = QGroupBox("Audio File")
        embed_layout = QGridLayout(embed_box)
        self.embed_chk = QCheckBox("Embed lyrics into the audio file")
        self.embed_chk.setChecked(True)
        embed_layout.addWidget(self.embed_chk, 0, 0, 1, 2)

        self.embed_format_combo = QComboBox()
        self._populate_lyrics_format_combo(self.embed_format_combo)
        embed_layout.addWidget(QLabel("Embedded contents"), 1, 0)
        embed_layout.addWidget(self.embed_format_combo, 1, 1)

        self.reaction_delay_spin = QSpinBox()
        self.reaction_delay_spin.setRange(-2000, 2000)
        self.reaction_delay_spin.setSingleStep(10)
        self.reaction_delay_spin.setSuffix(" ms")
        embed_layout.addWidget(QLabel("Reaction delay"), 2, 0)
        embed_layout.addWidget(self.reaction_delay_spin, 2, 1)

        reaction_hint = QLabel("Negative values stamp earlier. Positive values stamp later.")
        reaction_hint.setWordWrap(True)
        embed_layout.addWidget(reaction_hint, 3, 0, 1, 2)
        lyrics_embed_layout.addWidget(embed_box)

        ai_sync_box = QGroupBox("AI Auto-Sync")
        ai_sync_layout = QGridLayout(ai_sync_box)
        self.ai_device_combo = QComboBox()
        for label, value in AI_SYNC_DEVICE_OPTIONS:
            self.ai_device_combo.addItem(label, value)
        self.ai_language_combo = QComboBox()
        for label, value in AI_SYNC_LANGUAGE_OPTIONS:
            self.ai_language_combo.addItem(label, value)
        # Fuzzy matching controls
        self.ai_enable_fuzzy_chk = QCheckBox("Enable fuzzy matching (tolerates ASR errors)")
        self.ai_enable_fuzzy_chk.setChecked(True)
        self.ai_fuzzy_threshold_spin = QSpinBox()
        self.ai_fuzzy_threshold_spin.setRange(0, 100)
        self.ai_fuzzy_threshold_spin.setValue(60)
        self.ai_fuzzy_threshold_spin.setSuffix(" %")
        self.ai_enable_demucs_chk = QCheckBox(
            "Try optional Demucs vocal stem and keep it only if quality improves"
        )
        self.ai_enable_demucs_chk.setChecked(True)

        ai_sync_layout.addWidget(QLabel("Execution device"), 0, 0)
        ai_sync_layout.addWidget(self.ai_device_combo, 0, 1)
        ai_sync_layout.addWidget(QLabel("Transcription language"), 1, 0)
        ai_sync_layout.addWidget(self.ai_language_combo, 1, 1)
        ai_sync_layout.addWidget(self.ai_enable_fuzzy_chk, 2, 0, 1, 2)
        ai_sync_layout.addWidget(QLabel("Fuzzy threshold"), 3, 0)
        ai_sync_layout.addWidget(self.ai_fuzzy_threshold_spin, 3, 1)
        ai_sync_layout.addWidget(self.ai_enable_demucs_chk, 4, 0, 1, 2)
        ai_sync_hint = QLabel(
            "These options control local AI auto-sync only. "
            "Changes apply to the next Auto Sync run."
        )
        ai_sync_hint.setWordWrap(True)
        ai_sync_layout.addWidget(ai_sync_hint, 5, 0, 1, 2)
        ai_sync_tab_layout.addWidget(ai_sync_box)
        ai_sync_tab_layout.addStretch(1)

        lrclib_box = QGroupBox("LRCLIB")
        lrclib_layout = QGridLayout(lrclib_box)
        self.lrclib_instance_edit = QLineEdit()
        self.lrclib_instance_edit.setPlaceholderText("https://lrclib.net")
        lrclib_layout.addWidget(QLabel("Server URL"), 0, 0)
        lrclib_layout.addWidget(self.lrclib_instance_edit, 0, 1)
        self.lrclib_reset_btn = QPushButton("Reset to Default")
        lrclib_layout.addWidget(self.lrclib_reset_btn, 0, 2)
        lrclib_hint = QLabel(
            "The LRCLIB server used for downloading and publishing lyrics. "
            "Leave empty to use the default public server (lrclib.net)."
        )
        lrclib_hint.setWordWrap(True)
        lrclib_layout.addWidget(lrclib_hint, 1, 0, 1, 3)
        lyrics_download_layout.addWidget(lrclib_box)

        lyrics_download_layout.addStretch(1)
        lyrics_files_layout.addStretch(1)
        lyrics_embed_layout.addStretch(1)

        # Editor Settings
        lyrics_editor_tab = QWidget()
        lyrics_editor_layout = QVBoxLayout(lyrics_editor_tab)
        editor_box = QGroupBox("Lyrics Editor")
        editor_layout = QGridLayout(editor_box)
        self.auto_edit_on_add_line_chk = QCheckBox("Automatically enter editing mode when a new line is added")
        editor_layout.addWidget(self.auto_edit_on_add_line_chk, 0, 0, 1, 2)
        lyrics_editor_layout.addWidget(editor_box)
        lyrics_editor_layout.addStretch(1)

        self.lyrics_sections_tabs.addTab(lyrics_download_tab, "Download")
        self.lyrics_sections_tabs.addTab(lyrics_files_tab, "Files")
        self.lyrics_sections_tabs.addTab(lyrics_embed_tab, "Embed")
        self.lyrics_sections_tabs.addTab(lyrics_editor_tab, "Editor")
        lyrics_tab_layout.addStretch(1)

        self.tabs.addTab(library_tab, "Library")
        self.tabs.addTab(lyrics_tab, "Lyrics")
        self.tabs.addTab(ai_sync_tab, "AI Sync")
        self.tabs.addTab(appearance_tab, "Appearance")
        self.tabs.addTab(shortcuts_tab, "Shortcuts")

        self.save_btn = QPushButton("Save")
        layout.addWidget(self.save_btn)

        self._load()

        self.add_btn.clicked.connect(self.add_folder)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.save_btn.clicked.connect(self.save)
        self.browse_output_btn.clicked.connect(self._browse_output_dir)
        self.clear_output_btn.clicked.connect(lambda: self.output_dir_edit.setText(""))
        self.save_sidecars_chk.toggled.connect(self._update_export_fields_enabled)
        self.embed_chk.toggled.connect(self._update_embed_fields_enabled)
        self.pattern_edit.textChanged.connect(self._update_pattern_preview)
        self.output_dir_edit.textChanged.connect(self._update_pattern_preview)
        self.sidecar_format_combo.currentIndexChanged.connect(self._update_pattern_preview)
        self.download_mode_combo.currentIndexChanged.connect(self._update_download_mode_hint)
        self.add_excluded_path_btn.clicked.connect(self._add_excluded_path)
        self.add_excluded_file_btn.clicked.connect(self._add_excluded_file)
        self.remove_excluded_path_btn.clicked.connect(self._remove_selected_excluded_path_lines)
        self.test_exclusions_btn.clicked.connect(self._test_exclusions)
        self.excluded_patterns_edit.textChanged.connect(self._validate_regex_patterns)
        self.lrclib_reset_btn.clicked.connect(lambda: self.lrclib_instance_edit.setText(""))
        self.shortcuts_reset_btn.clicked.connect(self._reset_hotkeys_to_defaults)

    def _load(self):
        directories = get_directories(self.app_state.db)
        self.list_widget.clear()
        for directory in directories:
            self.list_widget.addItem(directory)

        config = get_config(self.app_state.db)
        theme_idx = self.theme_combo.findData(config.theme_mode or "auto")
        self.theme_combo.setCurrentIndex(max(0, theme_idx))
        ui_scale_idx = self.ui_scale_combo.findData(int(config.ui_scale_percent or 100))
        self.ui_scale_combo.setCurrentIndex(max(0, ui_scale_idx))
        font_size_idx = self.font_size_combo.findData(config.font_size_mode or "normal")
        self.font_size_combo.setCurrentIndex(max(0, font_size_idx))
        album_art_idx = self.album_art_combo.findData(bool(config.show_album_art))
        self.album_art_combo.setCurrentIndex(max(0, album_art_idx))
        startup_view_idx = self.startup_view_combo.findData(config.startup_view or "remember_last")
        self.startup_view_combo.setCurrentIndex(max(0, startup_view_idx))
        self.save_sidecars_chk.setChecked(config.save_lyrics_sidecars)
        sidecar_format_idx = self.sidecar_format_combo.findData(getattr(config, "lyrics_sidecar_format", "both") or "both")
        self.sidecar_format_combo.setCurrentIndex(max(0, sidecar_format_idx))
        mode_index = self.download_mode_combo.findData(config.download_lyrics_mode or "prefer_synced")
        self.download_mode_combo.setCurrentIndex(max(0, mode_index))
        self.output_dir_edit.setText(config.lyrics_output_dir)
        self.pattern_edit.setText(config.lyrics_file_pattern or "")
        self.lookup_subdir_edit.setText(config.lyrics_lookup_subdir or "")
        source_idx = self.scan_source_combo.findData(getattr(config, "scan_lyrics_source_mode", "both") or "both")
        self.scan_source_combo.setCurrentIndex(max(0, source_idx))
        self.scan_worker_spin.setValue(int(getattr(config, "scan_worker_count", 4) or 4))
        verbosity_idx = self.logging_verbosity_combo.findData(getattr(config, "logging_verbosity", "info") or "info")
        self.logging_verbosity_combo.setCurrentIndex(max(0, verbosity_idx))
        self.embed_chk.setChecked(config.try_embed_lyrics)
        embed_format_idx = self.embed_format_combo.findData(getattr(config, "lyrics_embed_format", "both") or "both")
        self.embed_format_combo.setCurrentIndex(max(0, embed_format_idx))
        self.reaction_delay_spin.setValue(int(config.reaction_delay_ms or 0))
        self.ignore_sort_articles_chk.setChecked(bool(getattr(config, "ignore_sort_articles", False)))

        try:
            ui_state = json.loads(config.ui_state_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            ui_state = {}
        if not isinstance(ui_state, dict):
            ui_state = {}
        self.auto_edit_on_add_line_chk.setChecked(bool(ui_state.get("editor_auto_edit_on_add_line", False)))

        ai_settings = load_ai_sync_settings(getattr(config, "ui_state_json", ""))
        ai_device_idx = self.ai_device_combo.findData(str(ai_settings.get("device") or "auto"))
        self.ai_device_combo.setCurrentIndex(max(0, ai_device_idx))
        ai_language_idx = self.ai_language_combo.findData(str(ai_settings.get("language") or "auto"))
        self.ai_language_combo.setCurrentIndex(max(0, ai_language_idx))
        # ensure widgets exist before setting
        if (
            hasattr(self, "ai_enable_fuzzy_chk")
            and hasattr(self, "ai_fuzzy_threshold_spin")
            and hasattr(self, "ai_enable_demucs_chk")
        ):
            self.ai_enable_fuzzy_chk.setChecked(bool(ai_settings.get("enable_fuzzy", True)))
            try:
                self.ai_fuzzy_threshold_spin.setValue(int(ai_settings.get("fuzzy_threshold", 60)))
            except Exception:
                self.ai_fuzzy_threshold_spin.setValue(60)
            self.ai_enable_demucs_chk.setChecked(
                bool(ai_settings.get("enable_demucs_candidate", True))
            )
        lrclib_url = (config.lrclib_instance or "").strip()
        self.lrclib_instance_edit.setText("" if lrclib_url == "https://lrclib.net" else lrclib_url)
        self.excluded_paths_edit.setPlainText(config.scan_excluded_paths)
        self.excluded_patterns_edit.setPlainText(config.scan_excluded_patterns)
        for action, binding in parse_hotkey_bindings(config.hotkey_bindings_json).items():
            self.shortcut_enabled_checks[action].setChecked(bool(binding.get("enabled", True)))
            self.shortcut_edits[action].setEnabled(bool(binding.get("enabled", True)))
            self.shortcut_edits[action].setKeySequence(QKeySequence(str(binding.get("key", HOTKEY_SPECS[action].default))))
        if config.lyrics_output_dir:
            self._last_browse_dir = config.lyrics_output_dir
        elif directories:
            self._last_browse_dir = directories[0]
        else:
            self._last_browse_dir = os.path.expanduser("~")
        self._update_export_fields_enabled()
        self._update_embed_fields_enabled()
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

    @staticmethod
    def _should_use_qt_picker() -> bool:
        # The native Windows picker exposes mapped drives and network shares
        # more reliably than the Qt fallback dialog.
        return os.name != "nt"

    def _configure_picker_dialog(self, dialog: QFileDialog) -> None:
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, self._should_use_qt_picker())
        dialog.setOption(QFileDialog.Option.DontUseCustomDirectoryIcons, True)

    def _pick_directory(self, title: str, preferred: str = "") -> str:
        dialog = QFileDialog(self, title, self._dialog_start_dir(preferred))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        self._configure_picker_dialog(dialog)
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
        self._configure_picker_dialog(dialog)
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
        self.sidecar_format_combo.setEnabled(enabled)
        self.output_dir_edit.setEnabled(enabled)
        self.pattern_edit.setEnabled(enabled)
        self.browse_output_btn.setEnabled(enabled)
        self.clear_output_btn.setEnabled(enabled)
        self._update_pattern_preview()

    def _update_embed_fields_enabled(self):
        self.embed_format_combo.setEnabled(self.embed_chk.isChecked())

    def _set_text_edit_visible_rows(self, edit: QTextEdit, rows: int) -> None:
        line_height = edit.fontMetrics().lineSpacing()
        frame_height = edit.frameWidth() * 2
        document_margin = int(edit.document().documentMargin() * 2)
        extra_padding = 12
        edit.setFixedHeight(max(38, line_height * rows + frame_height + document_margin + extra_padding))

    def _build_shortcut_controls(self, layout: QGridLayout, *, group: str, columns: int = 1) -> None:
        actions = [(action, spec) for action, spec in HOTKEY_SPECS.items() if spec.group == group]
        rows_per_column = max(1, (len(actions) + columns - 1) // columns)
        for index, (action, spec) in enumerate(actions):
            column = index // rows_per_column
            row = index % rows_per_column
            base_column = column * 3
            enabled_chk = QCheckBox("Enabled")
            enabled_chk.setChecked(True)
            edit = QKeySequenceEdit()
            enabled_chk.toggled.connect(edit.setEnabled)
            tooltip = f"{spec.description}. Default: {spec.default}."
            label = QLabel(spec.label)
            label.setToolTip(tooltip)
            edit.setToolTip(tooltip)
            enabled_chk.setToolTip(tooltip)
            layout.addWidget(label, row, base_column)
            layout.addWidget(edit, row, base_column + 1)
            layout.addWidget(enabled_chk, row, base_column + 2)
            self.shortcut_enabled_checks[action] = enabled_chk
            self.shortcut_edits[action] = edit

        for column in range(columns):
            layout.setColumnStretch(column * 3 + 1, 1)

    def _reset_hotkeys_to_defaults(self) -> None:
        for action, spec in HOTKEY_SPECS.items():
            self.shortcut_enabled_checks[action].setChecked(True)
            self.shortcut_edits[action].setKeySequence(QKeySequence(spec.default))

    def _current_hotkey_bindings(self) -> dict[str, dict[str, object]]:
        return {
            action: {
                "enabled": self.shortcut_enabled_checks[action].isChecked(),
                "key": edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText),
            }
            for action, edit in self.shortcut_edits.items()
        }

    def _validate_hotkey_bindings(self, bindings: dict[str, dict[str, object]]) -> str | None:
        missing_labels = [
            spec.label
            for action, spec in HOTKEY_SPECS.items()
            if bindings.get(action, {}).get("enabled", True) and not str(bindings.get(action, {}).get("key", "")).strip()
        ]
        if missing_labels:
            return f"Shortcut missing for: {', '.join(missing_labels)}"

        duplicates = find_duplicate_hotkeys(bindings)
        if duplicates:
            first_action, second_action, key = duplicates[0]
            first_label = HOTKEY_SPECS[first_action].label
            second_label = HOTKEY_SPECS[second_action].label
            return f"{first_label} and {second_label} both use {key}. Choose distinct shortcuts."
        return None

    @staticmethod
    def _populate_lyrics_format_combo(combo: QComboBox) -> None:
        combo.addItem("Synced and plain", "both")
        combo.addItem("Synced only", "synced_only")
        combo.addItem("Plain only", "plain_only")
        combo.addItem("Prefer synced, fallback to plain", "prefer_synced")

    def _update_download_mode_hint(self) -> None:
        mode = str(self.download_mode_combo.currentData() or "prefer_synced")
        self.download_mode_hint_label.setText(
            f"{missing_lyrics_summary(mode)} {missing_lyrics_detail(mode)}"
        )

    def _safe_filename_component(self, value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (value or "").strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" .")

    def _normalized_lookup_subdir(self) -> str:
        raw = (self.lookup_subdir_edit.text() or "").strip().replace("\\", "/")
        if not raw:
            return ""
        if os.path.isabs(raw) or re.match(r"^[a-zA-Z]:", raw):
            return ""
        parts = [part.strip() for part in raw.split("/") if part.strip() not in {"", "."}]
        if not parts or any(part == ".." for part in parts):
            return ""
        return "/".join(parts)

    def _render_pattern_preview(self) -> tuple[str, bool]:
        pattern = self.pattern_edit.text().strip()
        values = {
            "filename": self._safe_filename_component("01. Everything In Its Right Place"),
            "artist": self._safe_filename_component("Radiohead"),
            "title": self._safe_filename_component("Everything In Its Right Place"),
            "album": self._safe_filename_component("Kid A"),
            "track": self._safe_filename_component("01"),
        }
        used_fallback = False
        if not pattern:
            rendered = values["filename"]
        else:
            try:
                rendered = pattern.format(**values).strip()
            except (KeyError, ValueError, IndexError):
                rendered = ""
                used_fallback = True
        rendered = self._safe_filename_component(rendered)
        if not rendered:
            rendered = values["filename"]
            used_fallback = True

        output_dir = self.output_dir_edit.text().strip()
        suffix = self._lyrics_format_preview_suffix()
        if output_dir:
            return os.path.join(output_dir, rendered) + f" ({suffix})", used_fallback
        return rendered + f" ({suffix} next to the audio file)", used_fallback

    def _lyrics_format_preview_suffix(self) -> str:
        mode = str(self.sidecar_format_combo.currentData() or "both")
        if mode == "synced_only":
            return ".lrc"
        if mode == "plain_only":
            return ".txt"
        if mode == "prefer_synced":
            return ".lrc, or .txt if synced lyrics are unavailable"
        return ".lrc / .txt"

    def _update_pattern_preview(self) -> None:
        if not self.save_sidecars_chk.isChecked():
            self.pattern_preview_label.setProperty("validationState", "")
            self.pattern_preview_label.setText(
                "Export preview: lyric files will be saved next to the audio file when sidecar saving is disabled."
            )
        else:
            preview, used_fallback = self._render_pattern_preview()
            self.pattern_preview_label.setProperty("validationState", "error" if used_fallback else "success")
            if used_fallback:
                self.pattern_preview_label.setText(
                    "Export preview (fallback used due to invalid or empty result):\n"
                    f"{preview}"
                )
            else:
                self.pattern_preview_label.setText(f"Export preview:\n{preview}")

        self.pattern_preview_label.style().unpolish(self.pattern_preview_label)
        self.pattern_preview_label.style().polish(self.pattern_preview_label)
        self.pattern_preview_label.update()

    def save(self):
        previous_folders = get_directories(self.app_state.db)
        folders = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        hotkey_bindings = self._current_hotkey_bindings()
        hotkey_error = self._validate_hotkey_bindings(hotkey_bindings)
        if hotkey_error:
            QMessageBox.warning(self, "Invalid shortcuts", hotkey_error)
            return

        config = get_config(self.app_state.db)

        try:
            ui_state = json.loads(config.ui_state_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            ui_state = {}
        if not isinstance(ui_state, dict):
            ui_state = {}
        ui_state["editor_auto_edit_on_add_line"] = self.auto_edit_on_add_line_chk.isChecked()

        ai_state_json = merge_ai_sync_settings(
            json.dumps(ui_state, ensure_ascii=True, separators=(",", ":")),
            {
                "device": str(self.ai_device_combo.currentData() or "auto"),
                "language": str(self.ai_language_combo.currentData() or "auto"),
                "enable_fuzzy": self.ai_enable_fuzzy_chk.isChecked(),
                "fuzzy_threshold": int(self.ai_fuzzy_threshold_spin.value()),
                "enable_demucs_candidate": self.ai_enable_demucs_chk.isChecked(),
            },
        )
        new_config = replace(
            config,
            theme_mode=str(self.theme_combo.currentData() or "auto"),
            ui_scale_percent=int(self.ui_scale_combo.currentData() or 100),
            font_size_mode=str(self.font_size_combo.currentData() or "normal"),
            show_album_art=bool(self.album_art_combo.currentData()),
            startup_view=str(self.startup_view_combo.currentData() or "remember_last"),
            save_lyrics_sidecars=self.save_sidecars_chk.isChecked(),
            lyrics_sidecar_format=str(self.sidecar_format_combo.currentData() or "both"),
            download_lyrics_mode=str(self.download_mode_combo.currentData() or "prefer_synced"),
            try_embed_lyrics=self.embed_chk.isChecked(),
            lyrics_embed_format=str(self.embed_format_combo.currentData() or "both"),
            lyrics_output_dir=self.output_dir_edit.text().strip(),
            lyrics_file_pattern=self.pattern_edit.text().strip(),
            lyrics_lookup_subdir=self._normalized_lookup_subdir(),
            scan_excluded_paths=self.excluded_paths_edit.toPlainText().strip(),
            scan_excluded_patterns=self.excluded_patterns_edit.toPlainText().strip(),
            scan_lyrics_source_mode=str(self.scan_source_combo.currentData() or "both"),
            scan_worker_count=int(self.scan_worker_spin.value()),
            logging_verbosity=str(self.logging_verbosity_combo.currentData() or "info"),
            reaction_delay_ms=int(self.reaction_delay_spin.value()),
            lrclib_instance=self.lrclib_instance_edit.text().strip() or "https://lrclib.net",
            hotkey_bindings_json=serialize_hotkey_bindings(hotkey_bindings),
            ui_state_json=ai_state_json,
            ignore_sort_articles=self.ignore_sort_articles_chk.isChecked(),
        )

        set_directories(self.app_state.db, folders)
        set_config(self.app_state.db, new_config)
        self.directories_changed = folders != previous_folders
        self.accept()
