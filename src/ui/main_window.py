from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QByteArray, QSettings, QTimer
from PySide6.QtGui import QCloseEvent, QShortcut, QKeySequence
import logging
import os
import sqlite3

from dataclasses import replace

from core.state import Notify
from core.tracklist_models import LyricsState
from db.queries import (
    add_track,
    get_album_by_id,
    get_artist_by_id,
    get_config,
    get_directories,
    refresh_track_from_file,
    get_track_by_id,
    mark_tracks_instrumental,
    set_config,
    set_directories,
    unmark_tracks_instrumental,
    clear_track_dirty_lyrics,
    update_track_null_lyrics,
    update_track_dirty_lyrics,
    update_track_plain_lyrics,
    update_track_synced_lyrics,
)
from library.scan_library import AUDIO_EXTS, new_fs_track_from_path
from ui.workers.library_scanner import LibraryScanner
from ui.controllers.lyrics_download_controller import LyricsDownloadController
from ui.controllers.navigation_controller import NavigationController
from ui.controllers.publish_history_controller import PublishHistoryController
from ui.controllers.top_bar_controller import TopBarController
from ui.widgets.track_list_widget import TrackListWidget
from ui.dialogs.music_folders_dialog import MusicFoldersDialog
from ui.dialogs.about_dialog import AboutDialog
from ui.icon_loader import load_app_icon
from ui.player_bar import PlayerBar
from ui.widgets.lyrics_editor_widget import LyricsEditorWidget
from core.utils import parse_lrc, ms_to_ts as _ms_to_ts
from ui.dialogs.first_run_dialog import FirstRunDialog
from player.player import NowPlaying, Player
from ui.services.lyrics_download_service import sync_track_outputs_with_result
from ui.services.feedback import exception_message, log_and_notify, normalize_notify_type, notify_user
from ui.app_theme import apply_app_theme
from ui.widgets.album_list_widget import AlbumListWidget
from ui.widgets.artist_list_widget import ArtistListWidget
from ui.library_routes import LibraryRoute, deserialize_route, tracks_album, tracks_all, tracks_artist
from ui.spacing import SPACE_1, SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.toast import ToastManager
from ui.widgets.log_panel import LogPanel, QtLogHandler
from ui.widgets.my_lrclib_widget import MyLrclibWidget
from ui.widgets.lrclib_browser_widget import LrclibBrowserWidget
from ui.widgets.download_progress_overlay import DownloadProgressOverlay
from ui.widgets.hotkey_hints import HotkeyHintManager

logger = logging.getLogger(__name__)

LIBRARY_PANE_MIN_WIDTH = 180
LYRICS_PANE_MIN_WIDTH = 480


def _canonical_lyrics_pair(lrc: str | None, txt: str | None) -> tuple[str, str]:
    lrc_text = (lrc or "").strip()
    txt_text = (txt or "").strip()
    if not lrc_text:
        return "", txt_text

    pairs = parse_lrc(lrc_text)
    if not pairs:
        return lrc_text, txt_text

    pairs.sort(key=lambda item: item[0])
    canonical_lrc = "\n".join(
        f"[{_ms_to_ts(ms)}] {text.strip()}" if text.strip() else f"[{_ms_to_ts(ms)}]"
        for ms, text in pairs
    ).strip()
    canonical_txt = txt_text or "\n".join(text.rstrip() for _ms, text in pairs).rstrip()
    return canonical_lrc, canonical_txt


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
        self.setWindowTitle("PyLrcGet")
        self.setWindowIcon(load_app_icon())
        self.resize(900, 600)
        self.setAcceptDrops(True)
        self.app_state = app_state

        self._queue_ids: list[int] = []
        self._queue_index: int = -1
        self._editing_track_id: int | None = None
        self._loading_lyrics_views = False
        self._refresh_default_label = "Global Actions"
        self._pending_playback_speed: float | None = None
        self._pending_playback_volume: float | None = None
        self._ai_sync_worker = None
        self._dirty_lyrics_timer = QTimer(self)
        self._dirty_lyrics_timer.setSingleShot(True)
        self._dirty_lyrics_timer.setInterval(500)
        self._dirty_lyrics_timer.timeout.connect(self._flush_dirty_lyrics)
        self._pending_dirty_lrc: str = ""
        self._pending_dirty_txt: str = ""
        self._recent_toast_messages: set[str] = set()
        self.hotkey_hints = HotkeyHintManager(self)
        self.scanner = None
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
        # --- Player signals ---
        if self.app_state.player:
            self.app_state.player.trackChanged.connect(self._on_player_track_changed)
            self.app_state.player.statusChanged.connect(self._on_player_status_changed)

        # --- Shortcuts ---
        QShortcut(QKeySequence("Space"), self, activated=self._toggle_play_pause)
        QShortcut(QKeySequence("Return"), self, activated=self._play_selected_or_current)
        QShortcut(QKeySequence("Enter"), self, activated=self._play_selected_or_current)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=self.play_next)
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=self.play_prev)
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self._save_active_lyrics)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._focus_search)
        QShortcut(QKeySequence("Ctrl+/"), self, activated=self._toggle_hotkey_hints)

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
        self.top_bar = TopBarController(
            on_refresh=self.refresh_library,
            on_download_missing=self._download_missing_lyrics,
            on_open_settings=self.open_config_modal,
            on_open_about=self.open_about_modal,
            on_toggle_logs=self._toggle_logs_panel,
            on_toggle_hotkey_hints=self._toggle_hotkey_hints,
            on_schedule_search=self._schedule_library_search,
            on_filter_changed=self._apply_track_filters,
            parent=self,
        )
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

        self.track_pane = QWidget()
        track_pane_layout = QVBoxLayout(self.track_pane)
        set_layout_spacing(track_pane_layout, margins=0, spacing=SPACE_2)
        self._create_selection_actions_bar()

        self.track_list = TrackListWidget(self.app_state, show_bulk_context_actions=False)
        track_pane_layout.addWidget(self.selection_actions_bar)
        track_pane_layout.addWidget(self.track_list, 1)
        splitter.addWidget(self.track_pane)

        self.lyrics_view = LyricsEditorWidget()
        self.lyrics_view.show_none("Select a track to see lyrics")
        self._wire_lyrics_view(self.lyrics_view)

        splitter.addWidget(self.lyrics_view)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.track_pane.setMinimumWidth(LIBRARY_PANE_MIN_WIDTH)
        self.lyrics_view.setMinimumWidth(LYRICS_PANE_MIN_WIDTH)

        tracks_layout.addWidget(splitter)

        self.albums_tab = AlbumListWidget(self.app_state)
        self.albums_page = QWidget()
        albums_layout = QVBoxLayout(self.albums_page)
        set_layout_spacing(albums_layout, margins=0, spacing=SPACE_2)
        self.albums_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.albums_splitter.addWidget(self.albums_tab)
        self.albums_lyrics_view = LyricsEditorWidget()
        self.albums_lyrics_view.show_none("Select a track to see lyrics")
        self._wire_lyrics_view(self.albums_lyrics_view)
        self.albums_splitter.addWidget(self.albums_lyrics_view)
        self.albums_splitter.setStretchFactor(0, 3)
        self.albums_splitter.setStretchFactor(1, 2)
        self.albums_splitter.setCollapsible(0, False)
        self.albums_splitter.setCollapsible(1, False)
        self.albums_tab.setMinimumWidth(LIBRARY_PANE_MIN_WIDTH)
        self.albums_lyrics_view.setMinimumWidth(LYRICS_PANE_MIN_WIDTH)
        albums_layout.addWidget(self.albums_splitter)

        self.artists_tab = ArtistListWidget(self.app_state)
        self.artists_page = QWidget()
        artists_layout = QVBoxLayout(self.artists_page)
        set_layout_spacing(artists_layout, margins=0, spacing=SPACE_2)
        self.artists_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.artists_splitter.addWidget(self.artists_tab)
        self.artists_lyrics_view = LyricsEditorWidget()
        self.artists_lyrics_view.show_none("Select a track to see lyrics")
        self._wire_lyrics_view(self.artists_lyrics_view)
        self.artists_splitter.addWidget(self.artists_lyrics_view)
        self.artists_splitter.setStretchFactor(0, 3)
        self.artists_splitter.setStretchFactor(1, 2)
        self.artists_splitter.setCollapsible(0, False)
        self.artists_splitter.setCollapsible(1, False)
        self.artists_tab.setMinimumWidth(LIBRARY_PANE_MIN_WIDTH)
        self.artists_lyrics_view.setMinimumWidth(LYRICS_PANE_MIN_WIDTH)
        artists_layout.addWidget(self.artists_splitter)

        self.mylrclib_tab = MyLrclibWidget(self.app_state)

        self.lrclib_browser_tab = LrclibBrowserWidget(self.app_state)
        self.lrclib_browser_tab.set_lrclib_url(
            self._normalize_lrclib_base(get_config(self.app_state.db).lrclib_instance)
        )

        self.tabs.addTab(self.tracks_tab, "Tracks")
        self.tabs.addTab(self.albums_page, "Albums")
        self.tabs.addTab(self.artists_page, "Artists")
        self.tabs.addTab(self.lrclib_browser_tab, "LRCLIB Browser")
        self.tabs.addTab(self.mylrclib_tab, "My LRCLIB")
        self.tabs.setAccessibleName("Library navigation tabs")

        self.layout.addWidget(self.tabs)

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
        self._apply_appearance_preferences(get_config(self.app_state.db))

        self.download_overlay = DownloadProgressOverlay(self.central_widget)
        self.download_overlay.sync_to_parent()
        self.downloads = LyricsDownloadController(
            self.app_state,
            self.download_overlay,
            normalize_lrclib_base=self._normalize_lrclib_base,
            show_status=self._show_status_message,
            current_player_track_id=self._current_player_track_id,
            set_track_lyrics_views=self._set_track_lyrics_views,
            refresh_visible_library_view=self._refresh_visible_library_view_after_downloads,
            refresh_history=self.mylrclib_tab.refresh,
            set_track_download_state=self._set_track_download_state_all,
            get_track_download_state=self._get_primary_track_download_state,
            parent=self,
        )
        self.download_overlay.cancelRequested.connect(self.downloads.cancel)
        self.publish_overlay = DownloadProgressOverlay(self.central_widget, verb="Publish")
        self.publish_overlay.sync_to_parent()
        self.publish_history = PublishHistoryController(
            self.app_state,
            normalize_lrclib_base=self._normalize_lrclib_base,
            current_player_track_id=lambda: self._editing_track_id,
            lyrics_views=self._all_lyrics_views,
            refresh_history=self.mylrclib_tab.refresh,
            show_status=self._show_status_message,
            publish_overlay=self.publish_overlay,
            parent=self,
        )
        self.publish_overlay.cancelRequested.connect(self._cancel_bulk_publish)

        # Background activity button — shows when an overlay is minimized
        self.download_overlay.activeChanged.connect(self._update_bg_activity_button)
        self.publish_overlay.activeChanged.connect(self._update_bg_activity_button)
        self.download_overlay.minimized.connect(self._update_bg_activity_button)
        self.publish_overlay.minimized.connect(self._update_bg_activity_button)
        self.download_overlay.dismissed.connect(self._update_bg_activity_button)
        self.publish_overlay.dismissed.connect(self._update_bg_activity_button)
        self.top_bar.btn_bg_activity.clicked.connect(self._reopen_bg_overlay)

        self.lyrics_view.publishSyncedRequested.connect(self.publish_history.publish_synced)
        self.lyrics_view.publishPlainRequested.connect(self.publish_history.publish_plain)
        self.albums_lyrics_view.publishSyncedRequested.connect(self.publish_history.publish_synced)
        self.albums_lyrics_view.publishPlainRequested.connect(self.publish_history.publish_plain)
        self.artists_lyrics_view.publishSyncedRequested.connect(self.publish_history.publish_synced)
        self.artists_lyrics_view.publishPlainRequested.connect(self.publish_history.publish_plain)

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

        self.log_panel = LogPanel(self)
        self.log_panel.set_log_file_path(getattr(self.app_state, "log_path", ""))
        self.log_panel.setVisible(False)
        self.layout.addWidget(self.log_panel)
        self._ui_log_handler.bridge.messageReady.connect(self._on_log_message)
        logging.getLogger().addHandler(self._ui_log_handler)

        self.navigation = NavigationController(
            db=self.app_state.db,
            tabs=self.tabs,
            tracks_tab=self.tracks_tab,
            albums_page=self.albums_page,
            artists_page=self.artists_page,
            breadcrumbs_layout=self.breadcrumbs_layout,
            apply_route=self._apply_library_route,
            display_artist_name=self._display_artist_name,
            display_album_name=self._display_album_name,
            parent=self,
        )

        # --- Signals from track list ---
        self.track_list.playTrack.connect(self.on_play_track)
        self.track_list.previewTrack.connect(self._preview_track)
        self.track_list.refreshTrack.connect(self.on_refresh_track)
        self.track_list.bulkRefreshRequested.connect(self.on_refresh_tracks)
        self.track_list.downloadLyrics.connect(self.on_download_lyrics)
        self.track_list.exportLyricsFiles.connect(self._export_track_sidecars)
        self.track_list.bulkDownloadRequested.connect(self._on_bulk_download_requested)
        self.track_list.bulkPublishRequested.connect(self.publish_history.publish_batch)
        self.track_list.navigateRequested.connect(self.navigate_to)
        self.track_list.markInstrumental.connect(self._on_mark_instrumental)
        self.track_list.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.track_list.clearFiltersRequested.connect(self._reset_track_filters)
        self.track_list.configureFoldersRequested.connect(self.open_config_modal)
        self.albums_tab.playTrack.connect(self.on_play_track)
        self.albums_tab.previewTrack.connect(self._preview_track)
        self.albums_tab.refreshTrack.connect(self.on_refresh_track)
        self.albums_tab.bulkRefreshRequested.connect(self.on_refresh_tracks)
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
        self.artists_tab.previewTrack.connect(self._preview_track)
        self.artists_tab.refreshTrack.connect(self.on_refresh_track)
        self.artists_tab.bulkRefreshRequested.connect(self.on_refresh_tracks)
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
        self.top_bar.bind_tab_order(self, self.tabs)
        self._register_hotkey_hints()
        self._sync_download_mode_ui()

        # --- Selection counter in status bar ---
        self._selection_label = QLabel("")
        self.statusBar().addPermanentWidget(self._selection_label)
        self.track_list.table.selectionModel().selectionChanged.connect(self._update_selection_counter)
        self.track_list.table.selectionModel().selectionChanged.connect(self._update_selection_actions_bar)
        self.tabs.currentChanged.connect(self._update_selection_actions_bar)

        # initial load
        self._apply_track_filters()
        self.show_queued_notifications()
        self._update_responsive_layout()
        self._apply_startup_view()
        self._update_selection_actions_bar()
        QTimer.singleShot(0, self._maybe_show_first_run_onboarding)

        self._apply_styles()

        # Restore persisted window state (geometry, splitter sizes, tab index)
        self._restore_window_state()

    def _create_selection_actions_bar(self) -> None:
        self.selection_actions_bar = QWidget()
        self.selection_actions_bar.setObjectName("SelectionActionsBar")
        layout = QHBoxLayout(self.selection_actions_bar)
        set_layout_spacing(layout, margins=(SPACE_2, 0, SPACE_2, 0), spacing=SPACE_1)

        self.selection_actions_label = QLabel("No selection")
        self.selection_actions_label.setObjectName("SelectionActionsLabel")
        layout.addWidget(self.selection_actions_label)

        self.selection_action_buttons: list[QPushButton] = []

        def add_button(text: str, tooltip: str, handler) -> QPushButton:
            button = QPushButton(text)
            button.setObjectName("SelectionActionButton")
            button.setToolTip(tooltip)
            button.clicked.connect(handler)
            layout.addWidget(button)
            self.selection_action_buttons.append(button)
            return button

        add_button(
            "Refresh selected",
            "Refresh the selected tracks from their source files on disk.",
            self._refresh_selected_tracks,
        )
        add_button(
            "Download: current mode",
            "Download lyrics for the selected tracks using the global download mode.",
            lambda: self._download_selected_tracks("use_global"),
        )
        add_button(
            "Download synced",
            "Download only synced lyrics for the selected tracks.",
            lambda: self._download_selected_tracks("synced_only"),
        )
        add_button(
            "Download plain",
            "Download only plain lyrics for the selected tracks.",
            lambda: self._download_selected_tracks("plain_only"),
        )
        add_button(
            "Mark instrumental",
            "Mark the selected tracks as instrumental and clear their lyrics.",
            self._mark_selected_tracks_instrumental,
        )
        add_button(
            "Unmark instrumental",
            "Remove the instrumental flag from the selected tracks.",
            self._unmark_selected_tracks_instrumental,
        )
        add_button(
            "Publish synced",
            "Publish synced lyrics from the selected tracks to LRCLIB.",
            lambda: self._publish_selected_tracks(True),
        )
        add_button(
            "Publish plain",
            "Publish plain lyrics from the selected tracks to LRCLIB.",
            lambda: self._publish_selected_tracks(False),
        )
        layout.addStretch(1)

    def _selected_track_ids_for_toolbar(self) -> list[int]:
        if not hasattr(self, "track_list"):
            return []
        return self.track_list.selected_track_ids()

    def _download_selected_tracks(self, mode: str) -> None:
        track_ids = self._selected_track_ids_for_toolbar()
        if track_ids:
            self._on_bulk_download_requested(track_ids, mode)

    def _refresh_selected_tracks(self) -> None:
        track_ids = self._selected_track_ids_for_toolbar()
        if track_ids:
            self.on_refresh_tracks(track_ids)

    def _mark_selected_tracks_instrumental(self) -> None:
        track_ids = self._selected_track_ids_for_toolbar()
        if track_ids:
            self._on_mark_instrumental(track_ids)

    def _unmark_selected_tracks_instrumental(self) -> None:
        track_ids = self._selected_track_ids_for_toolbar()
        if track_ids:
            self._on_unmark_instrumental(track_ids)

    def _publish_selected_tracks(self, is_synced: bool) -> None:
        track_ids = self._selected_track_ids_for_toolbar()
        if track_ids:
            self.publish_history.publish_batch(track_ids, is_synced)

    def _update_selection_actions_bar(self, *_args) -> None:
        if not hasattr(self, "selection_actions_bar"):
            return

        show_toolbar = self.tabs.currentWidget() is self.tracks_tab
        self.selection_actions_bar.setVisible(show_toolbar)
        if not show_toolbar:
            return

        count = len(self._selected_track_ids_for_toolbar())
        has_selection = count > 0
        label = f"Selected tracks: {count}" if has_selection else "Selected tracks: none"
        self.selection_actions_label.setText(label)
        for button in self.selection_action_buttons:
            button.setEnabled(has_selection)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()
        if hasattr(self, "download_overlay"):
            self.download_overlay.sync_to_parent()
        if hasattr(self, "publish_overlay"):
            self.publish_overlay.sync_to_parent()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                if os.path.isdir(path):
                    event.acceptProposedAction()
                    return
                ext = os.path.splitext(path)[1].lower()
                if ext in AUDIO_EXTS:
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event):
        dropped_dirs: list[str] = []
        dropped_files: list[str] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.isdir(path):
                dropped_dirs.append(os.path.normpath(path))
            else:
                ext = os.path.splitext(path)[1].lower()
                if ext in AUDIO_EXTS:
                    dropped_files.append(os.path.normpath(path))

        if not dropped_dirs and not dropped_files:
            return
        event.acceptProposedAction()

        if dropped_dirs:
            self._handle_dropped_directories(dropped_dirs)
        if dropped_files:
            self._handle_dropped_files(dropped_files)

    def _handle_dropped_directories(self, dropped_dirs: list[str]) -> None:
        existing = get_directories(self.app_state.db)
        existing_set = {os.path.normcase(os.path.normpath(d)) for d in existing}
        new_dirs = [d for d in dropped_dirs if os.path.normcase(os.path.normpath(d)) not in existing_set]

        if not new_dirs:
            notify_user(
                self.app_state,
                "Dropped folder(s) are already in the library.",
                "info",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            return

        merged = existing + new_dirs
        set_directories(self.app_state.db, merged)
        label = ", ".join(os.path.basename(d) for d in new_dirs)
        notify_user(
            self.app_state,
            f"Added {len(new_dirs)} folder(s): {label}",
            "success",
            show_status=self._show_status_message,
            status_timeout_ms=4000,
        )
        self.refresh_library()

    def _handle_dropped_files(self, dropped_files: list[str]) -> None:
        config = get_config(self.app_state.db)
        added = 0
        skipped = 0

        # Batch-check existing paths to avoid per-file SELECT
        existing_paths: set[str] = set()
        chunk_size = 500
        for i in range(0, len(dropped_files), chunk_size):
            chunk = dropped_files[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            rows = self.app_state.db.execute(
                f"SELECT file_path FROM tracks WHERE file_path IN ({placeholders})",
                chunk,
            ).fetchall()
            existing_paths.update(row[0] for row in rows)

        with self.app_state.db:
            for file_path in dropped_files:
                if file_path in existing_paths:
                    skipped += 1
                    continue

                fs_track = new_fs_track_from_path(
                    file_path,
                    lyrics_lookup_subdir=config.lyrics_lookup_subdir,
                )
                if fs_track is None:
                    skipped += 1
                    continue
                try:
                    add_track(self.app_state.db, fs_track, commit=False)
                    added += 1
                except sqlite3.Error as exc:
                    logger.warning("Failed to import dropped file %s: %s", file_path, exc)
                    skipped += 1

        if added:
            self._refresh_visible_library_view_after_downloads()
            msg = f"Imported {added} track(s)."
            if skipped:
                msg += f" {skipped} skipped (already in library or unreadable)."
            notify_user(
                self.app_state,
                msg,
                "success",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
        elif skipped:
            notify_user(
                self.app_state,
                "All dropped files are already in the library or could not be read.",
                "info",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._dirty_lyrics_timer.isActive():
            self._dirty_lyrics_timer.stop()
            self._flush_dirty_lyrics()
        # Cancel running workers before shutdown
        if self._ai_sync_worker is not None and self._ai_sync_worker.isRunning():
            self._ai_sync_worker.requestInterruption()
            self._ai_sync_worker.wait(5000)
        self.downloads.cancel()
        if self.scanner is not None and self.scanner.isRunning():
            self.scanner.requestInterruption()
            self.scanner.wait(2000)
        self._save_window_state()
        self._flush_playback_speed()
        self._flush_playback_volume()
        self.navigation.flush_pending_route()
        logging.getLogger().removeHandler(self._ui_log_handler)
        super().closeEvent(event)

    def initialize_player_backend(self) -> None:
        if self.app_state.player is not None:
            return
        try:
            player = Player()
        except (RuntimeError, OSError) as exc:
            logger.warning("Player backend unavailable: %s", exc)
            notify_user(
                self.app_state,
                f"Player unavailable: {exc}",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=5000,
            )
            self.show_queued_notifications()
            return

        self.app_state.player = player
        self.app_state.player.trackChanged.connect(self._on_player_track_changed)
        self.app_state.player.statusChanged.connect(self._on_player_status_changed)
        self.player_bar.attach_player(player)
        for view in self._all_lyrics_views():
            view.set_current_position_provider(player.position_ms)
            player.positionChanged.connect(view.on_player_position)
        self._apply_saved_playback_speed()
        self._apply_saved_playback_volume()

    def _toggle_play_pause(self) -> None:
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox)):
            return
        if self.app_state.player:
            self.app_state.player.toggle_play_pause()

    def _seek_player(self, ms: int) -> None:
        if self.app_state.player:
            self.app_state.player.seek_ms(ms)

    # ------------------ filters ------------------
    def _apply_track_filters(self):
        filters = self.top_bar.filter_values()
        self.track_list.setSearchValue(self.top_bar.search_text())
        self.track_list.setFilters(
            synced=filters["synced"],
            plain=filters["plain"],
            instrumental=filters["instrumental"],
            none_=filters["none"],
            unsaved=filters.get("unsaved", False),
        )
        if self.app_state.player and self.app_state.player.track:
            self.track_list.set_now_playing(self.app_state.player.track.track_id)
        self._update_search_feedback()

    def _schedule_library_search(self):
        self._search_apply_timer.start()

    def _apply_library_search(self):
        current = self.tabs.currentWidget()
        text = self.top_bar.search_text()
        if current is self.tracks_tab:
            self._apply_track_filters()
        elif current is self.albums_page:
            self.albums_tab.setSearchValue(text)
        elif current is self.artists_page:
            self.artists_tab.setSearchValue(text)

    # ------------------ modals ------------------
    def open_config_modal(self):
        dlg = MusicFoldersDialog(self.app_state, self)
        if dlg.exec():
            updated_config = get_config(self.app_state.db)
            self._apply_appearance_preferences(updated_config)
            self._sync_download_mode_ui()
            self.lrclib_browser_tab.set_lrclib_url(
                self._normalize_lrclib_base(updated_config.lrclib_instance)
            )
            for view in self._all_lyrics_views():
                view.set_reaction_delay_ms(updated_config.reaction_delay_ms)
            self._apply_track_filters()
            after_dirs = get_directories(self.app_state.db)
            if dlg.directories_changed and after_dirs:
                self.refresh_library()

    def _sync_download_mode_ui(self) -> None:
        config = get_config(self.app_state.db)
        self.top_bar.set_download_missing_mode(str(config.download_lyrics_mode or "prefer_synced"))

    def open_about_modal(self):
        dlg = AboutDialog(self.app_state, self)
        dlg.exec()

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
            notify_user(
                self.app_state,
                "Add at least one music folder before starting a library scan.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            self.top_bar.set_button_feedback(self.top_bar.btn_refresh, "error")
            QTimer.singleShot(1800, self._reset_refresh_feedback)
            return

        logger.info("Starting library scan across %d folder(s).", len(directories))

        self.scan_row.setVisible(True)
        self.progress_bar.setValue(0)
        self.top_bar.set_actions_label("Scanning Library")
        self.top_bar.set_button_feedback(self.top_bar.btn_refresh, "loading")
        self.scan_label.setText("Scanning…")
        self.scan_details.setText(f"Preparing a scan across {len(directories)} folder(s)…")
        self.btn_cancel_scan.setEnabled(True)

        config = get_config(self.app_state.db)
        self.scanner = LibraryScanner(
            self.app_state.db_path,
            directories,
            excluded_paths=config.scan_excluded_paths,
            excluded_patterns=config.scan_excluded_patterns,
            lyrics_lookup_subdir=config.lyrics_lookup_subdir,
        )
        self.scanner.progress_signal.connect(self._update_scan_progress)
        self.scanner.finished_signal.connect(self._scan_finished)
        self.scanner.start()
        self.top_bar.btn_refresh.setEnabled(False)
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
        kind = normalize_notify_type(getattr(n, "notify_type", "info") or "info")

        msg = getattr(n, "message", "") or ""
        if not msg:
            return

        self._show_deduped_toast(msg, kind, 3000)

    def _on_log_message(self, level: str, message: str) -> None:
        self.log_panel.append_log(level, message)
        normalized_level = (level or "").upper()
        if normalized_level in {"ERROR", "CRITICAL"}:
            self.top_bar.set_logs_checked(True)
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
            notify_user(
                self.app_state,
                msg or "Library scan finished successfully.",
                "success",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
            self.top_bar.set_button_feedback(self.top_bar.btn_refresh, "success")
            logger.info("Library scan finished successfully: %s", msg or "ok")
        else:
            if "cancel" in (msg or "").lower():
                notify_user(
                    self.app_state,
                    msg,
                    "warning",
                    show_status=self._show_status_message,
                    status_timeout_ms=4000,
                )
                self.top_bar.set_button_feedback(self.top_bar.btn_refresh, "idle")
                logger.warning("Library scan cancelled: %s", msg)
            else:
                log_and_notify(
                    self.app_state,
                    logger,
                    logging.ERROR,
                    f"Library scanning failed: {msg}",
                    "error",
                    show_status=self._show_status_message,
                    status_timeout_ms=4000,
                )
                self.top_bar.set_button_feedback(self.top_bar.btn_refresh, "error")

        self.top_bar.btn_refresh.setEnabled(True)
        QTimer.singleShot(1800, self._reset_refresh_feedback)
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
        self._preview_track(track_id)
        if not self.app_state.player:
            notify_user(
                self.app_state,
                "Audio backend is still starting. Please try again in a moment.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=2500,
            )
            return

        self._queue_ids = self.track_list.current_queue_track_ids()
        try:
            self._queue_index = self._queue_ids.index(int(track_id))
        except ValueError:
            self._queue_index = -1

        track = get_track_by_id(self.app_state.db, track_id)


        path = self._track_playback_path(track)
        meta = self._now_playing_meta(track)

        self.app_state.player.play_file(path, meta)

        self._set_track_lyrics_views(track)

    def _preview_track(self, track_id: int) -> None:
        if self._dirty_lyrics_timer.isActive():
            self._dirty_lyrics_timer.stop()
            self._flush_dirty_lyrics()
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
        except (sqlite3.Error, KeyError):
            return
        self._editing_track_id = int(track_id)
        self._set_track_lyrics_views(track)

    def _normalize_dirty_lyrics_state(self, track):
        if not bool(getattr(track, "dirty_lyrics_present", False)):
            return track

        dirty_lrc, dirty_txt = _canonical_lyrics_pair(
            getattr(track, "dirty_lrc_lyrics", None),
            getattr(track, "dirty_txt_lyrics", None),
        )
        saved_lrc, saved_txt = _canonical_lyrics_pair(
            getattr(track, "lrc_lyrics", None),
            getattr(track, "txt_lyrics", None),
        )
        if (dirty_lrc, dirty_txt) != (saved_lrc, saved_txt):
            return track

        try:
            clear_track_dirty_lyrics(self.app_state.db, int(track.id))
            cleaned = get_track_by_id(self.app_state.db, int(track.id))
        except sqlite3.Error as exc:
            logger.warning("Failed to normalize dirty lyrics state for track %s: %s", track.id, exc)
            return track

        self.track_list.set_dirty_lyrics_state(int(track.id), False)
        self.albums_tab.set_dirty_lyrics_state(int(track.id), False)
        self.artists_tab.set_dirty_lyrics_state(int(track.id), False)
        return cleaned

    def on_refresh_track(self, track_id: int) -> None:
        self.on_refresh_tracks([int(track_id)])

    def on_refresh_tracks(self, track_ids: list[int]) -> None:
        track_ids = [int(track_id) for track_id in track_ids if track_id is not None]
        if not track_ids:
            return

        selected_before = set(track_ids)
        refreshed_tracks = {}
        removed_ids: set[int] = set()

        for track_id in track_ids:
            try:
                refreshed = refresh_track_from_file(self.app_state.db, int(track_id))
            except (sqlite3.Error, OSError, ValueError) as exc:
                log_and_notify(
                    self.app_state,
                    logger,
                    logging.ERROR,
                    exception_message("Failed to refresh track from disk", exc),
                    "error",
                    show_status=self._show_status_message,
                    status_timeout_ms=4000,
                )
                return

            if refreshed is None:
                removed_ids.add(int(track_id))
            else:
                refreshed_tracks[int(track_id)] = refreshed

        self._refresh_visible_library_view_after_downloads()
        self.track_list.restore_selection(selected_before - removed_ids)

        current_track_id = self._current_player_track_id()
        if current_track_id in removed_ids:
            self._clear_current_player_track()
        elif current_track_id in refreshed_tracks:
            refreshed = refreshed_tracks[current_track_id]
            self._update_current_player_track_meta(refreshed)
            self._set_track_lyrics_views(refreshed)

        refreshed_count = len(refreshed_tracks)
        removed_count = len(removed_ids)
        if removed_count:
            notify_user(
                self.app_state,
                f"Refreshed {refreshed_count} track(s). Removed {removed_count} missing track(s).",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3500,
            )
            return

        suffix = "s" if refreshed_count != 1 else ""
        self._show_status_message(f"Refreshed {refreshed_count} track{suffix} from disk.", 2500)

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
        self.downloads.start_downloads([int(track_id)], mode_override="use_global")

    def _on_bulk_download_requested(self, track_ids: list[int], mode: str) -> None:
        self.downloads.start_downloads(track_ids, mode_override=mode)

    def _download_missing_lyrics(self) -> None:
        self.downloads.download_missing()

    def _set_track_download_state_all(self, track_id: int, state: str) -> None:
        self.track_list.set_download_state(int(track_id), state)
        self.albums_tab.set_download_state(int(track_id), state)
        self.artists_tab.set_download_state(int(track_id), state)

    def _get_primary_track_download_state(self, track_id: int) -> str:
        return self.track_list.get_download_state(int(track_id))

    def _show_status_message(self, message: str, timeout_ms: int | None = None) -> None:
        if timeout_ms is None:
            self.statusBar().showMessage(message)
            return
        self.statusBar().showMessage(message, int(timeout_ms))

    def _update_selection_counter(self):
        sm = self.track_list.table.selectionModel()
        count = len(sm.selectedRows()) if sm else 0
        if count > 1:
            self._selection_label.setText(f"{count} tracks selected")
        else:
            self._selection_label.setText("")

    def _update_search_feedback(self):
        query = self.top_bar.search_text()
        if query:
            count = self.track_list.model.rowCount()
            has_more = getattr(self.track_list, '_has_more_rows', False)
            suffix = "+" if has_more else ""
            self._show_status_message(f"{count}{suffix} result{'s' if count != 1 else ''} for \"{query}\"")
        else:
            self.statusBar().clearMessage()

    def _current_player_track_id(self) -> int | None:
        if not self.app_state.player or not self.app_state.player.track:
            return None
        return int(self.app_state.player.track.track_id)

    def _track_playback_path(self, track) -> str:
        path = track.file_path
        if os.path.isdir(path):
            path = os.path.join(track.file_path, track.file_name)
        return path

    def _now_playing_meta(self, track) -> NowPlaying:
        return NowPlaying(
            track_id=track.id,
            title=track.title,
            artist=track.artist_name,
            path=self._track_playback_path(track),
            album=track.album_name,
        )

    def _update_current_player_track_meta(self, track) -> None:
        if not self.app_state.player:
            return
        self.app_state.player.track = self._now_playing_meta(track)
        self.app_state.player.trackChanged.emit(self.app_state.player.track)

    def _clear_current_player_track(self) -> None:
        if not self.app_state.player:
            return
        try:
            self.app_state.player.stop()
        except (RuntimeError, AttributeError):
            pass
        self.app_state.player.track = None
        self.app_state.player.trackChanged.emit(None)
        for view in self._all_lyrics_views():
            view.show_none("Select a track to see lyrics")

    def _refresh_visible_library_view_after_downloads(self) -> None:
        current = self.tabs.currentWidget()
        if current is self.tracks_tab:
            route = self.navigation.current_route
            self.track_list.apply_route(route if route.tab == "tracks" else tracks_all())
        elif current is self.albums_page:
            route = self.navigation.current_route
            self.albums_tab.apply_route(route if route.tab == "albums" else LibraryRoute(tab="albums", mode="root"))
        elif current is self.artists_page:
            route = self.navigation.current_route
            self.artists_tab.apply_route(route if route.tab == "artists" else LibraryRoute(tab="artists", mode="root"))

    @staticmethod
    def _lyrics_state_from_track(track) -> LyricsState:
        if track.instrumental or track.lrc_lyrics == "[au: instrumental]":
            return LyricsState.INSTRUMENTAL
        if track.lrc_lyrics:
            return LyricsState.SYNCED
        if track.txt_lyrics:
            return LyricsState.PLAIN
        return LyricsState.NONE

    def _update_single_track_lyrics_state(self, track) -> None:
        state = self._lyrics_state_from_track(track)
        tid = int(track.id)
        self.track_list.update_track_lyrics_state(tid, state)
        self.albums_tab.update_track_lyrics_state(tid, state)
        self.artists_tab.update_track_lyrics_state(tid, state)


    def _on_lyrics_save_requested(self, lrc: str, txt: str):
        track_id = self._editing_track_id
        if track_id is None:
            notify_user(
                self.app_state,
                "Select a track first.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            for view in self._all_lyrics_views():
                view.set_save_feedback("error", "No Track")
            return

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
            self.track_list.set_dirty_lyrics_state(int(track_id), False)
            self.albums_tab.set_dirty_lyrics_state(int(track_id), False)
            self.artists_tab.set_dirty_lyrics_state(int(track_id), False)
            self._update_single_track_lyrics_state(track)
            self._show_status_message("Lyrics saved.", 2500)
            for view in self._all_lyrics_views():
                view.set_save_feedback("success", "Saved")
        except (sqlite3.Error, OSError, ValueError) as exc:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to save lyrics", exc),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
            for view in self._all_lyrics_views():
                view.set_save_feedback("error", "Save Failed")

    def _on_dirty_lyrics_changed(self, lrc: str, txt: str) -> None:
        if self._loading_lyrics_views:
            return
        if self._editing_track_id is None:
            return
        self._pending_dirty_lrc = lrc
        self._pending_dirty_txt = txt
        self._dirty_lyrics_timer.start()

    def _flush_dirty_lyrics(self) -> None:
        track_id = self._editing_track_id
        if track_id is None:
            return
        lrc = self._pending_dirty_lrc
        txt = self._pending_dirty_txt
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            draft_lrc, draft_txt = _canonical_lyrics_pair(lrc, txt)
            saved_lrc, saved_txt = _canonical_lyrics_pair(track.lrc_lyrics, track.txt_lyrics)
            has_dirty = (draft_lrc, draft_txt) != (saved_lrc, saved_txt)
            if has_dirty:
                update_track_dirty_lyrics(self.app_state.db, int(track_id), draft_lrc, draft_txt)
            else:
                clear_track_dirty_lyrics(self.app_state.db, int(track_id))
            self.track_list.set_dirty_lyrics_state(int(track_id), has_dirty)
            self.albums_tab.set_dirty_lyrics_state(int(track_id), has_dirty)
            self.artists_tab.set_dirty_lyrics_state(int(track_id), has_dirty)
            for view in self._all_lyrics_views():
                view._set_dirty_badge(has_dirty)
        except sqlite3.Error as exc:
            logger.warning("Failed to save dirty lyrics draft for track %s: %s", track_id, exc)

    def _on_discard_draft_requested(self) -> None:
        track_id = self._editing_track_id
        if track_id is None:
            return
        try:
            clear_track_dirty_lyrics(self.app_state.db, int(track_id))
            track = get_track_by_id(self.app_state.db, int(track_id))
            self._set_track_lyrics_views(track)
            self.track_list.set_dirty_lyrics_state(int(track_id), False)
            self.albums_tab.set_dirty_lyrics_state(int(track_id), False)
            self.artists_tab.set_dirty_lyrics_state(int(track_id), False)
            self._show_status_message("Draft discarded.", 2500)
        except sqlite3.Error as exc:
            logger.warning("Failed to discard dirty lyrics draft for track %s: %s", track_id, exc)

    def _on_auto_sync_requested(self) -> None:
        from ui.workers.ai_sync_worker import _check_ai_sync_available, AiSyncWorker

        track_id = self._editing_track_id
        if track_id is None:
            notify_user(
                self.app_state,
                "Select a track before auto-syncing.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            return

        if self._ai_sync_worker is not None and self._ai_sync_worker.isRunning():
            notify_user(
                self.app_state,
                "AI sync is already running. Please wait.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            return

        ok, msg = _check_ai_sync_available()
        if not ok:
            notify_user(
                self.app_state,
                msg,
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=6000,
            )
            return

        track = get_track_by_id(self.app_state.db, int(track_id))
        audio_path = self._track_playback_path(track)
        if not os.path.isfile(audio_path):
            notify_user(
                self.app_state,
                "Audio file not found on disk.",
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            return

        # Get plain lyrics if available (prefer dirty draft for alignment)
        plain_lyrics = ""
        if track.dirty_lyrics_present and track.dirty_txt_lyrics:
            plain_lyrics = track.dirty_txt_lyrics
        elif track.txt_lyrics:
            plain_lyrics = track.txt_lyrics

        for view in self._all_lyrics_views():
            view.btn_auto_sync.setEnabled(False)
            view.btn_auto_sync.setText("Syncing...")

        self._show_status_message("AI sync starting...")
        sync_track_id = int(track_id)

        worker = AiSyncWorker(audio_path, plain_lyrics)
        worker.progress.connect(lambda msg: self._show_status_message(msg))
        worker.finished.connect(lambda ok, msg, lrc: self._on_auto_sync_finished(ok, msg, lrc, sync_track_id))
        self._ai_sync_worker = worker
        worker.start()

    def _on_auto_sync_finished(self, ok: bool, msg: str, lrc: str, track_id: int) -> None:
        for view in self._all_lyrics_views():
            view.btn_auto_sync.setEnabled(True)
            view.btn_auto_sync.setText("Auto Sync")

        if not ok:
            notify_user(
                self.app_state,
                msg,
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=5000,
            )
            return

        try:
            from core.utils import plain_text_from_lrc
            plain = plain_text_from_lrc(lrc)
            update_track_dirty_lyrics(self.app_state.db, int(track_id), lrc.strip(), plain.strip())
            if self._editing_track_id == track_id:
                track = get_track_by_id(self.app_state.db, int(track_id))
                self._set_track_lyrics_views(track)
            self.track_list.set_dirty_lyrics_state(int(track_id), True)
            self.albums_tab.set_dirty_lyrics_state(int(track_id), True)
            self.artists_tab.set_dirty_lyrics_state(int(track_id), True)
            notify_user(
                self.app_state,
                msg + " (loaded as draft — save to apply)",
                "success",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
        except (sqlite3.Error, OSError, ValueError) as exc:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to load AI-synced lyrics as draft", exc),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )

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
        result = sync_track_outputs_with_result(track, config)
        if result.sidecar_error is not None:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to export lyrics files", result.sidecar_error),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
        elif result.sidecar_paths:
            self._show_status_message(f"Lyrics exported to {os.path.dirname(result.sidecar_paths[0])}", 3000)

        if result.embed_error is not None:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to embed lyrics", result.embed_error),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
        elif result.embedded:
            self._show_status_message("Lyrics embedded into the audio file.", 3000)

    def _apply_saved_playback_speed(self) -> None:
        config = get_config(self.app_state.db)
        speed = float(config.playback_speed or 1.0)
        if self.app_state.player and hasattr(self.app_state.player, "set_playback_speed"):
            try:
                self.app_state.player.set_playback_speed(speed)
            except (AttributeError, RuntimeError):
                speed = 1.0
        self.player_bar.set_playback_speed_value(speed)

    def _apply_saved_playback_volume(self) -> None:
        config = get_config(self.app_state.db)
        volume = float(config.playback_volume)
        if self.app_state.player and hasattr(self.app_state.player, "set_volume"):
            try:
                self.app_state.player.set_volume(volume)
            except (AttributeError, RuntimeError) as exc:
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

    def _play_selected_or_current(self):
        tid = self.track_list.selected_track_id()
        if tid is not None:
            self.on_play_track(tid)

    def _reset_track_filters(self):
        self.top_bar.reset_track_filters()
        self.track_list.apply_route(tracks_all())
        self._apply_track_filters()

    def _clear_library_search(self) -> None:
        self.top_bar.clear_library_search()
        current = self.tabs.currentWidget()
        if current is self.tracks_tab:
            self._apply_track_filters()
        elif current is self.albums_page:
            self.albums_tab.setSearchValue("")
        elif current is self.artists_page:
            self.artists_tab.setSearchValue("")

    def _download_current_track_lyrics(self):
        track_id = self._editing_track_id
        if track_id is None:
            notify_user(
                self.app_state,
                "Select a track before downloading lyrics.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            return
        self.on_download_lyrics(int(track_id))

    def _search_current_track_lyrics(self):
        track_id = self._editing_track_id
        if track_id is None:
            notify_user(
                self.app_state,
                "Select a track before searching lyrics.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            return

        track = get_track_by_id(self.app_state.db, int(track_id))
        artist = track.artist_name or ""
        title = track.title or ""
        album = track.album_name or ""

        config = get_config(self.app_state.db)
        lrclib_url = self._normalize_lrclib_base(config.lrclib_instance)

        from ui.dialogs.search_lyrics_dialog import SearchLyricsDialog

        dlg = SearchLyricsDialog(
            lrclib_url,
            initial_artist=artist,
            initial_title=title,
            initial_album=album,
            parent=self,
        )

        def _on_lyrics_selected(plain: str, synced: str):
            s_text, p_text = synced.strip(), plain.strip()
            if s_text:
                if not p_text:
                    from core.utils import plain_text_from_lrc
                    p_text = plain_text_from_lrc(s_text)
                update_track_synced_lyrics(self.app_state.db, track_id, s_text, p_text)
            elif p_text:
                update_track_plain_lyrics(self.app_state.db, track_id, p_text)
            if not s_text and not p_text:
                return

            track = get_track_by_id(self.app_state.db, track_id)
            self._sync_track_lyrics_outputs(track)
            self._set_track_lyrics_views(track)
            self._show_status_message("Lyrics applied from search.", 3000)

        dlg.lyricsSelected.connect(_on_lyrics_selected)
        dlg.exec()

    def _export_current_track_sidecars(self):
        track_id = self._editing_track_id
        if track_id is None:
            notify_user(
                self.app_state,
                "Select or start a track before exporting lyrics files.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            for view in self._all_lyrics_views():
                view.set_export_feedback("error", "No Track")
            return
        self._export_track_sidecars(int(track_id))

    def _export_track_sidecars(self, track_id: int):
        for view in self._all_lyrics_views():
            view.set_export_feedback("loading", "Exporting...")
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            if not (track.lrc_lyrics or track.txt_lyrics):
                notify_user(
                    self.app_state,
                    "No lyrics are available to export for this track.",
                    "warning",
                    show_status=self._show_status_message,
                    status_timeout_ms=3000,
                )
                for view in self._all_lyrics_views():
                    view.set_export_feedback("error", "No Lyrics")
                return

            config = get_config(self.app_state.db)
            export_config = replace(config, save_lyrics_sidecars=True)
            result = sync_track_outputs_with_result(track, export_config)
            written_paths = list(result.sidecar_paths)
            if not written_paths:
                notify_user(
                    self.app_state,
                    "No lyrics files were generated for this track.",
                    "warning",
                    show_status=self._show_status_message,
                    status_timeout_ms=3000,
                )
                for view in self._all_lyrics_views():
                    view.set_export_feedback("error", "Nothing Exported")
                return

            output_dir = os.path.dirname(written_paths[0]) or os.path.dirname(track.file_path)
            notify_user(
                self.app_state,
                "Lyrics files generated successfully.",
                "success",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            self._show_status_message(f"Lyrics files exported to {output_dir}", 3000)
            for view in self._all_lyrics_views():
                view.set_export_feedback("success", "Exported")
        except (sqlite3.Error, OSError, ValueError) as exc:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to export lyrics files", exc),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
            for view in self._all_lyrics_views():
                view.set_export_feedback("error", "Export Failed")

    def _save_active_lyrics(self):
        """Ctrl+S: trigger save on the currently visible lyrics editor."""
        current = self.tabs.currentWidget()
        if current is self.tracks_tab:
            view = self.lyrics_view
        elif current is self.albums_page:
            view = self.albums_lyrics_view
        elif current is self.artists_page:
            view = self.artists_lyrics_view
        else:
            return
        if view.btn_save.isEnabled():
            view._emit_save()

    def _focus_search(self):
        """Ctrl+F: focus the search box."""
        self.top_bar.search_box.setFocus()
        self.top_bar.search_box.selectAll()

    def _toggle_hotkey_hints(self) -> None:
        visible = self.hotkey_hints.toggle()
        if hasattr(self, "top_bar"):
            self.top_bar.btn_hotkeys.setChecked(visible)
        self._show_status_message(
            "Keyboard shortcut hints shown." if visible else "Keyboard shortcut hints hidden.",
            1800,
        )

    def _register_hotkey_hints(self) -> None:
        self.hotkey_hints.register(self.top_bar.search_box, "Ctrl+F")
        self.hotkey_hints.register(self.top_bar.btn_hotkeys, "Ctrl+/")
        self.hotkey_hints.register(self.track_list.table, "Enter")
        self.hotkey_hints.register(self.lyrics_view.btn_save, "Ctrl+S")
        self.hotkey_hints.register(self.albums_lyrics_view.btn_save, "Ctrl+S")
        self.hotkey_hints.register(self.artists_lyrics_view.btn_save, "Ctrl+S")
        self.hotkey_hints.register(self.player_bar.btn_prev, "Ctrl+Left")
        self.hotkey_hints.register(self.player_bar.btn_play, "Space")
        self.hotkey_hints.register(self.player_bar.btn_next, "Ctrl+Right")

    def _wire_lyrics_view(self, view: LyricsEditorWidget) -> None:
        view.saveRequested.connect(self._on_lyrics_save_requested)
        view.dirtyDraftChanged.connect(self._on_dirty_lyrics_changed)
        view.discardDraftRequested.connect(self._on_discard_draft_requested)
        view.autoSyncRequested.connect(self._on_auto_sync_requested)
        view.seekRequested.connect(self._seek_player)
        view.downloadRequested.connect(self._download_current_track_lyrics)
        view.searchRequested.connect(self._search_current_track_lyrics)
        view.exportFilesRequested.connect(self._export_current_track_sidecars)

    def _all_lyrics_views(self) -> list[LyricsEditorWidget]:
        return [self.lyrics_view, self.albums_lyrics_view, self.artists_lyrics_view]

    def _set_track_lyrics_views(self, track) -> None:
        track = self._normalize_dirty_lyrics_state(track)
        title = f"{track.artist_name} — {track.title}"
        self._loading_lyrics_views = True
        try:
            for view in self._all_lyrics_views():
                view.set_track_lyrics(
                    title=title,
                    txt_lyrics=track.txt_lyrics,
                    lrc_lyrics=track.lrc_lyrics,
                    instrumental=bool(track.instrumental),
                    dirty_txt_lyrics=getattr(track, "dirty_txt_lyrics", None),
                    dirty_lrc_lyrics=getattr(track, "dirty_lrc_lyrics", None),
                    dirty_lyrics_present=bool(getattr(track, "dirty_lyrics_present", False)),
                )
        finally:
            self._loading_lyrics_views = False

    def _reset_refresh_feedback(self):
        self.top_bar.reset_refresh_feedback(self._refresh_default_label)

    def _update_responsive_layout(self):
        width = max(0, self.width())
        self.top_bar.update_responsive_layout(width)

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

    # --- Window state persistence ---
    def _get_settings(self) -> QSettings:
        return QSettings("PyLrcGet", "PyLrcGet")

    def _save_window_state(self):
        s = self._get_settings()
        s.setValue("window/geometry", self.saveGeometry())
        if hasattr(self, "content_splitter"):
            s.setValue("window/tracks_splitter", self.content_splitter.sizes())
        if hasattr(self, "albums_splitter"):
            s.setValue("window/albums_splitter", self.albums_splitter.sizes())
        if hasattr(self, "artists_splitter"):
            s.setValue("window/artists_splitter", self.artists_splitter.sizes())
        s.setValue("window/tab_index", self.tabs.currentIndex())

    def _restore_window_state(self):
        s = self._get_settings()

        geometry = s.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        for attr, key in [
            ("content_splitter", "window/tracks_splitter"),
            ("albums_splitter", "window/albums_splitter"),
            ("artists_splitter", "window/artists_splitter"),
        ]:
            splitter = getattr(self, attr, None)
            if splitter is None:
                continue
            saved = s.value(key)
            if saved is not None:
                try:
                    sizes = [int(v) for v in saved]
                    if len(sizes) == 2 and all(v > 0 for v in sizes):
                        splitter.setSizes(sizes)
                except (TypeError, ValueError):
                    pass

        tab_index = s.value("window/tab_index")
        if tab_index is not None:
            try:
                idx = int(tab_index)
                if 0 <= idx < self.tabs.count():
                    self.tabs.setCurrentIndex(idx)
            except (TypeError, ValueError):
                pass

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("main_window.qss"))

    def _appearance_scale(self, ui_scale_percent: int) -> float:
        return max(0.85, min(1.5, float(int(ui_scale_percent or 100)) / 100.0))

    def _apply_appearance_preferences(self, config) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_app_theme(
                app,
                config.theme_mode,
                ui_scale_percent=config.ui_scale_percent,
                font_size_mode=config.font_size_mode,
            )

        scale = self._appearance_scale(config.ui_scale_percent)
        if hasattr(self, "player_bar"):
            self.player_bar.set_show_album_art(bool(config.show_album_art))
            self.player_bar.set_ui_scale(scale)
        if hasattr(self, "track_list"):
            self.track_list.set_ui_scale(scale)
        if hasattr(self, "albums_tab"):
            self.albums_tab.set_ui_scale(scale)
        if hasattr(self, "artists_tab"):
            self.artists_tab.set_ui_scale(scale)

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
        self._update_responsive_layout()

    def _clear_breadcrumbs(self) -> None:
        while self.breadcrumbs_layout.count():
            item = self.breadcrumbs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _apply_startup_view(self) -> None:
        config = get_config(self.app_state.db)
        startup_view = str(config.startup_view or "remember_last")
        if startup_view == "albums":
            self.navigate_to(LibraryRoute(tab="albums", mode="root"), record_history=False)
            return
        if startup_view == "artists":
            self.navigate_to(LibraryRoute(tab="artists", mode="root"), record_history=False)
            return
        if startup_view == "my_lrclib":
            self.tabs.setCurrentWidget(self.mylrclib_tab)
            self._clear_breadcrumbs()
            return

        if startup_view == "remember_last" and deserialize_route(config.last_library_route) is not None:
            QTimer.singleShot(0, self.navigation.restore_last_route)
            return

        self.navigate_to(tracks_all(), record_history=False)
        if startup_view == "remember_last":
            # No persisted route to restore yet; keep the default tracks root view.
            return

    def navigate_to(self, route: LibraryRoute, *, record_history: bool = True) -> None:
        self.navigation.navigate_to(route, record_history=record_history)

    def _apply_library_route(self, route: LibraryRoute) -> None:
        if route.tab == "tracks":
            self.top_bar.clear_library_search()
            self.track_list.apply_route(route)
        elif route.tab == "albums":
            self.albums_tab.apply_route(route)
        elif route.tab == "artists":
            self.artists_tab.apply_route(route)
        self._schedule_library_search()

    def _apply_theme(self, theme_mode: str):
        config = get_config(self.app_state.db)
        self._apply_appearance_preferences(replace(config, theme_mode=theme_mode))

    def _on_open_album(self, album_id: int):
        try:
            album = get_album_by_id(self.app_state.db, int(album_id))
            label = self._display_album_name(album.get("album_name", ""))
        except (sqlite3.Error, KeyError, TypeError):
            label = ""
        self.navigate_to(tracks_album((int(album_id),), label=label))
    
    def _on_open_artist(self, artist_id: int):
        try:
            artist = get_artist_by_id(self.app_state.db, int(artist_id))
            label = self._display_artist_name(artist.get("artist_name", ""))
        except (sqlite3.Error, KeyError, TypeError):
            label = ""
        self.navigate_to(tracks_artist((int(artist_id),), label=label))

    def _route_for_current_track_album(self, track_id: int) -> LibraryRoute | None:
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            if track.album_id is None:
                return None
            return tracks_album((int(track.album_id),), label=self._display_album_name(track.album_name))
        except (sqlite3.Error, AttributeError, TypeError):
            return None

    def _route_for_current_track_artist(self, track_id: int) -> LibraryRoute | None:
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
            if track.artist_id is None:
                return None
            return tracks_artist((int(track.artist_id),), label=self._display_artist_name(track.artist_name))
        except (sqlite3.Error, AttributeError, TypeError):
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

        # Preserve selection across refresh
        selected_before = set(track_ids)

        try:
            mark_tracks_instrumental(self.app_state.db, track_ids)
            self._show_status_message(f"Marked {len(track_ids)} track(s) as instrumental.", 3000)
            self._apply_track_filters()
            self.track_list.restore_selection(selected_before)
        except sqlite3.Error as e:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to mark tracks as instrumental", e),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
            return

        self._publish_instrumental_to_lrclib(track_ids)

    def _on_unmark_instrumental(self, track_ids: list[int]):
        track_ids = [int(x) for x in track_ids if x is not None]
        if not track_ids:
            return

        if not self._confirm_bulk("Instrumental", "Unmark instrumental for selected tracks?", len(track_ids)):
            return

        selected_before = set(track_ids)

        try:
            unmark_tracks_instrumental(self.app_state.db, track_ids)
            self._show_status_message(f"Unmarked {len(track_ids)} track(s).", 3000)
            self._apply_track_filters()
            self.track_list.restore_selection(selected_before)
        except sqlite3.Error as e:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to update tracks", e),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )

    def _cancel_bulk_publish(self) -> None:
        worker = getattr(self.publish_history, "_bulk_worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()

    def _update_bg_activity_button(self, *_args) -> None:
        """Show the background-activity button when any overlay is active but hidden."""
        dl_bg = self.download_overlay.is_active and not self.download_overlay.isVisible()
        pub_bg = self.publish_overlay.is_active and not self.publish_overlay.isVisible()
        self.top_bar.btn_bg_activity.setVisible(dl_bg or pub_bg)

    def _reopen_bg_overlay(self) -> None:
        """Re-show whichever overlay is running in the background."""
        if self.download_overlay.is_active:
            self.download_overlay.reopen()
        elif self.publish_overlay.is_active:
            self.publish_overlay.reopen()

    def _publish_instrumental_to_lrclib(self, track_ids: list[int]) -> None:
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Publish Instrumental",
            f"Also mark {len(track_ids)} track(s) as instrumental on LRCLIB?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from ui.workers.bulk_publish_instrumental_worker import BulkPublishInstrumentalWorker

        config = get_config(self.app_state.db)
        lrclib_url = self._normalize_lrclib_base(config.lrclib_instance)

        self._instrumental_worker = BulkPublishInstrumentalWorker(
            db_path=self.app_state.db_path,
            track_ids=track_ids,
            lrclib_instance=lrclib_url,
            parent=self,
        )

        def _on_finished(ok: bool, summary: str, stats: dict):
            self._instrumental_worker = None
            notify_user(
                self.app_state,
                summary,
                "success" if ok else "warning",
                show_status=self._show_status_message,
                status_timeout_ms=5000,
            )

        self._instrumental_worker.finished.connect(_on_finished)
        self._show_status_message(f"Publishing instrumental status for {len(track_ids)} track(s)...", 3000)
        self._instrumental_worker.start()
