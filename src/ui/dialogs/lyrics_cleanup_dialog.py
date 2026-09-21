from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
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
        self.setWindowTitle("Clean Lyrics")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        set_layout_spacing(layout, margins=(SPACE_3, SPACE_3, SPACE_3, SPACE_3), spacing=SPACE_2)

        count = len(self._tracks)
        self.summary = QLabel(
            f"Choose what to clean for {count} selected track{'s' if count != 1 else ''}."
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

        self.clear_library = QCheckBox("Clear saved lyrics from the library")
        self.clear_library.setChecked(True)
        self.clear_library.setToolTip("Remove plain, synced, and unsaved draft lyrics from the database.")
        layout.addWidget(self.clear_library)

        self.delete_sidecars = QCheckBox("Delete detected .lrc/.txt sidecar files")
        self.delete_sidecars.setToolTip("Only matching files shown in the preview are removed.")
        layout.addWidget(self.delete_sidecars)

        self.clear_embedded = QCheckBox("Remove PyLrcGet lyrics embedded in audio files")
        self.clear_embedded.setToolTip("Removes only lyric fields managed by PyLrcGet; other tags are preserved.")
        layout.addWidget(self.clear_embedded)

        self.discard_drafts = QCheckBox("Discard unsaved drafts")
        self.discard_drafts.setChecked(True)
        self.discard_drafts.setToolTip("Remove unsaved lyrics drafts stored for these tracks.")
        layout.addWidget(self.discard_drafts)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setObjectName("LyricsCleanupWarning")
        layout.addWidget(self.warning)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        clean_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        clean_button.setText("Clean Lyrics")
        set_button_role(clean_button, "danger")
        set_button_role(self.buttons.button(QDialogButtonBox.StandardButton.Cancel), "secondary")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        for checkbox in (
            self.clear_library,
            self.delete_sidecars,
            self.clear_embedded,
            self.discard_drafts,
        ):
            checkbox.toggled.connect(self._update_warning)
        self._update_warning()

    def options(self) -> LyricsCleanupOptions:
        return LyricsCleanupOptions(
            clear_library=self.clear_library.isChecked(),
            delete_sidecars=self.delete_sidecars.isChecked(),
            clear_embedded=self.clear_embedded.isChecked(),
            discard_drafts=self.discard_drafts.isChecked(),
        )

    def _update_warning(self) -> None:
        options = self.options()
        selected = options.clear_library or options.delete_sidecars or options.clear_embedded or options.discard_drafts
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(selected)

        warnings: list[str] = []
        if options.clear_library and not options.delete_sidecars and not options.clear_embedded:
            warnings.append("Lyrics may return on the next scan if sidecar or embedded lyrics remain on disk.")
        if options.delete_sidecars:
            warnings.append("Matching sidecar files will be permanently deleted.")
        if options.clear_embedded:
            warnings.append("Audio files will be modified; non-lyrics metadata is preserved.")
        self.warning.setText(" ".join(warnings))
        self.warning.setVisible(bool(warnings))
