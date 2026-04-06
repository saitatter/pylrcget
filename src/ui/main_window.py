from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel,
    QTabWidget, QProgressBar, QMessageBox, QLineEdit, QHBoxLayout, QCheckBox, QSplitter, QBoxLayout, QPushButton, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QShortcut, QKeySequence
import os

from dataclasses import replace

from db.database import get_album_by_id, get_artist_by_id, get_config, get_directories, get_track_by_id, set_config
from core.lyrics_sidecar import export_lyrics_sidecars
from ui.workers.library_scanner import LibraryScanner
from ui.widgets.track_list_widget import TrackListWidget
from ui.dialogs.music_folders_dialog import MusicFoldersDialog
from ui.player_bar import PlayerBar
from ui.widgets.lyrics_editor_widget import LyricsEditorWidget
from ui.dialogs.publish_lyrics_dialog import PublishLyricsDialog
from ui.dialogs.first_run_dialog import FirstRunDialog
from player.player import NowPlaying
from core.embed_lyrics import embed_lyrics_for_track
from ui.app_theme import apply_app_theme
from ui.widgets.album_list_widget import AlbumListWidget
from ui.widgets.artist_list_widget import ArtistListWidget
from ui.icon_loader import load_svg_icon
from ui.spacing import SPACE_1, SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.toast import ToastManager
from PySide6.QtWidgets import QToolButton


class MainWindow(QMainWindow):
    @staticmethod
    def _display_album_name(value: str | None) -> str:
        text = (value or "").strip()
        if text.casefold() in {"", "album", "unknown album"}:
            return "N/A"
        return text

    @staticmethod
    def _display_artist_name(value: str | None) -> str:
        text = (value or "").strip()
        if text.casefold() in {"", "artist", "unknown artist"}:
            return "N/A"
        return text

    def __init__(self, app_state):
        super().__init__()
        self.setWindowTitle("LrcGet")
        self.resize(900, 600)
        self.app_state = app_state

        self._queue_ids: list[int] = []
        self._queue_index: int = -1
        self._refresh_default_label = "Global Actions"
        self._pending_playback_speed: float | None = None
        self._playback_speed_save_timer = QTimer(self)
        self._playback_speed_save_timer.setSingleShot(True)
        self._playback_speed_save_timer.setInterval(350)
        self._playback_speed_save_timer.timeout.connect(self._flush_playback_speed)

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
        set_layout_spacing(self.layout, margins=SPACE_3, spacing=SPACE_3)

        self.toasts = ToastManager(self)
        self.app_state.notification.connect(self._on_notify)

        # --- Top controls (search + filters) ---
        self.top_bar = QWidget()
        self.top_bar.setObjectName("TopBar")
        top_bar = QHBoxLayout(self.top_bar)
        self.top_bar_layout = top_bar
        set_layout_spacing(top_bar, margins=SPACE_2, spacing=SPACE_2)

        self.search_group = QWidget()
        self.search_group.setObjectName("TopBarGroup")
        search_layout = QVBoxLayout(self.search_group)
        set_layout_spacing(search_layout, margins=SPACE_2, spacing=SPACE_1)

        self.search_label = QLabel("Search Library")
        self.search_label.setObjectName("TopBarLabel")
        search_layout.addWidget(self.search_label)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search tracks / artists / albums...")
        self.search_box.setObjectName("TopBarSearch")
        self.search_box.setAccessibleName("Library search")
        search_layout.addWidget(self.search_box)
        top_bar.addWidget(self.search_group, stretch=3)

        self.filters_group = QWidget()
        self.filters_group.setObjectName("TopBarGroup")
        filters_layout = QVBoxLayout(self.filters_group)
        set_layout_spacing(filters_layout, margins=SPACE_2, spacing=SPACE_1)

        self.filters_label = QLabel("Filter Lyrics")
        self.filters_label.setObjectName("TopBarLabel")
        filters_layout.addWidget(self.filters_label)

        filters_row = QHBoxLayout()
        set_layout_spacing(filters_row, spacing=SPACE_2)

        self.chk_synced = QCheckBox("Synced")
        self.chk_synced.setChecked(True)
        self.chk_synced.setAccessibleName("Filter synced lyrics")
        filters_row.addWidget(self.chk_synced)

        self.chk_plain = QCheckBox("Plain")
        self.chk_plain.setChecked(True)
        self.chk_plain.setAccessibleName("Filter plain lyrics")
        filters_row.addWidget(self.chk_plain)

        self.chk_instr = QCheckBox("Instrumental")
        self.chk_instr.setChecked(False)
        self.chk_instr.setAccessibleName("Filter instrumental tracks")
        filters_row.addWidget(self.chk_instr)

        self.chk_none = QCheckBox("No lyrics")
        self.chk_none.setChecked(True)
        self.chk_none.setAccessibleName("Filter tracks without lyrics")
        filters_row.addWidget(self.chk_none)
        filters_row.addStretch(1)
        filters_layout.addLayout(filters_row)
        top_bar.addWidget(self.filters_group, stretch=2)

        # --- Action icons (top-right) ---
        self.actions_group = QWidget()
        self.actions_group.setObjectName("TopBarGroup")
        actions_layout = QVBoxLayout(self.actions_group)
        set_layout_spacing(actions_layout, margins=SPACE_2, spacing=SPACE_1)

        self.actions_label = QLabel("Global Actions")
        self.actions_label.setObjectName("TopBarLabel")
        actions_layout.addWidget(self.actions_label)

        actions_row = QHBoxLayout()
        set_layout_spacing(actions_row, spacing=SPACE_2)

        self.btn_refresh = QToolButton()
        self.btn_refresh.setObjectName("TopBarAction")
        self.btn_refresh.setIcon(load_svg_icon("refresh-cw.svg", 18))
        self.btn_refresh.setToolTip("Refresh library")
        self.btn_refresh.setAccessibleName("Refresh library")
        self.btn_refresh.clicked.connect(self.refresh_library)

        self.btn_config = QToolButton()
        self.btn_config.setObjectName("TopBarAction")
        self.btn_config.setIcon(load_svg_icon("settings-2.svg", 18))
        self.btn_config.setToolTip("Settings")
        self.btn_config.setAccessibleName("Open music folder settings")
        self.btn_config.clicked.connect(self.open_config_modal)

        self.btn_about = QToolButton()
        self.btn_about.setObjectName("TopBarAction")
        self.btn_about.setIcon(load_svg_icon("info.svg", 18))
        self.btn_about.setToolTip("About")
        self.btn_about.setAccessibleName("About LrcGet")
        self.btn_about.clicked.connect(self.open_about_modal)

        actions_row.addWidget(self.btn_refresh)
        actions_row.addWidget(self.btn_config)
        actions_row.addWidget(self.btn_about)
        actions_row.addStretch(1)
        actions_layout.addLayout(actions_row)
        top_bar.addWidget(self.actions_group, stretch=1)

        self.layout.addWidget(self.top_bar)

        # --- Tabs ---
        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)

        # Tracks tab
        self.tracks_tab = QWidget()
        tracks_layout = QVBoxLayout(self.tracks_tab)
        set_layout_spacing(tracks_layout, margins=0, spacing=SPACE_2)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter = splitter

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
        self.tabs.addTab(self.mylrclib_tab, "My LRCLIB")
        self.tabs.setAccessibleName("Library navigation tabs")

        self.layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # --- PlayerBar (fără Now Playing label separat) ---
        self.player_bar = PlayerBar(self.app_state.player, self)
        self.layout.addWidget(self.player_bar)
        self.player_bar.set_prev_next_handlers(self.play_prev, self.play_next)
        self.player_bar.playbackSpeedChanged.connect(self._persist_playback_speed)
        self.player_bar.artistNavigationRequested.connect(self._open_current_track_artist)
        self.player_bar.albumNavigationRequested.connect(self._open_current_track_album)
        self.lyrics_view.set_reaction_delay_ms(get_config(self.app_state.db).reaction_delay_ms)
        self._apply_saved_playback_speed()

        # --- Scan progress (pretty + hidden when idle) ---
        self.scan_row = QWidget()
        scan_layout = QHBoxLayout(self.scan_row)
        set_layout_spacing(scan_layout, margins=(SPACE_3, SPACE_2, SPACE_3, SPACE_2), spacing=SPACE_2)

        self.scan_label = QLabel("Scanning…")
        self.scan_label.setObjectName("ScanLabel")
        self.scan_details = QLabel("Preparing scan…")
        self.scan_details.setObjectName("ScanDetails")

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ScanProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        scan_text = QVBoxLayout()
        set_layout_spacing(scan_text, spacing=SPACE_1)
        scan_text.addWidget(self.scan_label)
        scan_text.addWidget(self.scan_details)

        self.btn_cancel_scan = QPushButton("Cancel")
        self.btn_cancel_scan.setObjectName("ScanCancelButton")
        self.btn_cancel_scan.clicked.connect(self._cancel_scan)
        self.btn_cancel_scan.setEnabled(False)

        scan_layout.addLayout(scan_text)
        scan_layout.addWidget(self.progress_bar, 1)
        scan_layout.addWidget(self.btn_cancel_scan)

        self.layout.addWidget(self.scan_row)
        self.scan_row.setVisible(False)
        self.scan_row.setObjectName("ScanRow")

        # --- Signals from track list ---
        self.track_list.playTrack.connect(self.on_play_track)
        self.track_list.downloadLyrics.connect(self.on_download_lyrics)
        self.track_list.openArtist.connect(self._on_open_artist)
        self.track_list.openAlbum.connect(self._on_open_album)
        self.track_list.markInstrumental.connect(self._on_mark_instrumental)
        self.track_list.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.track_list.clearFiltersRequested.connect(self._reset_track_filters)
        self.track_list.configureFoldersRequested.connect(self.open_config_modal)
        self.lyrics_view.downloadRequested.connect(self._download_current_track_lyrics)
        self.albums_tab.playTrack.connect(self.on_play_track)
        self.albums_tab.downloadLyrics.connect(self.on_download_lyrics)
        self.albums_tab.openAlbum.connect(self._open_album_in_albums_tab)
        self.albums_tab.openArtist.connect(self._open_artist_in_artists_tab)
        self.albums_tab.markInstrumental.connect(self._on_mark_instrumental)
        self.albums_tab.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.albums_tab.clearFiltersRequested.connect(self._reset_track_filters)
        self.albums_tab.configureFoldersRequested.connect(self.open_config_modal)
        self.artists_tab.playTrack.connect(self.on_play_track)
        self.artists_tab.downloadLyrics.connect(self.on_download_lyrics)
        self.artists_tab.openArtist.connect(self._open_artist_in_artists_tab)
        self.artists_tab.openAlbum.connect(self._open_album_in_artists_tab)
        self.artists_tab.markInstrumental.connect(self._on_mark_instrumental)
        self.artists_tab.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.artists_tab.clearFiltersRequested.connect(self._reset_track_filters)
        self.artists_tab.configureFoldersRequested.connect(self.open_config_modal)

        # --- Filters wiring ---
        self.search_box.textChanged.connect(self._apply_track_filters)
        self.chk_synced.toggled.connect(self._apply_track_filters)
        self.chk_plain.toggled.connect(self._apply_track_filters)
        self.chk_instr.toggled.connect(self._apply_track_filters)
        self.chk_none.toggled.connect(self._apply_track_filters)

        self.setTabOrder(self.search_box, self.chk_synced)
        self.setTabOrder(self.chk_synced, self.chk_plain)
        self.setTabOrder(self.chk_plain, self.chk_instr)
        self.setTabOrder(self.chk_instr, self.chk_none)
        self.setTabOrder(self.chk_none, self.btn_refresh)
        self.setTabOrder(self.btn_refresh, self.btn_config)
        self.setTabOrder(self.btn_config, self.btn_about)
        self.setTabOrder(self.btn_about, self.tabs)

        # initial load
        self._apply_track_filters()
        self.show_queued_notifications()
        self._update_responsive_layout()
        QTimer.singleShot(0, self._maybe_show_first_run_onboarding)

        self._apply_styles()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._flush_playback_speed()
        super().closeEvent(event)

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
        before = get_config(self.app_state.db).theme_mode
        dlg = MusicFoldersDialog(self.app_state, self)
        if dlg.exec():
            updated_config = get_config(self.app_state.db)
            after = updated_config.theme_mode
            if after != before:
                self._apply_theme(after)
            self.lyrics_view.set_reaction_delay_ms(updated_config.reaction_delay_ms)
            self._apply_track_filters()

    def open_about_modal(self):
        self.app_state.notify("LrcGet helps you scan your library, edit lyrics, and publish them to LRCLIB.", "info")

    def _maybe_show_first_run_onboarding(self):
        if get_directories(self.app_state.db):
            return

        self.tabs.setCurrentWidget(self.tracks_tab)
        dlg = FirstRunDialog(self)
        if dlg.exec():
            self.open_config_modal()
            if get_directories(self.app_state.db):
                self.refresh_library()

    # ------------------ scanning ------------------
    def refresh_library(self):
        directories = get_directories(self.app_state.db)
        if not directories:
            self.app_state.notify("Add at least one music folder before starting a library scan.", "warning")
            self._set_tool_feedback(self.btn_refresh, "error")
            QTimer.singleShot(1800, self._reset_refresh_feedback)
            return

        self.scan_row.setVisible(True)
        self.progress_bar.setValue(0)
        self.actions_label.setText("Scanning Library")
        self._set_tool_feedback(self.btn_refresh, "loading")
        self.scan_label.setText("Scanning…")
        self.scan_details.setText(f"Preparing a scan across {len(directories)} folder(s)…")
        self.btn_cancel_scan.setEnabled(True)

        config = get_config(self.app_state.db)
        self.scanner = LibraryScanner(
            self.app_state.db_path,
            directories,
            excluded_paths=config.scan_excluded_paths,
            excluded_patterns=config.scan_excluded_patterns,
        )
        self.scanner.progress_signal.connect(self._update_scan_progress)
        self.scanner.finished_signal.connect(self._scan_finished)
        self.scanner.start()
        self.btn_refresh.setEnabled(False)
        self.statusBar().showMessage("Scanning library…")

    def _update_scan_progress(self, scanned: int, total: int, current_path: str, elapsed_s: float):
        total = max(int(total), 0)
        scanned = max(int(scanned), 0)
        current_name = os.path.basename(current_path) if current_path else ""
        elapsed_s = max(0.0, float(elapsed_s or 0.0))

        if total <= 0:
            # unknown total -> show indeterminate animation
            self.progress_bar.setRange(0, 0)
            self.scan_label.setText("Scanning…")
            self.scan_details.setText("Counting tracks in selected folders…")
            return

        # determinate
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

        percent = int((scanned / total) * 100)
        percent = max(0, min(100, percent))

        self.progress_bar.setValue(percent)
        self.scan_label.setText(f"Scanning… {scanned}/{total} ({percent}%)")
        self.scan_details.setText(
            f"Current file: {current_name or 'Preparing next file…'}  •  Elapsed: {elapsed_s:.1f}s"
        )

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
        self.btn_cancel_scan.setEnabled(False)

        if ok:
            self._apply_track_filters()
            self.app_state.notify(msg or "Library scan finished successfully.", "success")
            self._set_tool_feedback(self.btn_refresh, "success")
        else:
            if "cancel" in (msg or "").lower():
                self.app_state.notify(msg, "warning")
                self._set_tool_feedback(self.btn_refresh, "idle")
            else:
                self.app_state.notify(f"Library scanning failed: {msg}", "error")
                self._set_tool_feedback(self.btn_refresh, "error")

        self.btn_refresh.setEnabled(True)
        QTimer.singleShot(1800, self._reset_refresh_feedback)
        self.statusBar().showMessage(msg, 4000)

    def _cancel_scan(self):
        if not hasattr(self, "scanner") or self.scanner is None:
            return
        self.btn_cancel_scan.setEnabled(False)
        self.scan_details.setText("Cancelling scan after the current batch…")
        self.scanner.requestInterruption()

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
            album=track.album_name,
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
        config = get_config(self.app_state.db)
        lrclib_instance = config.lrclib_instance or "https://lrclib.net"
        lrclib_instance = self._normalize_lrclib_base(lrclib_instance)

        self.statusBar().showMessage(f"Starting lyrics download... ({lrclib_instance})")
        self.track_list.set_download_state(int(track_id), "loading")

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
            if ok:
                self._sync_track_lyrics_outputs(track)
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
            self.app_state.notify("Lyrics downloaded successfully.", "success")
            self.track_list.set_download_state(int(track_id), "success")
        else:
            self.app_state.notify(f"Failed to download lyrics: {msg}", "error")
            self.track_list.set_download_state(int(track_id), "error")
        QTimer.singleShot(1800, lambda tid=int(track_id): self.track_list.set_download_state(tid, "idle"))


    def _on_lyrics_save_requested(self, lrc: str, txt: str):
        if not self.app_state.player or not self.app_state.player.track:
            self.app_state.notify("Start playback or select a track first.", "warning")
            self.lyrics_view.set_save_feedback("error", "No Track")
            return

        track_id = self.app_state.player.track.track_id

        from db.database import (
            update_track_synced_lyrics,
            update_track_plain_lyrics,
            update_track_null_lyrics,
        )

        self.lyrics_view.set_save_feedback("loading", "Saving...")
        try:
            if lrc.strip():
                update_track_synced_lyrics(self.app_state.db, track_id, lrc.strip(), (txt or "").strip())
            elif (txt or "").strip():
                update_track_plain_lyrics(self.app_state.db, track_id, (txt or "").strip())
            else:
                update_track_null_lyrics(self.app_state.db, track_id)

            track = get_track_by_id(self.app_state.db, track_id)
            self._sync_track_lyrics_outputs(track)
            title = f"{track.artist_name} - {track.title}"
            self.lyrics_view.set_track_lyrics(
                title=title,
                txt_lyrics=track.txt_lyrics,
                lrc_lyrics=track.lrc_lyrics,
                instrumental=bool(track.instrumental),
            )
            self.statusBar().showMessage("Lyrics saved.", 2500)
            self.lyrics_view.set_save_feedback("success", "Saved")
        except Exception as exc:
            self.statusBar().showMessage("Failed to save lyrics.", 4000)
            self.app_state.notify(f"Failed to save lyrics: {exc}", "error")
            self.lyrics_view.set_save_feedback("error", "Save Failed")

    # ------------------ publish dialogs ------------------
    def _publish_synced(self):
        self._open_publish_dialog(is_synced=True)

    def _publish_plain(self):
        self._open_publish_dialog(is_synced=False)

    def _open_publish_dialog(self, is_synced: bool):
        if not self.app_state.player or not self.app_state.player.track:
            self.app_state.notify("Start playback or select a track first.", "warning")
            self.lyrics_view.set_publish_feedback(is_synced=is_synced, state="error", message="No Track")
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
        self.lyrics_view.set_publish_feedback(is_synced=is_synced, state="loading", message="Publishing...")
        dlg.exec()
        if dlg.publish_result is True:
            self.lyrics_view.set_publish_feedback(is_synced=is_synced, state="success", message="Published")
            self.app_state.notify("Lyrics published successfully.", "success")
        elif dlg.publish_result is False:
            self.lyrics_view.set_publish_feedback(is_synced=is_synced, state="error", message="Publish Failed")
        else:
            self.lyrics_view.set_publish_feedback(is_synced=is_synced, state="idle")

    # ------------------ helpers ------------------
    def _normalize_lrclib_base(self, url: str) -> str:
        u = (url or "").strip().rstrip("/")
        if not u:
            u = "https://lrclib.net"
        if not u.endswith("/api"):
            u += "/api"
        return u

    def _sync_track_lyrics_outputs(self, track) -> None:
        config = get_config(self.app_state.db)
        if config.save_lyrics_sidecars:
            try:
                written_paths = export_lyrics_sidecars(track, config)
            except Exception as exc:
                self.app_state.notify(f"Failed to export lyrics files: {exc}", "error")
            else:
                if written_paths:
                    self.statusBar().showMessage(f"Lyrics exported to {os.path.dirname(written_paths[0])}", 3000)

        if config.try_embed_lyrics:
            try:
                embed_lyrics_for_track(track)
            except Exception as exc:
                self.app_state.notify(f"Failed to embed lyrics: {exc}", "error")
            else:
                self.statusBar().showMessage("Lyrics embedded into the audio file.", 3000)

    def _apply_saved_playback_speed(self) -> None:
        config = get_config(self.app_state.db)
        speed = float(config.playback_speed or 1.0)
        if self.app_state.player and hasattr(self.app_state.player, "set_playback_speed"):
            try:
                self.app_state.player.set_playback_speed(speed)
            except Exception:
                speed = 1.0
        self.player_bar.set_playback_speed_value(speed)

    def _persist_playback_speed(self, speed: float) -> None:
        self._pending_playback_speed = float(speed)
        self._playback_speed_save_timer.start()

    def _flush_playback_speed(self) -> None:
        if self._pending_playback_speed is None:
            return
        config = get_config(self.app_state.db)
        set_config(self.app_state.db, replace(config, playback_speed=float(self._pending_playback_speed)))
        self._pending_playback_speed = None

    def _play_selected_or_current(self):
        tid = self.track_list.selected_track_id()
        if tid is not None:
            self.on_play_track(tid)

    def _reset_track_filters(self):
        self.search_box.blockSignals(True)
        self.search_box.setText("")
        self.search_box.blockSignals(False)
        self.track_list.setArtistFilter(None)
        self.track_list.setAlbumFilter(None)

        for checkbox, checked in (
            (self.chk_synced, True),
            (self.chk_plain, True),
            (self.chk_instr, False),
            (self.chk_none, True),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

        self._apply_track_filters()

    def _download_current_track_lyrics(self):
        if not self.app_state.player or not self.app_state.player.track:
            self.app_state.notify("Select a track before downloading lyrics.", "warning")
            return
        self.on_download_lyrics(int(self.app_state.player.track.track_id))

    def _set_tool_feedback(self, button: QToolButton, state: str) -> None:
        button.setProperty("actionState", state if state != "idle" else "")
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()
        button.setEnabled(state != "loading")

    def _reset_refresh_feedback(self):
        self._set_tool_feedback(self.btn_refresh, "idle")
        self.btn_refresh.setEnabled(True)
        self.actions_label.setText(self._refresh_default_label)

    def _update_responsive_layout(self):
        width = max(0, self.width())

        if hasattr(self, "top_bar_layout"):
            if width < 1120:
                self.top_bar_layout.setDirection(QBoxLayout.TopToBottom)
            else:
                self.top_bar_layout.setDirection(QBoxLayout.LeftToRight)

        if hasattr(self, "content_splitter"):
            if width < 980:
                if self.content_splitter.orientation() != Qt.Orientation.Vertical:
                    self.content_splitter.setOrientation(Qt.Orientation.Vertical)
                self.content_splitter.setSizes([int(self.height() * 0.54), int(self.height() * 0.46)])
            else:
                if self.content_splitter.orientation() != Qt.Orientation.Horizontal:
                    self.content_splitter.setOrientation(Qt.Orientation.Horizontal)
                self.content_splitter.setSizes([int(width * 0.58), int(width * 0.42)])

        if hasattr(self, "player_bar"):
            self.player_bar.set_compact_mode(width < 980)

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("main_window.qss"))

    def _apply_theme(self, theme_mode: str):
        app = QApplication.instance()
        if app is not None:
            apply_app_theme(app, theme_mode)

        self._apply_styles()
        if hasattr(self, "player_bar"):
            self.player_bar._apply_styles()
        if hasattr(self, "track_list"):
            self.track_list._apply_styles()
            self.track_list.empty_state._apply_styles()
        if hasattr(self, "albums_tab"):
            self.albums_tab._apply_styles()
        if hasattr(self, "artists_tab"):
            self.artists_tab._apply_styles()
        if hasattr(self, "lyrics_view"):
            self.lyrics_view._apply_styles()

    def _on_open_album(self, album_id: int):
        self.tabs.setCurrentWidget(self.tracks_tab)
        self.search_box.blockSignals(True)
        self.search_box.setText("")
        self.search_box.blockSignals(False)

        try:
            album = get_album_by_id(self.app_state.db, int(album_id))
            self.track_list.setAlbumFilterLabel(self._display_album_name(album.get("album_name", "")))
        except Exception:
            self.track_list.setAlbumFilterLabel("")
        self.track_list.setAlbumFilter(int(album_id))

    def _open_album_in_albums_tab(self, album_id: int) -> None:
        self.tabs.setCurrentWidget(self.albums_tab)
        try:
            album = get_album_by_id(self.app_state.db, int(album_id))
            album_name = self._display_album_name(album.get("album_name", ""))
        except Exception:
            album_name = ""
        self.albums_tab.show_album_tracks(int(album_id), album_name)

    def _open_album_in_artists_tab(self, album_id: int) -> None:
        self.tabs.setCurrentWidget(self.artists_tab)
        try:
            album = get_album_by_id(self.app_state.db, int(album_id))
            artist_id = album.get("artist_id")
            artist_name = self._display_artist_name(album.get("artist_name") or album.get("album_artist_name") or "")
            album_name = self._display_album_name(album.get("album_name", ""))
        except Exception:
            artist_id = None
            artist_name = ""
            album_name = ""

        if artist_id is not None:
            self.artists_tab.show_artist_albums(int(artist_id), str(artist_name))
        self.artists_tab.show_album_tracks(int(album_id), album_name)
    
    def _on_open_artist(self, artist_id: int):
        self.tabs.setCurrentWidget(self.tracks_tab)

        # proper filtering, no search hack
        try:
            artist = get_artist_by_id(self.app_state.db, int(artist_id))
            self.track_list.setArtistFilterLabel(self._display_artist_name(artist.get("artist_name", "")))
        except Exception:
            self.track_list.setArtistFilterLabel("")
        self.track_list.setArtistFilter(artist_id)

    def _open_artist_in_artists_tab(self, artist_id: int) -> None:
        self.tabs.setCurrentWidget(self.artists_tab)
        try:
            artist = get_artist_by_id(self.app_state.db, int(artist_id))
            artist_name = self._display_artist_name(artist.get("artist_name", ""))
        except Exception:
            artist_name = ""
        self.artists_tab.show_artist_albums(int(artist_id), artist_name)

    def _open_current_track_album(self, track_id: int) -> None:
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            if track.album_id is None:
                return
            self._on_open_album(int(track.album_id))
        except Exception:
            return

    def _open_current_track_artist(self, track_id: int) -> None:
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            if track.artist_id is None:
                return
            self._on_open_artist(int(track.artist_id))
        except Exception:
            return
    
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
