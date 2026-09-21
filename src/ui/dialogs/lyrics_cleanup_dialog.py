from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QVBoxLayout,
)

from db.models import Config, Track
from ui.button_roles import set_button_role
from ui.services.lyrics_cleanup_service import (
    LyricsCleanupOptions,
    preview_lyrics_cleanup,
)
from ui.spacing import SPACE_2, SPACE_3, set_layout_spacing


class LyricsCleanupDialog(QDialog):
    def __init__(self, tracks: list[Track], config: Config, parent=None) -> None:
        super().__init__(parent)
        self._tracks = list(tracks)
        self._config = config
        self.setWindowTitle("Clear Lyrics")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        set_layout_spacing(layout, margins=(SPACE_3, SPACE_3, SPACE_3, SPACE_3), spacing=SPACE_2)

        count = len(self._tracks)
        self.summary = QLabel(
            f"Choose what to clear for {count} selected track{'s' if count != 1 else ''}."
        )
        self.summary.setWordWrap(True)
        self.summary.setObjectName("LyricsCleanupSummary")
        layout.addWidget(self.summary)

        self.track_list = QListWidget()
        self.track_list.setObjectName("LyricsCleanupTrackList")
        for track in self._tracks[:100]:
            label = f"{track.artist_name} — {track.title}".strip(" —")
            preview = preview_lyrics_cleanup(track, config)
            if preview.sidecar_paths:
                label += f"  ({len(preview.sidecar_paths)} sidecar file(s))"
            self.track_list.addItem(label)
        if count > 100:
            self.track_list.addItem(f"… and {count - 100} more track(s)")
        self.track_list.setMaximumHeight(180)
        layout.addWidget(self.track_list)

        self.clear_txt = QCheckBox("Clear TXT lyrics")
        self.clear_txt.setChecked(True)
        self.clear_txt.setToolTip("Clear saved TXT/plain lyrics from the library database and their matching draft.")

        self.clear_lrc = QCheckBox("Clear LRC lyrics")
        self.clear_lrc.setChecked(True)
        self.clear_lrc.setToolTip("Clear saved LRC/synced lyrics from the library database and their matching draft.")

        self.delete_sidecars = QCheckBox("Delete detected .lrc/.txt sidecar files")
        self.delete_sidecars.setToolTip("Only matching files shown in the preview are removed.")

        self.clear_embedded_txt = QCheckBox("Remove PyLrcGet embedded TXT/plain lyrics")
        self.clear_embedded_txt.setToolTip("Removes only the PyLrcGet-managed TXT/plain field; other tags are preserved.")

        self.clear_embedded_lrc = QCheckBox("Remove PyLrcGet embedded LRC/synced lyrics")
        self.clear_embedded_lrc.setToolTip("Removes only the PyLrcGet-managed LRC/synced field; other tags are preserved.")

        self.discard_drafts = QCheckBox("Discard unsaved drafts")
        self.discard_drafts.setChecked(True)
        self.discard_drafts.setToolTip("Remove unsaved lyrics drafts stored for these tracks.")

        library_box = QGroupBox("Library database")
        library_layout = QGridLayout(library_box)
        set_layout_spacing(library_layout, margins=(SPACE_2, SPACE_2, SPACE_2, SPACE_2), spacing=SPACE_2)
        library_layout.addWidget(self.clear_txt, 0, 0)
        library_layout.addWidget(self.clear_lrc, 0, 1)
        library_layout.addWidget(self.discard_drafts, 1, 0, 1, 2)
        library_layout.setColumnStretch(0, 1)
        library_layout.setColumnStretch(1, 1)

        embedded_box = QGroupBox("Embedded audio")
        embedded_layout = QVBoxLayout(embedded_box)
        set_layout_spacing(embedded_layout, margins=(SPACE_2, SPACE_2, SPACE_2, SPACE_2), spacing=SPACE_2)
        embedded_layout.addWidget(self.clear_embedded_txt)
        embedded_layout.addWidget(self.clear_embedded_lrc)

        files_box = QGroupBox("External files")
        files_layout = QVBoxLayout(files_box)
        set_layout_spacing(files_layout, margins=(SPACE_2, SPACE_2, SPACE_2, SPACE_2), spacing=SPACE_2)
        files_layout.addWidget(self.delete_sidecars)

        options_layout = QGridLayout()
        set_layout_spacing(options_layout, spacing=SPACE_2)
        options_layout.addWidget(library_box, 0, 0, 1, 2)
        options_layout.addWidget(embedded_box, 1, 0)
        options_layout.addWidget(files_box, 1, 1)
        options_layout.setColumnStretch(0, 1)
        options_layout.setColumnStretch(1, 1)
        layout.addLayout(options_layout)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setObjectName("LyricsCleanupWarning")
        layout.addWidget(self.warning)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        clean_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        clean_button.setText("Clear Lyrics")
        set_button_role(clean_button, "danger")
        set_button_role(self.buttons.button(QDialogButtonBox.StandardButton.Cancel), "secondary")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        for checkbox in (
            self.clear_txt,
            self.clear_lrc,
            self.delete_sidecars,
            self.clear_embedded_txt,
            self.clear_embedded_lrc,
            self.discard_drafts,
        ):
            checkbox.toggled.connect(self._update_warning)
        self._update_warning()

    def options(self) -> LyricsCleanupOptions:
        return LyricsCleanupOptions(
            clear_library=self.clear_txt.isChecked() or self.clear_lrc.isChecked(),
            clear_txt=self.clear_txt.isChecked(),
            clear_lrc=self.clear_lrc.isChecked(),
            delete_sidecars=self.delete_sidecars.isChecked(),
            clear_embedded_txt=self.clear_embedded_txt.isChecked(),
            clear_embedded_lrc=self.clear_embedded_lrc.isChecked(),
            discard_drafts=self.discard_drafts.isChecked(),
        )

    def _update_warning(self) -> None:
        options = self.options()
        selected = (
            options.clear_library
            or options.delete_sidecars
            or options.clear_embedded
            or options.clear_embedded_txt
            or options.clear_embedded_lrc
            or options.discard_drafts
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(selected)

        warnings: list[str] = []
        embedded_selected = (
            options.clear_embedded
            or options.clear_embedded_txt
            or options.clear_embedded_lrc
        )
        if options.clear_library and not options.delete_sidecars and not embedded_selected:
            warnings.append("Lyrics may return on the next scan if sidecar or embedded lyrics remain on disk.")
        if options.delete_sidecars:
            warnings.append("Matching sidecar files will be permanently deleted.")
        if embedded_selected:
            warnings.append("Audio files will be modified; non-lyrics metadata is preserved.")
        self.warning.setText(" ".join(warnings))
        self.warning.setVisible(bool(warnings))
