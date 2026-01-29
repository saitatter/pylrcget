from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel,
    QTabWidget, QPushButton, QProgressBar, QMessageBox, QLineEdit, QHBoxLayout, QCheckBox, QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence
from dataclasses import dataclass
import os

from db.database import get_directories, get_track_by_id
from ui.workers.library_scanner import LibraryScanner
from ui.widgets.track_list_widget import TrackListWidget
from ui.dialogs.music_folders_dialog import MusicFoldersDialog
from ui.player_bar import PlayerBar
from ui.lyrics_view import LyricsView
from ui.dialogs.publish_lyrics_dialog import PublishLyricsDialog
from player.player import NowPlaying
from core.embed_lyrics import embed_lyrics_for_track

@dataclass
class ScanProgress:
    files_scanned: int
    files_count: int


class MainWindow(QMainWindow):
    def __init__(self, app_state):
        super().__init__()
        self.setWindowTitle("LrcGet Python")
        self.resize(900, 600)
        self.app_state = app_state

        self._queue_ids: list[int] = []
        self._queue_index: int = -1

        # --- Player signals ---
        if self.app_state.player:
            self.app_state.player.trackChanged.connect(self._on_player_track_changed)
            self.app_state.player.statusChanged.connect(self._on_player_status_changed)

        # --- Shortcuts ---
        QShortcut(QKeySequence("Space"), self, activated=lambda: self.app_state.player.toggle_play_pause())
        QShortcut(QKeySequence("Return"), self, activated=self._play_selected_or_current)
        QShortcut(QKeySequence("Enter"), self, activated=self._play_selected_or_current)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=self.play_next)
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=self.play_prev)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # --- Top controls (search + filters) ---
        top_bar = QHBoxLayout()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search tracks / artists / albums...")
        top_bar.addWidget(self.search_box, stretch=1)

        self.chk_synced = QCheckBox("Synced")
        self.chk_synced.setChecked(True)
        top_bar.addWidget(self.chk_synced)

        self.chk_plain = QCheckBox("Plain")
        self.chk_plain.setChecked(True)
        top_bar.addWidget(self.chk_plain)

        self.chk_instr = QCheckBox("Instrumental")
        self.chk_instr.setChecked(False)
        top_bar.addWidget(self.chk_instr)

        self.chk_none = QCheckBox("No lyrics")
        self.chk_none.setChecked(True)
        top_bar.addWidget(self.chk_none)

        self.layout.addLayout(top_bar)

        # --- Tabs ---
        self.tabs = QTabWidget()

        # Tracks tab
        self.tracks_tab = QWidget()
        tracks_layout = QVBoxLayout(self.tracks_tab)
        tracks_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.track_list = TrackListWidget(self.app_state)
        splitter.addWidget(self.track_list)

        self.lyrics_view = LyricsView()
        self.lyrics_view.show_none("Select a track to see lyrics")
        self.lyrics_view.saveRequested.connect(self._on_lyrics_save_requested)

        splitter.addWidget(self.lyrics_view)
        self.lyrics_view.seekRequested.connect(lambda ms: self.app_state.player.seek_ms(ms))
        if self.app_state.player:
            self.app_state.player.positionChanged.connect(self.lyrics_view.on_player_position)

        self.lyrics_view.publishSyncedRequested.connect(self._publish_synced)
        self.lyrics_view.publishPlainRequested.connect(self._publish_plain)
        self.lyrics_view.embedRequested.connect(self._on_embed_requested)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        tracks_layout.addWidget(splitter)

        # other tabs placeholder
        self.albums_tab = QLabel("Album list")
        self.artists_tab = QLabel("Artist list")
        self.mylrclib_tab = QLabel("My Lrclib")

        self.tabs.addTab(self.tracks_tab, "Tracks")
        self.tabs.addTab(self.albums_tab, "Albums")
        self.tabs.addTab(self.artists_tab, "Artists")
        self.tabs.addTab(self.mylrclib_tab, "My Lrclib")

        self.layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # --- PlayerBar (fără Now Playing label separat) ---
        self.player_bar = PlayerBar(self.app_state.player, self)
        self.layout.addWidget(self.player_bar)
        self.player_bar.set_prev_next_handlers(self.play_prev, self.play_next)

        # --- Progress bar ---
        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)

        # --- Bottom buttons ---
        self.config_button = QPushButton("Open Config")
        self.about_button = QPushButton("Open About")
        self.refresh_button = QPushButton("Refresh Library")

        self.layout.addWidget(self.config_button)
        self.layout.addWidget(self.about_button)
        self.layout.addWidget(self.refresh_button)

        self.config_button.clicked.connect(self.open_config_modal)
        self.about_button.clicked.connect(self.open_about_modal)
        self.refresh_button.clicked.connect(self.refresh_library)

        # --- Signals from track list ---
        self.track_list.playTrack.connect(self.on_play_track)
        self.track_list.downloadLyrics.connect(self.on_download_lyrics)

        # --- Filters wiring ---
        self.search_box.textChanged.connect(self._apply_track_filters)
        self.chk_synced.toggled.connect(self._apply_track_filters)
        self.chk_plain.toggled.connect(self._apply_track_filters)
        self.chk_instr.toggled.connect(self._apply_track_filters)
        self.chk_none.toggled.connect(self._apply_track_filters)

        # initial load
        self._apply_track_filters()
        self.show_queued_notifications()

    # ------------------ filters ------------------
    def _apply_track_filters(self):
        self.track_list.setSearchValue(self.search_box.text())
        self.track_list.setFilters(
            synced=self.chk_synced.isChecked(),
            plain=self.chk_plain.isChecked(),
            instrumental=self.chk_instr.isChecked(),
            none_=self.chk_none.isChecked(),
        )
        if self.app_state.player and self.app_state.player.track:
            self.track_list.set_now_playing(self.app_state.player.track.track_id)

    # ------------------ modals ------------------
    def open_config_modal(self):
        dlg = MusicFoldersDialog(self.app_state, self)
        dlg.exec()

    def open_about_modal(self):
        QMessageBox.information(self, "About", "About modal here")

    # ------------------ scanning ------------------
    def update_progress(self, progress: ScanProgress):
        percent = int(progress.files_scanned / progress.files_count * 100)
        self.progress_bar.setValue(percent)

    def scanning_finished(self):
        self._apply_track_filters()
        QMessageBox.information(self, "Scan Finished", "Library scanning complete!")

    def refresh_library(self):
        self.progress_bar.setValue(0)

        directories = get_directories(self.app_state.db)
        if not directories:
            QMessageBox.warning(self, "No directories", "No music folders configured.")
            return

        self.scanner = LibraryScanner(self.app_state.db_path, directories)
        self.scanner.progress_signal.connect(self._update_scan_progress)
        self.scanner.finished_signal.connect(self._scan_finished)
        self.scanner.start()

    def _update_scan_progress(self, scanned: int, total: int):
        percent = int((scanned / max(total, 1)) * 100)
        self.progress_bar.setValue(percent)

    def _scan_finished(self, ok: bool, msg: str):
        if ok:
            self._apply_track_filters()
            QMessageBox.information(self, "Scan Finished", msg)
        else:
            QMessageBox.critical(self, "Scan Failed", msg)

    # ------------------ track actions ------------------
    def on_play_track(self, track_id: int):
        self._queue_ids = self.track_list.current_queue_track_ids()
        try:
            self._queue_index = self._queue_ids.index(int(track_id))
        except ValueError:
            self._queue_index = -1

        track = get_track_by_id(self.app_state.db, track_id)

        path = track.file_path
        if os.path.isdir(path):
            path = os.path.join(track.file_path, track.file_name)

        meta = NowPlaying(
            track_id=track.id,
            title=track.title,
            artist=track.artist_name,
            path=path,
        )

        self.app_state.player.play_file(path, meta)

        title = f"{track.artist_name} — {track.title}"
        self.lyrics_view.set_track_lyrics(
            title=title,
            txt_lyrics=track.txt_lyrics,
            lrc_lyrics=track.lrc_lyrics,
            instrumental=bool(track.instrumental),
        )

    def play_next(self):
        if not self._queue_ids:
            self._queue_ids = self.track_list.current_queue_track_ids()
        if not self._queue_ids:
            return

        if self._queue_index < 0 and self.app_state.player and self.app_state.player.track:
            cur_id = int(self.app_state.player.track.track_id)
            self._queue_index = self._queue_ids.index(cur_id) if cur_id in self._queue_ids else -1

        nxt = self._queue_index + 1
        if nxt >= len(self._queue_ids):
            return

        self._queue_index = nxt
        self.on_play_track(self._queue_ids[self._queue_index])

    def play_prev(self):
        if not self._queue_ids:
            self._queue_ids = self.track_list.current_queue_track_ids()
        if not self._queue_ids:
            return

        if self._queue_index < 0 and self.app_state.player and self.app_state.player.track:
            cur_id = int(self.app_state.player.track.track_id)
            self._queue_index = self._queue_ids.index(cur_id) if cur_id in self._queue_ids else -1

        prv = self._queue_index - 1
        if prv < 0:
            return

        self._queue_index = prv
        self.on_play_track(self._queue_ids[self._queue_index])

    # ------------------ player + notifications ------------------
    def show_queued_notifications(self):
        for notify in getattr(self.app_state, "queued_notifications", []):
            self.show_toast(notify)  # TODO: implement
        if hasattr(self.app_state, "queued_notifications"):
            self.app_state.queued_notifications.clear()

    def _on_tab_changed(self, idx: int):
        if self.tabs.widget(idx) is self.tracks_tab:
            self._apply_track_filters()

    def _on_player_track_changed(self, now_playing):
        # doar highlight în listă, fără label de text
        if hasattr(self, "track_list") and self.track_list:
            if now_playing:
                self.track_list.set_now_playing(now_playing.track_id)
            else:
                self.track_list.set_now_playing(None)

    def _on_player_status_changed(self, status):
        # momentan nu mai afișăm nimic text-based aici
        pass

    # ------------------ lyrics download & save ------------------
    def on_download_lyrics(self, track_id: int):
        lrclib_instance = "https://lrclib.net"
        lrclib_instance = self._normalize_lrclib_base(lrclib_instance)

        self.statusBar().showMessage(f"Starting lyrics download... ({lrclib_instance})")

        from ui.workers.lyrics_download_worker import LyricsDownloadWorker
        self._lyrics_worker = LyricsDownloadWorker(
            db_path=self.app_state.db_path,
            track_id=track_id,
            lrclib_instance=lrclib_instance,
            parent=self,
        )
        self._lyrics_worker.progress.connect(lambda s: self.statusBar().showMessage(s))
        self._lyrics_worker.finished.connect(self._on_lyrics_download_finished)
        self._lyrics_worker.start()

    def _on_lyrics_download_finished(self, ok: bool, msg: str, track_id: int):
        self.statusBar().showMessage(msg, 4000)
        self._apply_track_filters()

        try:
            track = get_track_by_id(self.app_state.db, track_id)
            title = f"{track.artist_name} — {track.title}"
            self.lyrics_view.set_track_lyrics(
                title=title,
                txt_lyrics=track.txt_lyrics,
                lrc_lyrics=track.lrc_lyrics,
                instrumental=bool(track.instrumental),
            )
        except Exception:
            pass

        if ok:
            QMessageBox.information(self, "Lyrics", msg)
        else:
            QMessageBox.warning(self, "Lyrics", msg)

    def _on_lyrics_save_requested(self, lrc: str, txt: str):
        if not self.app_state.player or not self.app_state.player.track:
            QMessageBox.information(self, "Lyrics", "No track playing.")
            return

        track_id = self.app_state.player.track.track_id

        from db.database import (
            update_track_synced_lyrics,
            update_track_plain_lyrics,
            update_track_null_lyrics,
        )

        if lrc.strip():
            update_track_synced_lyrics(self.app_state.db, track_id, lrc.strip(), (txt or "").strip())
        elif (txt or "").strip():
            update_track_plain_lyrics(self.app_state.db, track_id, (txt or "").strip())
        else:
            update_track_null_lyrics(self.app_state.db, track_id)

        track = get_track_by_id(self.app_state.db, track_id)
        title = f"{track.artist_name} — {track.title}"
        self.lyrics_view.set_track_lyrics(
            title=title,
            txt_lyrics=track.txt_lyrics,
            lrc_lyrics=track.lrc_lyrics,
            instrumental=bool(track.instrumental),
        )
        self.statusBar().showMessage("Lyrics saved.", 2500)

    # ------------------ publish dialogs ------------------
    def open_publish_dialog_for_current_track(self, is_synced: bool):
        if not self.app_state.player or not self.app_state.player.track:
            QMessageBox.information(self, "Publish", "No track playing.")
            return

        track_id = self.app_state.player.track.track_id
        track = get_track_by_id(self.app_state.db, track_id)

        lyrics_text = track.lrc_lyrics if is_synced else (track.txt_lyrics or "")
        dlg = PublishLyricsDialog(
            title=track.title,
            artist_name=track.artist_name,
            album_name=track.album_name,
            duration_s=float(track.duration or 0.0),
            lyrics_text=lyrics_text or "",
            is_synced=is_synced,
            lint_result=[],
            parent=self,
        )
        dlg.exec()

    def _publish_synced(self):
        self._open_publish_dialog(is_synced=True)

    def _publish_plain(self):
        self._open_publish_dialog(is_synced=False)

    def _open_publish_dialog(self, is_synced: bool):
        if not self.app_state.player or not self.app_state.player.track:
            QMessageBox.information(self, "Publish", "No track playing.")
            return

        track_id = self.app_state.player.track.track_id
        track = get_track_by_id(self.app_state.db, track_id)

        lyrics_text = (track.lrc_lyrics or "") if is_synced else (track.txt_lyrics or "")
        dlg = PublishLyricsDialog(
            title=track.title,
            artist_name=track.artist_name,
            album_name=track.album_name,
            duration_s=float(track.duration or 0.0),
            lyrics_text=lyrics_text,
            is_synced=is_synced,
            lint_result=[],
            parent=self,
        )
        dlg.exec()

    # ------------------ helpers ------------------
    def _normalize_lrclib_base(self, url: str) -> str:
        u = (url or "").strip().rstrip("/")
        if not u:
            u = "https://lrclib.net"
        if not u.endswith("/api"):
            u += "/api"
        return u

    def _play_selected_or_current(self):
        tid = self.track_list.selected_track_id()
        if tid is not None:
            self.on_play_track(tid)

    def _on_embed_requested(self):
        # embed doar pentru track-ul care cântă acum (simplu și clar)
        if not self.app_state.player or not self.app_state.player.track:
            QMessageBox.information(self, "Embed lyrics", "No track playing.")
            return

        track_id = self.app_state.player.track.track_id

        try:
            track = get_track_by_id(self.app_state.db, track_id)
        except Exception as e:
            QMessageBox.warning(self, "Embed lyrics", f"Cannot read track from database: {e}")
            return

        try:
            embed_lyrics_for_track(track)
            QMessageBox.information(
                self,
                "Embed lyrics",
                "Lyrics have been embedded into the audio file tags."
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "Embed lyrics",
                f"Failed to embed lyrics: {e}"
            )
