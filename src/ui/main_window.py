from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel,
    QTabWidget, QProgressBar, QMessageBox, QLineEdit, QHBoxLayout, QCheckBox, QSplitter, QBoxLayout, QPushButton, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QShortcut, QKeySequence
import logging
import os

from dataclasses import replace

from db.database import get_album_by_id, get_artist_by_id, get_config, get_directories, get_track_by_id, set_config
from core.lyrics_sidecar import export_lyrics_sidecars
from ui.workers.library_scanner import LibraryScanner
from ui.workers.bulk_lyrics_download_worker import BulkLyricsDownloadWorker
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
from ui.library_routes import LibraryRoute, deserialize_route, route_breadcrumbs, serialize_route, tracks_album, tracks_all, tracks_artist
from ui.icon_loader import load_svg_icon
from ui.spacing import SPACE_1, SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.toast import ToastManager
from PySide6.QtWidgets import QToolButton
from ui.widgets.log_panel import LogPanel, QtLogHandler
from ui.widgets.my_lrclib_widget import MyLrclibWidget
from db.queries import get_track_ids_for_download_mode, record_publish_history

logger = logging.getLogger(__name__)


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
        self._pending_playback_volume: float | None = None
        self._pending_library_route: str | None = None
        self._nav_history: list[LibraryRoute] = []
        self._nav_index: int = -1
        self._current_route = tracks_all()
        self._artist_label_cache: dict[int, str] = {}
        self._album_label_cache: dict[int, str] = {}
        self._recent_toast_messages: set[str] = set()
        self._active_download_track_ids: set[int] = set()
        self._download_state_tokens: dict[int, int] = {}
        self._nav_apply_in_progress = False
        self._tab_sync_suppressed = False
        self.scanner = None
        self._download_worker = None
        self._playback_speed_save_timer = QTimer(self)
        self._playback_speed_save_timer.setSingleShot(True)
        self._playback_speed_save_timer.setInterval(350)
        self._playback_speed_save_timer.timeout.connect(self._flush_playback_speed)
        self._playback_volume_save_timer = QTimer(self)
        self._playback_volume_save_timer.setSingleShot(True)
        self._playback_volume_save_timer.setInterval(250)
        self._playback_volume_save_timer.timeout.connect(self._flush_playback_volume)
        self._search_apply_timer = QTimer(self)
        self._search_apply_timer.setSingleShot(True)
        self._search_apply_timer.setInterval(180)
        self._search_apply_timer.timeout.connect(self._apply_library_search)
        self._route_save_timer = QTimer(self)
        self._route_save_timer.setSingleShot(True)
        self._route_save_timer.setInterval(250)
        self._route_save_timer.timeout.connect(self._flush_library_route)

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
        self._ui_log_handler = QtLogHandler()
        self._ui_log_handler.setLevel(logging.INFO)
        self._ui_log_handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)s  %(name)s: %(message)s", "%H:%M:%S")
        )

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

        self.btn_download_missing = QToolButton()
        self.btn_download_missing.setObjectName("TopBarAction")
        self.btn_download_missing.setIcon(load_svg_icon("download.svg", 18))
        self.btn_download_missing.setToolTip("Download missing lyrics")
        self.btn_download_missing.setAccessibleName("Download missing lyrics")
        self.btn_download_missing.clicked.connect(self._download_missing_lyrics)

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

        self.btn_logs = QToolButton()
        self.btn_logs.setObjectName("TopBarAction")
        self.btn_logs.setIcon(load_svg_icon("logs.svg", 18))
        self.btn_logs.setToolTip("Logs")
        self.btn_logs.setAccessibleName("Toggle log panel")
        self.btn_logs.setCheckable(True)
        self.btn_logs.clicked.connect(self._toggle_logs_panel)

        actions_row.addWidget(self.btn_refresh)
        actions_row.addWidget(self.btn_download_missing)
        actions_row.addWidget(self.btn_config)
        actions_row.addWidget(self.btn_about)
        actions_row.addWidget(self.btn_logs)
        actions_row.addStretch(1)
        actions_layout.addLayout(actions_row)
        top_bar.addWidget(self.actions_group, stretch=1)

        self.layout.addWidget(self.top_bar)

        self.nav_bar = QWidget()
        self.nav_bar.setObjectName("LibraryNavBar")
        nav_layout = QHBoxLayout(self.nav_bar)
        set_layout_spacing(nav_layout, margins=(SPACE_2, 0, SPACE_2, 0), spacing=SPACE_2)
        self.breadcrumbs = QWidget()
        self.breadcrumbs.setObjectName("LibraryBreadcrumbs")
        self.breadcrumbs_layout = QHBoxLayout(self.breadcrumbs)
        set_layout_spacing(self.breadcrumbs_layout, margins=0, spacing=SPACE_1)
        nav_layout.addWidget(self.breadcrumbs, 1)
        self.layout.addWidget(self.nav_bar)

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
        self.lyrics_view.exportFilesRequested.connect(self._export_current_track_sidecars)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        tracks_layout.addWidget(splitter)

        self.albums_tab = AlbumListWidget(self.app_state)
        self.albums_page = QWidget()
        albums_layout = QVBoxLayout(self.albums_page)
        set_layout_spacing(albums_layout, margins=0, spacing=SPACE_2)
        self.albums_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.albums_splitter.addWidget(self.albums_tab)
        self.albums_lyrics_view = LyricsEditorWidget()
        self.albums_lyrics_view.show_none("Select a track to see lyrics")
        self.albums_lyrics_view.saveRequested.connect(self._on_lyrics_save_requested)
        self.albums_lyrics_view.seekRequested.connect(lambda ms: self.app_state.player.seek_ms(ms))
        self.albums_lyrics_view.publishSyncedRequested.connect(self._publish_synced)
        self.albums_lyrics_view.publishPlainRequested.connect(self._publish_plain)
        self.albums_lyrics_view.downloadRequested.connect(self._download_current_track_lyrics)
        self.albums_lyrics_view.exportFilesRequested.connect(self._export_current_track_sidecars)
        if self.app_state.player:
            self.app_state.player.positionChanged.connect(self.albums_lyrics_view.on_player_position)
        self.albums_splitter.addWidget(self.albums_lyrics_view)
        self.albums_splitter.setStretchFactor(0, 3)
        self.albums_splitter.setStretchFactor(1, 2)
        albums_layout.addWidget(self.albums_splitter)

        self.artists_tab = ArtistListWidget(self.app_state)
        self.artists_page = QWidget()
        artists_layout = QVBoxLayout(self.artists_page)
        set_layout_spacing(artists_layout, margins=0, spacing=SPACE_2)
        self.artists_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.artists_splitter.addWidget(self.artists_tab)
        self.artists_lyrics_view = LyricsEditorWidget()
        self.artists_lyrics_view.show_none("Select a track to see lyrics")
        self.artists_lyrics_view.saveRequested.connect(self._on_lyrics_save_requested)
        self.artists_lyrics_view.seekRequested.connect(lambda ms: self.app_state.player.seek_ms(ms))
        self.artists_lyrics_view.publishSyncedRequested.connect(self._publish_synced)
        self.artists_lyrics_view.publishPlainRequested.connect(self._publish_plain)
        self.artists_lyrics_view.downloadRequested.connect(self._download_current_track_lyrics)
        self.artists_lyrics_view.exportFilesRequested.connect(self._export_current_track_sidecars)
        if self.app_state.player:
            self.app_state.player.positionChanged.connect(self.artists_lyrics_view.on_player_position)
        self.artists_splitter.addWidget(self.artists_lyrics_view)
        self.artists_splitter.setStretchFactor(0, 3)
        self.artists_splitter.setStretchFactor(1, 2)
        artists_layout.addWidget(self.artists_splitter)

        self.mylrclib_tab = MyLrclibWidget(self.app_state)

        self.tabs.addTab(self.tracks_tab, "Tracks")
        self.tabs.addTab(self.albums_page, "Albums")
        self.tabs.addTab(self.artists_page, "Artists")
        self.tabs.addTab(self.mylrclib_tab, "My LRCLIB")
        self.tabs.setAccessibleName("Library navigation tabs")

        self.layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # --- PlayerBar (fără Now Playing label separat) ---
        self.player_bar = PlayerBar(self.app_state.player, self)
        self.layout.addWidget(self.player_bar)
        self.player_bar.set_prev_next_handlers(self.play_prev, self.play_next)
        self.player_bar.playbackSpeedChanged.connect(self._persist_playback_speed)
        self.player_bar.volumeChanged.connect(self._persist_playback_volume)
        self.player_bar.artistNavigationRequested.connect(self._navigate_current_track_artist)
        self.player_bar.albumNavigationRequested.connect(self._navigate_current_track_album)
        for view in self._all_lyrics_views():
            view.set_reaction_delay_ms(get_config(self.app_state.db).reaction_delay_ms)
            view.set_current_position_provider(self.app_state.player.position_ms if self.app_state.player else None)
        self._apply_saved_playback_speed()
        self._apply_saved_playback_volume()

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

        self.download_row = QWidget()
        download_layout = QHBoxLayout(self.download_row)
        set_layout_spacing(download_layout, margins=(SPACE_3, SPACE_2, SPACE_3, SPACE_2), spacing=SPACE_2)

        self.download_label = QLabel("Downloading lyrics…")
        self.download_label.setObjectName("ScanLabel")
        self.download_details = QLabel("Preparing download…")
        self.download_details.setObjectName("ScanDetails")

        self.download_progress_bar = QProgressBar()
        self.download_progress_bar.setObjectName("ScanProgress")
        self.download_progress_bar.setTextVisible(False)
        self.download_progress_bar.setRange(0, 100)
        self.download_progress_bar.setValue(0)

        download_text = QVBoxLayout()
        set_layout_spacing(download_text, spacing=SPACE_1)
        download_text.addWidget(self.download_label)
        download_text.addWidget(self.download_details)

        self.btn_cancel_download = QPushButton("Cancel")
        self.btn_cancel_download.setObjectName("ScanCancelButton")
        self.btn_cancel_download.clicked.connect(self._cancel_downloads)
        self.btn_cancel_download.setEnabled(False)

        download_layout.addLayout(download_text)
        download_layout.addWidget(self.download_progress_bar, 1)
        download_layout.addWidget(self.btn_cancel_download)

        self.layout.addWidget(self.download_row)
        self.download_row.setVisible(False)
        self.download_row.setObjectName("ScanRow")

        self.log_panel = LogPanel(self)
        self.log_panel.set_log_file_path(getattr(self.app_state, "log_path", ""))
        self.log_panel.setVisible(False)
        self.layout.addWidget(self.log_panel)
        self._ui_log_handler.bridge.messageReady.connect(self._on_log_message)
        logging.getLogger().addHandler(self._ui_log_handler)

        # --- Signals from track list ---
        self.track_list.playTrack.connect(self.on_play_track)
        self.track_list.downloadLyrics.connect(self.on_download_lyrics)
        self.track_list.exportLyricsFiles.connect(self._export_track_sidecars)
        self.track_list.bulkDownloadRequested.connect(self._on_bulk_download_requested)
        self.track_list.navigateRequested.connect(self.navigate_to)
        self.track_list.markInstrumental.connect(self._on_mark_instrumental)
        self.track_list.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.track_list.clearFiltersRequested.connect(self._reset_track_filters)
        self.track_list.configureFoldersRequested.connect(self.open_config_modal)
        self.lyrics_view.downloadRequested.connect(self._download_current_track_lyrics)
        self.albums_tab.playTrack.connect(self.on_play_track)
        self.albums_tab.downloadLyrics.connect(self.on_download_lyrics)
        self.albums_tab.exportLyricsFiles.connect(self._export_track_sidecars)
        self.albums_tab.bulkDownloadRequested.connect(self._on_bulk_download_requested)
        self.albums_tab.navigateRequested.connect(self.navigate_to)
        self.albums_tab.markInstrumental.connect(self._on_mark_instrumental)
        self.albums_tab.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.albums_tab.clearFiltersRequested.connect(self._reset_track_filters)
        self.albums_tab.clearSearchRequested.connect(self._clear_library_search)
        self.albums_tab.refreshLibraryRequested.connect(self.refresh_library)
        self.albums_tab.configureFoldersRequested.connect(self.open_config_modal)
        self.artists_tab.playTrack.connect(self.on_play_track)
        self.artists_tab.downloadLyrics.connect(self.on_download_lyrics)
        self.artists_tab.exportLyricsFiles.connect(self._export_track_sidecars)
        self.artists_tab.bulkDownloadRequested.connect(self._on_bulk_download_requested)
        self.artists_tab.navigateRequested.connect(self.navigate_to)
        self.artists_tab.markInstrumental.connect(self._on_mark_instrumental)
        self.artists_tab.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.artists_tab.clearFiltersRequested.connect(self._reset_track_filters)
        self.artists_tab.clearSearchRequested.connect(self._clear_library_search)
        self.artists_tab.refreshLibraryRequested.connect(self.refresh_library)
        self.artists_tab.configureFoldersRequested.connect(self.open_config_modal)
        self.mylrclib_tab.playTrack.connect(self.on_play_track)

        # --- Filters wiring ---
        self.search_box.textChanged.connect(self._schedule_library_search)
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
        self._update_nav_controls()
        self.navigate_to(tracks_all(), record_history=False)
        QTimer.singleShot(0, self._restore_last_library_route)
        QTimer.singleShot(0, self._maybe_show_first_run_onboarding)

        self._apply_styles()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._flush_playback_speed()
        self._flush_playback_volume()
        self._flush_library_route()
        logging.getLogger().removeHandler(self._ui_log_handler)
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

    def _schedule_library_search(self):
        self._search_apply_timer.start()

    def _apply_library_search(self):
        current = self.tabs.currentWidget()
        text = self.search_box.text()
        if current is self.tracks_tab:
            self._apply_track_filters()
        elif current is self.albums_page:
            self.albums_tab.setSearchValue(text)
        elif current is self.artists_page:
            self.artists_tab.setSearchValue(text)

    # ------------------ modals ------------------
    def open_config_modal(self):
        before = get_config(self.app_state.db).theme_mode
        dlg = MusicFoldersDialog(self.app_state, self)
        if dlg.exec():
            updated_config = get_config(self.app_state.db)
            after = updated_config.theme_mode
            if after != before:
                self._apply_theme(after)
            for view in self._all_lyrics_views():
                view.set_reaction_delay_ms(updated_config.reaction_delay_ms)
            self._apply_track_filters()
            after_dirs = get_directories(self.app_state.db)
            if dlg.directories_changed and after_dirs:
                self.refresh_library()

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
        if self.scanner is not None and self.scanner.isRunning():
            return
        directories = get_directories(self.app_state.db)
        if not directories:
            self.app_state.notify("Add at least one music folder before starting a library scan.", "warning")
            self._set_tool_feedback(self.btn_refresh, "error")
            QTimer.singleShot(1800, self._reset_refresh_feedback)
            return

        logger.info("Starting library scan across %d folder(s).", len(directories))

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

        self._show_deduped_toast(msg, kind, 3000)

    def _on_log_message(self, level: str, message: str) -> None:
        self.log_panel.append_log(level, message)
        normalized_level = (level or "").upper()
        if normalized_level in {"ERROR", "CRITICAL"}:
            self.btn_logs.setChecked(True)
            self.log_panel.setVisible(True)
            self._show_deduped_toast(message, "error", 4000)

    def _show_deduped_toast(self, message: str, notify_type: str, timeout_ms: int) -> None:
        key = f"{notify_type.lower()}::{message.strip()}"
        if key in self._recent_toast_messages:
            return
        self._recent_toast_messages.add(key)
        self.toasts.show_toast(message, notify_type=notify_type, timeout_ms=timeout_ms)
        QTimer.singleShot(
            max(1000, int(timeout_ms) + 500),
            self,
            lambda k=key: self._recent_toast_messages.discard(k),
        )

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
            logger.info("Library scan finished successfully: %s", msg or "ok")
        else:
            if "cancel" in (msg or "").lower():
                self.app_state.notify(msg, "warning")
                self._set_tool_feedback(self.btn_refresh, "idle")
                logger.warning("Library scan cancelled: %s", msg)
            else:
                self.app_state.notify(f"Library scanning failed: {msg}", "error")
                self._set_tool_feedback(self.btn_refresh, "error")
                logger.error("Library scan failed: %s", msg)

        self.btn_refresh.setEnabled(True)
        QTimer.singleShot(1800, self._reset_refresh_feedback)
        self.statusBar().showMessage(msg, 4000)
        self.scanner = None

    def _cancel_scan(self):
        if not hasattr(self, "scanner") or self.scanner is None:
            return
        self.btn_cancel_scan.setEnabled(False)
        self.scan_details.setText("Cancelling scan after the current batch…")
        logger.info("Cancellation requested for library scan.")
        self.scanner.requestInterruption()

    def _toggle_logs_panel(self, checked: bool) -> None:
        self.log_panel.setVisible(bool(checked))

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

        self._set_track_lyrics_views(track)

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
        if self._tab_sync_suppressed or self._nav_apply_in_progress:
            return
        w = self.tabs.widget(idx)
        if w is self.tracks_tab:
            self.navigate_to(tracks_all())
        elif w is self.albums_page:
            self.navigate_to(LibraryRoute(tab="albums", mode="root"))
        elif w is self.artists_page:
            self.navigate_to(LibraryRoute(tab="artists", mode="root"))
        self._schedule_library_search()

    def _on_player_track_changed(self, now_playing):
        if hasattr(self, "track_list") and self.track_list:
            if now_playing:
                self.track_list.set_now_playing(now_playing.track_id)
            else:
                self.track_list.set_now_playing(None)
        if hasattr(self, "albums_tab") and hasattr(self.albums_tab, "track_list"):
            self.albums_tab.track_list.set_now_playing(now_playing.track_id if now_playing else None)
        if hasattr(self, "artists_tab") and hasattr(self.artists_tab, "album_browser"):
            self.artists_tab.album_browser.track_list.set_now_playing(now_playing.track_id if now_playing else None)

    def _on_player_status_changed(self, status):
        # momentan nu mai afișăm nimic text-based aici
        pass

    # ------------------ lyrics download & save ------------------
    def on_download_lyrics(self, track_id: int):
        self._start_lyrics_downloads([int(track_id)], mode_override="use_global")

    def _on_bulk_download_requested(self, track_ids: list[int], mode: str) -> None:
        self._start_lyrics_downloads(track_ids, mode_override=mode)

    def _resolve_download_mode(self, mode_override: str = "use_global") -> str:
        if mode_override and mode_override != "use_global":
            return mode_override
        config = get_config(self.app_state.db)
        return str(config.download_lyrics_mode or "prefer_synced")

    def _start_lyrics_downloads(self, track_ids: list[int], *, mode_override: str = "use_global") -> None:
        unique_ids = [int(t) for t in dict.fromkeys(int(x) for x in track_ids if x is not None)]
        if not unique_ids:
            self.app_state.notify("No tracks selected for lyrics download.", "warning")
            return
        if self._download_worker is not None and self._download_worker.isRunning():
            self.app_state.notify("A lyrics download is already running.", "warning")
            return

        config = get_config(self.app_state.db)
        lrclib_instance = self._normalize_lrclib_base(config.lrclib_instance or "https://lrclib.net")
        mode = self._resolve_download_mode(mode_override)

        for track_id in unique_ids:
            self._set_track_download_state_all(track_id, "loading")
        self._active_download_track_ids = set(unique_ids)

        self.download_row.setVisible(True)
        self.btn_cancel_download.setEnabled(True)
        self.download_label.setText(f"Downloading lyrics ({self._download_mode_label(mode)})")
        self.download_details.setText("Preparing download queue…")
        self.download_progress_bar.setRange(0, len(unique_ids))
        self.download_progress_bar.setValue(0)
        self.statusBar().showMessage(f"Starting lyrics download... ({lrclib_instance})")

        self._download_worker = BulkLyricsDownloadWorker(
            db_path=self.app_state.db_path,
            track_ids=unique_ids,
            lrclib_instance=lrclib_instance,
            download_mode=mode,
            parent=self,
        )
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.itemFinished.connect(self._on_download_item_finished)
        self._download_worker.finishedBatch.connect(self._on_download_batch_finished)
        self._download_worker.start()

    def _download_missing_lyrics(self) -> None:
        mode = self._resolve_download_mode("use_global")
        track_ids = get_track_ids_for_download_mode(self.app_state.db, mode)
        if not track_ids:
            self.app_state.notify("No tracks are missing lyrics for the current download mode.", "info")
            return
        self._start_lyrics_downloads(track_ids, mode_override=mode)

    def _cancel_downloads(self) -> None:
        if self._download_worker is None or not self._download_worker.isRunning():
            return
        self.btn_cancel_download.setEnabled(False)
        self.download_details.setText("Cancelling after the current track…")
        self._download_worker.requestInterruption()

    def _on_download_progress(self, current: int, total: int, track_label: str, status: str, elapsed_s: float) -> None:
        self.download_progress_bar.setRange(0, max(1, int(total)))
        self.download_progress_bar.setValue(min(int(current), int(total)))
        label = track_label or "Lyrics download"
        self.download_details.setText(f"{label}  •  {status}")
        self.statusBar().showMessage(status)

    def _on_download_item_finished(self, track_id: int, ok: bool, msg: str) -> None:
        try:
            if self.app_state.player and self.app_state.player.track and int(self.app_state.player.track.track_id) == int(track_id):
                track = get_track_by_id(self.app_state.db, int(track_id))
                self._set_track_lyrics_views(track)
        except Exception as exc:
            logger.warning("Failed to update track after lyrics download for %s: %s", track_id, exc)

        self._active_download_track_ids.discard(int(track_id))
        state = "success" if ok else "error"
        self._set_track_download_state_all(int(track_id), state)

        token = self._download_state_tokens.get(int(track_id), 0) + 1
        self._download_state_tokens[int(track_id)] = token
        QTimer.singleShot(
            1800,
            self,
            lambda tid=int(track_id), expected=token, expected_state=state: self._reset_track_download_state_if_unchanged(
                tid,
                expected,
                expected_state,
            ),
        )

    def _on_download_batch_finished(self, ok: bool, msg: str, stats: object) -> None:
        self.statusBar().showMessage(msg, 4000)
        self.btn_cancel_download.setEnabled(False)
        self.download_row.setVisible(False)
        for track_id in list(self._active_download_track_ids):
            self._set_track_download_state_all(int(track_id), "idle")
        self._active_download_track_ids.clear()

        try:
            current = self.tabs.currentWidget()
            if current is self.tracks_tab:
                self.track_list.apply_route(self._current_route if self._current_route.tab == "tracks" else tracks_all())
            elif current is self.albums_page:
                self.albums_tab.apply_route(self._current_route if self._current_route.tab == "albums" else LibraryRoute(tab="albums", mode="root"))
            elif current is self.artists_page:
                self.artists_tab.apply_route(self._current_route if self._current_route.tab == "artists" else LibraryRoute(tab="artists", mode="root"))
        except Exception as exc:
            logger.warning("Failed to refresh current view after lyrics download: %s", exc)

        stats_dict = stats if isinstance(stats, dict) else {}
        if stats_dict.get("cancelled"):
            self.app_state.notify("Lyrics download cancelled.", "warning")
        elif int(stats_dict.get("failed", 0)) > 0 and int(stats_dict.get("ok", 0)) > 0:
            self.app_state.notify(msg, "warning")
        elif int(stats_dict.get("failed", 0)) > 0:
            self.app_state.notify(msg, "error")
        else:
            self.app_state.notify("Lyrics downloaded successfully.", "success")
        self._download_worker = None

    def _set_track_download_state_all(self, track_id: int, state: str) -> None:
        self.track_list.set_download_state(int(track_id), state)
        if hasattr(self.albums_tab, "track_list"):
            self.albums_tab.track_list.set_download_state(int(track_id), state)
        if hasattr(self.artists_tab, "album_browser") and hasattr(self.artists_tab.album_browser, "track_list"):
            self.artists_tab.album_browser.track_list.set_download_state(int(track_id), state)

    def _get_primary_track_download_state(self, track_id: int) -> str:
        return self.track_list.get_download_state(int(track_id))

    def _reset_track_download_state_if_unchanged(
        self,
        track_id: int,
        expected_token: int,
        expected_state: str,
    ) -> None:
        if self._download_state_tokens.get(int(track_id)) != int(expected_token):
            return
        if self._get_primary_track_download_state(int(track_id)) != expected_state:
            return
        self._set_track_download_state_all(int(track_id), "idle")

    @staticmethod
    def _download_mode_label(mode: str) -> str:
        labels = {
            "prefer_synced": "Prefer synced",
            "synced_only": "Synced only",
            "plain_only": "Plain only",
        }
        return labels.get((mode or "").strip(), "Custom")


    def _on_lyrics_save_requested(self, lrc: str, txt: str):
        if not self.app_state.player or not self.app_state.player.track:
            self.app_state.notify("Start playback or select a track first.", "warning")
            for view in self._all_lyrics_views():
                view.set_save_feedback("error", "No Track")
            return

        track_id = self.app_state.player.track.track_id

        from db.database import (
            update_track_synced_lyrics,
            update_track_plain_lyrics,
            update_track_null_lyrics,
        )

        for view in self._all_lyrics_views():
            view.set_save_feedback("loading", "Saving...")
        try:
            if lrc.strip():
                update_track_synced_lyrics(self.app_state.db, track_id, lrc.strip(), (txt or "").strip())
            elif (txt or "").strip():
                update_track_plain_lyrics(self.app_state.db, track_id, (txt or "").strip())
            else:
                update_track_null_lyrics(self.app_state.db, track_id)

            track = get_track_by_id(self.app_state.db, track_id)
            self._sync_track_lyrics_outputs(track)
            self._set_track_lyrics_views(track)
            self.statusBar().showMessage("Lyrics saved.", 2500)
            for view in self._all_lyrics_views():
                view.set_save_feedback("success", "Saved")
        except Exception as exc:
            self.statusBar().showMessage("Failed to save lyrics.", 4000)
            self.app_state.notify(f"Failed to save lyrics: {exc}", "error")
            for view in self._all_lyrics_views():
                view.set_save_feedback("error", "Save Failed")

    # ------------------ publish dialogs ------------------
    def _publish_synced(self):
        self._open_publish_dialog(is_synced=True)

    def _publish_plain(self):
        self._open_publish_dialog(is_synced=False)

    def _open_publish_dialog(self, is_synced: bool):
        if not self.app_state.player or not self.app_state.player.track:
            self.app_state.notify("Start playback or select a track first.", "warning")
            for view in self._all_lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="error", message="No Track")
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
        for view in self._all_lyrics_views():
            view.set_publish_feedback(is_synced=is_synced, state="loading", message="Publishing...")
        dlg.exec()
        if dlg.publish_result is True:
            try:
                record_publish_history(
                    self.app_state.db,
                    track_id=int(track.id),
                    title=track.title,
                    artist_name=track.artist_name,
                    album_name=track.album_name,
                    publish_kind="synced" if is_synced else "plain",
                    lrclib_instance=self._normalize_lrclib_base(get_config(self.app_state.db).lrclib_instance),
                )
            except Exception as exc:
                logger.warning("Failed to record publish history: %s", exc)
            else:
                self.mylrclib_tab.refresh()
            for view in self._all_lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="success", message="Published")
            self.app_state.notify("Lyrics published successfully.", "success")
        elif dlg.publish_result is False:
            for view in self._all_lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="error", message="Publish Failed")
        else:
            for view in self._all_lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="idle")

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

    def _apply_saved_playback_volume(self) -> None:
        config = get_config(self.app_state.db)
        volume = float(config.playback_volume)
        if self.app_state.player and hasattr(self.app_state.player, "set_volume"):
            try:
                self.app_state.player.set_volume(volume)
            except Exception as exc:
                logger.warning("Failed to apply saved volume: %s", exc)
                volume = 0.7
        self.player_bar.set_volume_value(volume)

    def _persist_playback_speed(self, speed: float) -> None:
        self._pending_playback_speed = float(speed)
        self._playback_speed_save_timer.start()

    def _persist_playback_volume(self, volume: float) -> None:
        self._pending_playback_volume = float(volume)
        self._playback_volume_save_timer.start()

    def _flush_playback_speed(self) -> None:
        if self._pending_playback_speed is None:
            return
        config = get_config(self.app_state.db)
        set_config(self.app_state.db, replace(config, playback_speed=float(self._pending_playback_speed)))
        self._pending_playback_speed = None

    def _flush_playback_volume(self) -> None:
        if self._pending_playback_volume is None:
            return
        config = get_config(self.app_state.db)
        set_config(self.app_state.db, replace(config, playback_volume=float(self._pending_playback_volume)))
        self._pending_playback_volume = None

    def _persist_library_route(self, route: LibraryRoute) -> None:
        self._pending_library_route = serialize_route(route)
        self._route_save_timer.start()

    def _flush_library_route(self) -> None:
        if self._pending_library_route is None:
            return
        config = get_config(self.app_state.db)
        set_config(self.app_state.db, replace(config, last_library_route=self._pending_library_route))
        self._pending_library_route = None
    def _play_selected_or_current(self):
        tid = self.track_list.selected_track_id()
        if tid is not None:
            self.on_play_track(tid)

    def _reset_track_filters(self):
        self.search_box.blockSignals(True)
        self.search_box.setText("")
        self.search_box.blockSignals(False)
        self.track_list.apply_route(tracks_all())

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

    def _clear_library_search(self) -> None:
        self.search_box.blockSignals(True)
        self.search_box.setText("")
        self.search_box.blockSignals(False)
        current = self.tabs.currentWidget()
        if current is self.tracks_tab:
            self._apply_track_filters()
        elif current is self.albums_page:
            self.albums_tab.setSearchValue("")
        elif current is self.artists_page:
            self.artists_tab.setSearchValue("")

    def _download_current_track_lyrics(self):
        if not self.app_state.player or not self.app_state.player.track:
            self.app_state.notify("Select a track before downloading lyrics.", "warning")
            return
        self.on_download_lyrics(int(self.app_state.player.track.track_id))

    def _export_current_track_sidecars(self):
        if not self.app_state.player or not self.app_state.player.track:
            self.app_state.notify("Select or start a track before exporting lyrics files.", "warning")
            for view in self._all_lyrics_views():
                view.set_export_feedback("error", "No Track")
            return
        self._export_track_sidecars(int(self.app_state.player.track.track_id))

    def _export_track_sidecars(self, track_id: int):
        for view in self._all_lyrics_views():
            view.set_export_feedback("loading", "Exporting...")
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            if not (track.lrc_lyrics or track.txt_lyrics):
                self.app_state.notify("No lyrics are available to export for this track.", "warning")
                for view in self._all_lyrics_views():
                    view.set_export_feedback("error", "No Lyrics")
                return

            config = get_config(self.app_state.db)
            export_config = replace(config, save_lyrics_sidecars=True)
            written_paths = export_lyrics_sidecars(track, export_config)
            if not written_paths:
                self.app_state.notify("No lyrics files were generated for this track.", "warning")
                for view in self._all_lyrics_views():
                    view.set_export_feedback("error", "Nothing Exported")
                return

            output_dir = os.path.dirname(written_paths[0]) or os.path.dirname(track.file_path)
            self.statusBar().showMessage(f"Lyrics files exported to {output_dir}", 3000)
            self.app_state.notify("Lyrics files generated successfully.", "success")
            for view in self._all_lyrics_views():
                view.set_export_feedback("success", "Exported")
        except Exception as exc:
            self.app_state.notify(f"Failed to export lyrics files: {exc}", "error")
            for view in self._all_lyrics_views():
                view.set_export_feedback("error", "Export Failed")

    def _all_lyrics_views(self) -> list[LyricsEditorWidget]:
        return [self.lyrics_view, self.albums_lyrics_view, self.artists_lyrics_view]

    def _set_track_lyrics_views(self, track) -> None:
        title = f"{track.artist_name} — {track.title}"
        for view in self._all_lyrics_views():
            view.set_track_lyrics(
                title=title,
                txt_lyrics=track.txt_lyrics,
                lrc_lyrics=track.lrc_lyrics,
                instrumental=bool(track.instrumental),
            )

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

        for splitter_name in ("albums_splitter", "artists_splitter"):
            splitter = getattr(self, splitter_name, None)
            if splitter is None:
                continue
            if width < 980:
                if splitter.orientation() != Qt.Orientation.Vertical:
                    splitter.setOrientation(Qt.Orientation.Vertical)
                splitter.setSizes([int(self.height() * 0.54), int(self.height() * 0.46)])
            else:
                if splitter.orientation() != Qt.Orientation.Horizontal:
                    splitter.setOrientation(Qt.Orientation.Horizontal)
                splitter.setSizes([int(width * 0.58), int(width * 0.42)])

        if hasattr(self, "player_bar"):
            self.player_bar.set_compact_mode(width < 980)

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("main_window.qss"))

    def navigate_to(self, route: LibraryRoute, *, record_history: bool = True) -> None:
        route = self._hydrate_route(route)
        self._current_route = route
        self._nav_apply_in_progress = True
        try:
            self._tab_sync_suppressed = True
            if route.tab == "tracks":
                self.tabs.setCurrentWidget(self.tracks_tab)
                self.search_box.blockSignals(True)
                self.search_box.setText("")
                self.search_box.blockSignals(False)
                self.track_list.apply_route(route)
            elif route.tab == "albums":
                self.tabs.setCurrentWidget(self.albums_page)
                self.albums_tab.apply_route(route)
            elif route.tab == "artists":
                self.tabs.setCurrentWidget(self.artists_page)
                self.artists_tab.apply_route(route)
        finally:
            self._tab_sync_suppressed = False
            self._nav_apply_in_progress = False

        if record_history:
            if self._nav_index < 0 or self._nav_history[self._nav_index] != route:
                self._nav_history = self._nav_history[: self._nav_index + 1]
                self._nav_history.append(route)
                self._nav_index = len(self._nav_history) - 1
        self._persist_library_route(route)
        self._update_nav_controls()

    def _hydrate_route(self, route: LibraryRoute) -> LibraryRoute:
        artist_label = route.artist_label
        album_label = route.album_label

        if not artist_label and len(route.artist_ids) == 1:
            artist_id = int(route.artist_ids[0])
            artist_label = self._artist_label_cache.get(artist_id, artist_label)
            if not artist_label:
                try:
                    artist = get_artist_by_id(self.app_state.db, artist_id)
                    artist_label = self._display_artist_name(artist.get("artist_name", ""))
                    if artist_label:
                        self._artist_label_cache[artist_id] = artist_label
                except Exception:
                    pass

        if not album_label and len(route.album_ids) == 1:
            album_id = int(route.album_ids[0])
            album_label = self._album_label_cache.get(album_id, album_label)
            if not album_label:
                try:
                    album = get_album_by_id(self.app_state.db, album_id)
                    album_label = self._display_album_name(album.get("album_name", ""))
                    if album_label:
                        self._album_label_cache[album_id] = album_label
                    if not artist_label:
                        artist_label = self._display_artist_name(album.get("artist_name") or album.get("album_artist_name") or "")
                        artist_id = album.get("artist_id")
                        if artist_label and artist_id is not None:
                            self._artist_label_cache[int(artist_id)] = artist_label
                except Exception:
                    pass

        if artist_label == route.artist_label and album_label == route.album_label:
            return route
        return replace(route, artist_label=artist_label, album_label=album_label)

    def _update_nav_controls(self) -> None:
        while self.breadcrumbs_layout.count():
            item = self.breadcrumbs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        crumbs = route_breadcrumbs(self._current_route)
        for idx, (label, route) in enumerate(crumbs):
            btn = QToolButton()
            btn.setObjectName("LibraryBreadcrumbButton")
            btn.setText(label)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setAutoRaise(True)
            btn.setEnabled(idx != len(crumbs) - 1)
            if idx != len(crumbs) - 1:
                btn.clicked.connect(lambda _=False, r=route: self.navigate_to(r))
            self.breadcrumbs_layout.addWidget(btn)
            if idx != len(crumbs) - 1:
                sep = QLabel(">")
                sep.setObjectName("LibraryBreadcrumbSeparator")
                self.breadcrumbs_layout.addWidget(sep)
        self.breadcrumbs_layout.addStretch(1)

    def _navigate_back(self) -> None:
        if self._nav_index <= 0:
            return
        self._nav_index -= 1
        self.navigate_to(self._nav_history[self._nav_index], record_history=False)
        self._update_nav_controls()

    def _navigate_forward(self) -> None:
        if self._nav_index >= len(self._nav_history) - 1:
            return
        self._nav_index += 1
        self.navigate_to(self._nav_history[self._nav_index], record_history=False)
        self._update_nav_controls()

    def _restore_last_library_route(self) -> None:
        config = get_config(self.app_state.db)
        route = deserialize_route(config.last_library_route)
        if route is None:
            route = tracks_all()
        self._nav_history = [route]
        self._nav_index = 0
        self.navigate_to(route, record_history=False)

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
        if hasattr(self, "mylrclib_tab"):
            self.mylrclib_tab._apply_styles()
        if hasattr(self, "lyrics_view"):
            self.lyrics_view._apply_styles()
        if hasattr(self, "albums_lyrics_view"):
            self.albums_lyrics_view._apply_styles()
        if hasattr(self, "artists_lyrics_view"):
            self.artists_lyrics_view._apply_styles()

    def _on_open_album(self, album_id: int):
        try:
            album = get_album_by_id(self.app_state.db, int(album_id))
            label = self._display_album_name(album.get("album_name", ""))
        except Exception:
            label = ""
        self.navigate_to(tracks_album((int(album_id),), label=label))
    
    def _on_open_artist(self, artist_id: int):
        try:
            artist = get_artist_by_id(self.app_state.db, int(artist_id))
            label = self._display_artist_name(artist.get("artist_name", ""))
        except Exception:
            label = ""
        self.navigate_to(tracks_artist((int(artist_id),), label=label))

    def _route_for_current_track_album(self, track_id: int) -> LibraryRoute | None:
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            if track.album_id is None:
                return None
            return tracks_album((int(track.album_id),), label=self._display_album_name(track.album_name))
        except Exception:
            return None

    def _route_for_current_track_artist(self, track_id: int) -> LibraryRoute | None:
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            if track.artist_id is None:
                return None
            return tracks_artist((int(track.artist_id),), label=self._display_artist_name(track.artist_name))
        except Exception:
            return None

    def _navigate_current_track_album(self, track_id: int) -> None:
        route = self._route_for_current_track_album(track_id)
        if route is not None:
            self.navigate_to(route)

    def _navigate_current_track_artist(self, track_id: int) -> None:
        route = self._route_for_current_track_artist(track_id)
        if route is not None:
            self.navigate_to(route)
    
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
