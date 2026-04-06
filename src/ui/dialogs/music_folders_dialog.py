from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
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
    QVBoxLayout,
)

from core.lyrics_sidecar import DEFAULT_LYRICS_FILE_PATTERN
from db.database import get_config, get_directories, set_config, set_directories
from db.models import Config


class MusicFoldersDialog(QDialog):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(640, 520)
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
        embed_layout = QVBoxLayout(embed_box)
        self.embed_chk = QCheckBox("Embed lyrics into the audio file")
        self.embed_chk.setChecked(True)
        embed_layout.addWidget(self.embed_chk)
        layout.addWidget(embed_box)

        self.save_btn = QPushButton("Save")
        layout.addWidget(self.save_btn)

        self._load()

        self.add_btn.clicked.connect(self.add_folder)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.save_btn.clicked.connect(self.save)
        self.browse_output_btn.clicked.connect(self._browse_output_dir)
        self.clear_output_btn.clicked.connect(lambda: self.output_dir_edit.setText(""))
        self.save_sidecars_chk.toggled.connect(self._update_export_fields_enabled)

    def _load(self):
        self.list_widget.clear()
        for directory in get_directories(self.app_state.db):
            self.list_widget.addItem(directory)

        config = get_config(self.app_state.db)
        self.save_sidecars_chk.setChecked(config.save_lyrics_sidecars)
        self.output_dir_edit.setText(config.lyrics_output_dir)
        self.pattern_edit.setText(config.lyrics_file_pattern or DEFAULT_LYRICS_FILE_PATTERN)
        self.embed_chk.setChecked(config.try_embed_lyrics)
        self._update_export_fields_enabled()

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
        new_config = Config(
            skip_tracks_with_synced_lyrics=config.skip_tracks_with_synced_lyrics,
            skip_tracks_with_plain_lyrics=config.skip_tracks_with_plain_lyrics,
            show_line_count=config.show_line_count,
            save_lyrics_sidecars=self.save_sidecars_chk.isChecked(),
            try_embed_lyrics=self.embed_chk.isChecked(),
            theme_mode=config.theme_mode,
            lrclib_instance=config.lrclib_instance,
            lyrics_output_dir=self.output_dir_edit.text().strip(),
            lyrics_file_pattern=self.pattern_edit.text().strip() or DEFAULT_LYRICS_FILE_PATTERN,
        )

        set_directories(self.app_state.db, folders)
        set_config(self.app_state.db, new_config)
        self.accept()
