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
from ui.widgets.lyrics_editor_widget import LyricsEditorWidget
from ui.dialogs.publish_lyrics_dialog import PublishLyricsDialog
from player.player import NowPlaying
from core.embed_lyrics import embed_lyrics_for_track
from ui.widgets.album_list_widget import AlbumListWidget
from ui.widgets.artist_list_widget import ArtistListWidget
from ui.widgets.toast import ToastManager
from PySide6.QtWidgets import QToolButton
from PySide6.QtWidgets import QStyle

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

        self.toasts = ToastManager(self)
        self.app_state.notification.connect(self._on_notify)

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
        top_bar.addStretch(1)  # pushes icons to the right

        # --- Action icons (top-right) ---
        self.btn_refresh = QToolButton()
        self.btn_refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.btn_refresh.setToolTip("Refresh library")
        self.btn_refresh.clicked.connect(self.refresh_library)

        self.btn_config = QToolButton()
        self.btn_config.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.btn_config.setToolTip("Settings")
        self.btn_config.clicked.connect(self.open_config_modal)

        self.btn_about = QToolButton()
        self.btn_about.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        self.btn_about.setToolTip("About")
        self.btn_about.clicked.connect(self.open_about_modal)

        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(self.btn_config)
        top_bar.addWidget(self.btn_about)

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

        self.lyrics_view = LyricsEditorWidget()
        self.lyrics_view.show_none("Select a track to see lyrics")
        self.lyrics_view.saveRequested.connect(self._on_lyrics_save_requested)

        splitter.addWidget(self.lyrics_view)
        self.lyrics_view.seekRequested.connect(lambda ms: self.app_state.player.seek_ms(ms))
        if self.app_state.player:
            self.app_state.player.positionChanged.connect(self.lyrics_view.on_player_position)

        self.lyrics_view.publishSyncedRequested.connect(self._publish_synced)
        self.lyrics_view.publishPlainRequested.connect(self._publish_plain)
        self.lyrics_view.saveRequested.connect(self._on_embed_requested)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        tracks_layout.addWidget(splitter)

        # other tabs placeholder
        self.albums_tab = AlbumListWidget(self.app_state)
        self.artists_tab = ArtistListWidget(self.app_state)

        self.mylrclib_tab = QLabel("My Lrclib")

        self.tabs.addTab(self.tracks_tab, "Tracks")
        self.tabs.addTab(self.albums_tab, "Albums")
        self.tabs.addTab(self.artists_tab, "Artists")
        self.tabs.addTab(self.mylrclib_tab, "My Lrclib")

        self.layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.albums_tab.openAlbum.connect(self._on_open_album)
        self.artists_tab.openArtist.connect(self._on_open_artist)

        # --- PlayerBar (fără Now Playing label separat) ---
        self.player_bar = PlayerBar(self.app_state.player, self)
        self.layout.addWidget(self.player_bar)
        self.player_bar.set_prev_next_handlers(self.play_prev, self.play_next)

        # --- Scan progress (pretty + hidden when idle) ---
        self.scan_row = QWidget()
        scan_layout = QHBoxLayout(self.scan_row)
        scan_layout.setContentsMargins(8, 6, 8, 6)
        scan_layout.setSpacing(10)

        self.scan_label = QLabel("Scanning…")
        self.scan_label.setObjectName("ScanLabel")

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ScanProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        scan_layout.addWidget(self.scan_label)
        scan_layout.addWidget(self.progress_bar, 1)

        self.layout.addWidget(self.scan_row)
        self.scan_row.setVisible(False)
        self.scan_row.setObjectName("ScanRow")

        # --- Signals from track list ---
        self.track_list.playTrack.connect(self.on_play_track)
        self.track_list.downloadLyrics.connect(self.on_download_lyrics)
        self.track_list.markInstrumental.connect(self._on_mark_instrumental)
        self.track_list.unmarkInstrumental.connect(self._on_unmark_instrumental)

        # --- Filters wiring ---
        self.search_box.textChanged.connect(self._apply_track_filters)
        self.chk_synced.toggled.connect(self._apply_track_filters)
        self.chk_plain.toggled.connect(self._apply_track_filters)
        self.chk_instr.toggled.connect(self._apply_track_filters)
        self.chk_none.toggled.connect(self._apply_track_filters)

        # initial load
        self._apply_track_filters()
        self.show_queued_notifications()

        self.setStyleSheet(self.styleSheet() + """
            QWidget#ScanRow {
                background: #020617;
                border-top: 1px solid #111827;
            }

            QLabel#ScanLabel {
                color: #9ca3af;
                font-size: 11px;
            }

            QProgressBar#ScanProgress {
                background: #0b1222;
                border: 1px solid #1f2937;
                border-radius: 999px;
                height: 10px;
            }

            QProgressBar#ScanProgress::chunk {
                border-radius: 999px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #38bdf8, stop:1 #22c55e
                );
            }
            QToolButton {
                border: 1px solid transparent;
                background: transparent;
                padding: 6px;
                border-radius: 10px;
            }

            QToolButton:hover {
                background: #0b1222;
                border-color: #1f2937;
            }

            QToolButton:pressed {
                background: #0f172a;
            }
            """)

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
        self.app_state.notify("LrcGet Python — about modal TBD", "info")

    # ------------------ scanning ------------------
    def scanning_finished(self):
        self._apply_track_filters()
        self.app_state.notify("Library scanning complete!", "success")

    def refresh_library(self):
        directories = get_directories(self.app_state.db)
        if not directories:
            self.app_state.notify("No music folders configured.", "warning")
            return

        self.scan_row.setVisible(True)
        self.progress_bar.setValue(0)
        self.scan_label.setText("Scanning…")

        self.scanner = LibraryScanner(self.app_state.db_path, directories)
        self.scanner.progress_signal.connect(self._update_scan_progress)
        self.scanner.finished_signal.connect(self._scan_finished)
        self.scanner.start()
        self.btn_refresh.setEnabled(False)
        self.statusBar().showMessage("Scanning library…")

    def _update_scan_progress(self, scanned: int, total: int):
        total = max(int(total), 0)
        scanned = max(int(scanned), 0)

        if total <= 0:
            # unknown total -> show indeterminate animation
            self.progress_bar.setRange(0, 0)
            self.scan_label.setText("Scanning…")
            return

        # determinate
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

        percent = int((scanned / total) * 100)
        percent = max(0, min(100, percent))

        self.progress_bar.setValue(percent)
        self.scan_label.setText(f"Scanning… {scanned}/{total} ({percent}%)")

    def _on_notify(self, n):
        # n is core.state.Notify
        kind = (getattr(n, "notify_type", "info") or "info").lower()
        # your enum uses "warn"; toast supports "warning"
        if kind == "warn":
            kind = "warning"

        msg = getattr(n, "message", "") or ""
        if not msg:
            return

        self.toasts.show_toast(msg, notify_type=kind, timeout_ms=3000)

    def _scan_finished(self, ok: bool, msg: str):
        # hide progress strip
        self.progress_bar.setRange(0, 100)  # reset from indeterminate if needed
        self.progress_bar.setValue(0)
        self.scan_row.setVisible(False)

        if ok:
            self._apply_track_filters()
            self.app_state.notify("Library scanning complete!", "success")
        else:
            self.app_state.notify(f"Library scanning failed: {msg}", "error")

        self.btn_refresh.setEnabled(True)
        self.statusBar().showMessage(msg, 4000)

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
        for n in getattr(self.app_state, "queued_notifications", []):
            self._on_notify(n)
        if hasattr(self.app_state, "queued_notifications"):
            self.app_state.queued_notifications.clear()

    def _on_tab_changed(self, idx: int):
        w = self.tabs.widget(idx)
        if w is self.tracks_tab:
            self._apply_track_filters()
        elif w is self.albums_tab:
            self.albums_tab.refresh()
        elif w is self.artists_tab:
            self.artists_tab.refresh()

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
            self.app_state.notify("Lyrics downloaded successfully!", "success")
        else:
            self.app_state.notify(f"Failed to download lyrics: {msg}", "error")

    def _on_lyrics_save_requested(self, lrc: str, txt: str):
        if not self.app_state.player or not self.app_state.player.track:
            self.app_state.notify("No track playing.", "warning")
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
            self.app_state.notify("No track playing.", "warning")
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
            self.app_state.notify("No track playing.", "warning")
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
            self.app_state.notify("No track playing.", "warning")
            return

        track_id = self.app_state.player.track.track_id

        try:
            track = get_track_by_id(self.app_state.db, track_id)
        except Exception as e:
            self.app_state.notify(f"Cannot read track from database: {e}", "error")
            return

        try:
            embed_lyrics_for_track(track)
            self.app_state.notify("Lyrics have been embedded into the audio file tags.", "success")
        except Exception as e:
            self.app_state.notify(f"Failed to embed lyrics: {e}", "error")

    def _on_open_album(self, album_id: int):
        self.tabs.setCurrentWidget(self.tracks_tab)
        self.search_box.blockSignals(True)
        self.search_box.setText("")
        self.search_box.blockSignals(False)

        self.track_list.setAlbumFilter(int(album_id))
    
    def _on_open_artist(self, artist_id: int):
        self.tabs.setCurrentWidget(self.tracks_tab)

        # proper filtering, no search hack
        self.track_list.setArtistFilter(artist_id)
    
    def _confirm_bulk(self, title: str, text: str, count: int) -> bool:
        # Confirm only when selection is "large"
        if count < 10:
            return True
        res = QMessageBox.question(
            self,
            title,
            f"{text}\n\nSelected: {count}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return res == QMessageBox.StandardButton.Yes


    def _on_mark_instrumental(self, track_ids: list[int]):
        track_ids = [int(x) for x in track_ids if x is not None]
        if not track_ids:
            return

        if not self._confirm_bulk("Instrumental", "Mark selected tracks as instrumental?", len(track_ids)):
            return

        from db.database import mark_tracks_instrumental

        # Preserve selection across refresh
        selected_before = set(track_ids)

        try:
            mark_tracks_instrumental(self.app_state.db, track_ids)
            self.statusBar().showMessage(f"Marked {len(track_ids)} track(s) as instrumental.", 3000)
            self._apply_track_filters()
            self.track_list.restore_selection(selected_before)
        except Exception as e:
            self.app_state.notify(f"Failed to update tracks: {e}", "error")


    def _on_unmark_instrumental(self, track_ids: list[int]):
        track_ids = [int(x) for x in track_ids if x is not None]
        if not track_ids:
            return

        if not self._confirm_bulk("Instrumental", "Unmark instrumental for selected tracks?", len(track_ids)):
            return

        from db.database import unmark_tracks_instrumental

        selected_before = set(track_ids)

        try:
            unmark_tracks_instrumental(self.app_state.db, track_ids)
            self.statusBar().showMessage(f"Unmarked {len(track_ids)} track(s).", 3000)
            self._apply_track_filters()
            self.track_list.restore_selection(selected_before)
        except Exception as e:
            self.app_state.notify(f"Failed to update tracks: {e}", "error")