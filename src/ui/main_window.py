from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMainWindow,
    QMessageBox,
    QDialog,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QEvent, Qt, QByteArray, QTimer
from PySide6.QtGui import QCloseEvent, QShortcut, QKeySequence
import logging
import os
import sqlite3

from dataclasses import replace

from core.state import Notify
from core.tracklist_models import LyricsState
from db.queries import (
    add_tracks,
    get_album_by_id,
    get_artist_by_id,
    get_config,
    get_directories,
    get_existing_file_paths,
    get_similar_lyrics_track_rows,
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
from ui.controllers.lyrics_download_controller import LyricsDownloadController
from ui.controllers.lyrics_output_controller import LyricsOutputController
from ui.controllers.navigation_controller import NavigationController
from ui.controllers.publish_history_controller import PublishHistoryController
from ui.controllers.track_maintenance_controller import TrackMaintenanceController
from ui.controllers.top_bar_controller import TopBarController
from ui.ai_sync_settings import load_ai_sync_settings
from ui.hotkeys import HOTKEY_SPECS, effective_hotkey_text, parse_hotkey_bindings
from ui.widgets.track_list_widget import TrackListWidget
from ui.dialogs.music_folders_dialog import MusicFoldersDialog
from ui.dialogs.about_dialog import AboutDialog
from ui.dialogs.ai_dependencies_dialog import AIDependenciesDialog
from ui.icon_loader import load_app_icon
from ui.player_bar import PlayerBar
from ui.widgets.lyrics_editor_widget import LyricsEditorWidget
from core.utils import parse_lrc
from ui.dialogs.first_run_dialog import FirstRunDialog
from player.player import NowPlaying, Player
from ui.services.feedback import exception_message, log_and_notify, normalize_notify_type, notify_user
from ui.app_theme import apply_app_theme
from ui.widgets.album_list_widget import AlbumListWidget
from ui.widgets.artist_list_widget import ArtistListWidget
from ui.widgets.album_artist_list_widget import AlbumArtistListWidget
from ui.library_routes import LibraryRoute, deserialize_route, tracks_album, tracks_all, tracks_artist
from ui.spacing import SPACE_1, SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.toast import ToastManager
from ui.widgets.log_panel import LogPanel, QtLogHandler
from ui.services.logging_preferences import apply_logging_verbosity
from ui.widgets.my_lrclib_widget import MyLrclibWidget
from ui.widgets.lrclib_browser_widget import LrclibBrowserWidget
from ui.widgets.download_progress_overlay import DownloadProgressOverlay
from ui.widgets.hotkey_hints import HotkeyHintManager
from ui.main_window_parts import canonical_lyrics_pair, library_actions, library_filters, lyrics_actions, preferences
from ui.constants import (
    DIRTY_LYRICS_FLUSH_MS,
    FEEDBACK_RESET_MS,
    LIBRARY_PANE_MIN_WIDTH,
    LYRICS_PANE_MIN_WIDTH,
    PLAYBACK_SPEED_SAVE_MS,
    PLAYBACK_VOLUME_SAVE_MS,
    SEARCH_DEBOUNCE_MS,
)

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 760


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
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.setAcceptDrops(True)
        self.app_state = app_state

        self._queue_ids: list[int] = []
        self._queue_index: int = -1
        self._editing_track_id: int | None = None
        self._editing_saved_lyrics: tuple[str, str] = ("", "")
        self._loading_lyrics_views = False
        self._refresh_default_label = "Global Actions"
        self._pending_playback_speed: float | None = None
        self._pending_playback_volume: float | None = None
        self._ai_sync_worker = None
        self._track_refresh_worker = None
        self._dirty_lyrics_timer = QTimer(self)
        self._dirty_lyrics_timer.setSingleShot(True)
        self._dirty_lyrics_timer.setInterval(DIRTY_LYRICS_FLUSH_MS)
        self._dirty_lyrics_timer.timeout.connect(self._flush_dirty_lyrics)
        self._pending_dirty_lrc: str = ""
        self._pending_dirty_txt: str = ""
        self._recent_toast_messages: set[str] = set()
        self.hotkey_hints = HotkeyHintManager(self)
        self.scanner = None
        self._playback_speed_save_timer = QTimer(self)
        self._playback_speed_save_timer.setSingleShot(True)
        self._playback_speed_save_timer.setInterval(PLAYBACK_SPEED_SAVE_MS)
        self._playback_speed_save_timer.timeout.connect(self._flush_playback_speed)
        self._playback_volume_save_timer = QTimer(self)
        self._playback_volume_save_timer.setSingleShot(True)
        self._playback_volume_save_timer.setInterval(PLAYBACK_VOLUME_SAVE_MS)
        self._playback_volume_save_timer.timeout.connect(self._flush_playback_volume)
        self._search_apply_timer = QTimer(self)
        self._search_apply_timer.setSingleShot(True)
        self._search_apply_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_apply_timer.timeout.connect(self._apply_library_search)
        self._global_shortcuts: dict[str, QShortcut | None] = {
            "play_pause": None,
            "play_next": None,
            "play_previous": None,
            "save_lyrics": None,
            "focus_search": None,
            "clear_search": None,
            "toggle_hotkey_hints": None,
        }
        # --- Player signals ---
        if self.app_state.player:
            self.app_state.player.trackChanged.connect(self._on_player_track_changed)
            self.app_state.player.statusChanged.connect(self._on_player_status_changed)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        set_layout_spacing(self.layout, margins=SPACE_3, spacing=SPACE_3)

        self.toasts = ToastManager(self.central_widget)
        self.app_state.notification.connect(self._on_notify)
        self._ui_log_handler = QtLogHandler()
        self._ui_log_handler.setLevel(logging.INFO)
        self._ui_log_handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)s  %(name)s: %(message)s", "%H:%M:%S")
        )
        logging.getLogger().addHandler(self._ui_log_handler)
        self._apply_logging_preferences(get_config(self.app_state.db))

        # --- Top controls (search + filters) ---
        self.top_bar = TopBarController(
            on_refresh=self.refresh_library,
            on_download_missing=self._download_missing_lyrics,
            on_export_library=self._export_library_tracks,
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
        (
            self.selection_actions_bar,
            self.selection_actions_label,
            self.selection_action_buttons,
        ) = self._create_selection_actions_bar()

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
        (
            self.albums_selection_actions_bar,
            self.albums_selection_actions_label,
            self.albums_selection_action_buttons,
        ) = self._create_selection_actions_bar()
        albums_layout.addWidget(self.albums_selection_actions_bar)
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
        (
            self.artists_selection_actions_bar,
            self.artists_selection_actions_label,
            self.artists_selection_action_buttons,
        ) = self._create_selection_actions_bar()
        artists_layout.addWidget(self.artists_selection_actions_bar)
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

        # --- Album Artists tab ---
        self.album_artists_tab = AlbumArtistListWidget(self.app_state)
        self.album_artists_page = QWidget()
        album_artists_layout = QVBoxLayout(self.album_artists_page)
        set_layout_spacing(album_artists_layout, margins=0, spacing=SPACE_2)
        (
            self.album_artists_selection_actions_bar,
            self.album_artists_selection_actions_label,
            self.album_artists_selection_action_buttons,
        ) = self._create_selection_actions_bar()
        album_artists_layout.addWidget(self.album_artists_selection_actions_bar)
        self.album_artists_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.album_artists_splitter.addWidget(self.album_artists_tab)
        self.album_artists_lyrics_view = LyricsEditorWidget()
        self.album_artists_lyrics_view.show_none("Select a track to see lyrics")
        self._wire_lyrics_view(self.album_artists_lyrics_view)
        self.album_artists_splitter.addWidget(self.album_artists_lyrics_view)
        self.album_artists_splitter.setStretchFactor(0, 3)
        self.album_artists_splitter.setStretchFactor(1, 2)
        self.album_artists_splitter.setCollapsible(0, False)
        self.album_artists_splitter.setCollapsible(1, False)
        self.album_artists_tab.setMinimumWidth(LIBRARY_PANE_MIN_WIDTH)
        self.album_artists_lyrics_view.setMinimumWidth(LYRICS_PANE_MIN_WIDTH)
        album_artists_layout.addWidget(self.album_artists_splitter)

        self._syncing_library_splitters = False
        self._connect_library_splitter_sync()

        self.mylrclib_tab = MyLrclibWidget(self.app_state)

        self.lrclib_browser_tab = LrclibBrowserWidget(self.app_state)
        self.lrclib_browser_tab.set_lrclib_url(
            self._normalize_lrclib_base(get_config(self.app_state.db).lrclib_instance)
        )

        self.tabs.addTab(self.tracks_tab, "Tracks")
        self.tabs.addTab(self.albums_page, "Albums")
        self.tabs.addTab(self.artists_page, "Artists")
        self.tabs.addTab(self.album_artists_page, "Album Artists")
        self.tabs.addTab(self.lrclib_browser_tab, "LRCLIB Browser")
        self.tabs.addTab(self.mylrclib_tab, "My LRCLIB")
        self.tabs.setAccessibleName("Library navigation tabs")

        self.layout.addWidget(self.tabs)

        # --- PlayerBar ---
        self.player_bar = PlayerBar(self.app_state.player, self)
        self.layout.addWidget(self.player_bar)
        self.toasts.set_bottom_anchor(self.player_bar)
        self.player_bar.set_prev_next_handlers(self.play_prev, self.play_next)
        self.player_bar.playbackSpeedChanged.connect(self._persist_playback_speed)
        self.player_bar.volumeChanged.connect(self._persist_playback_volume)
        self.player_bar.artistNavigationRequested.connect(self._navigate_current_track_artist)
        self.player_bar.albumNavigationRequested.connect(self._navigate_current_track_album)
        self.player_bar.slider.installEventFilter(self)
        for view in self._all_lyrics_views():
            view.set_reaction_delay_ms(get_config(self.app_state.db).reaction_delay_ms)
            view.set_current_position_provider(self.app_state.player.position_ms if self.app_state.player else None)
        self._apply_saved_playback_speed()
        self._apply_saved_playback_volume()
        self._apply_appearance_preferences(get_config(self.app_state.db))

        self.download_overlay = DownloadProgressOverlay(self.central_widget)
        self.download_overlay.sync_to_parent()
        self.export_overlay = DownloadProgressOverlay(self.central_widget, verb="Export")
        self.export_overlay.sync_to_parent()
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
        self.export_overlay.cancelRequested.connect(self._cancel_lyrics_export)
        self.publish_overlay = DownloadProgressOverlay(self.central_widget, verb="Publish")
        self.publish_overlay.sync_to_parent()
        self.scan_overlay = DownloadProgressOverlay(self.central_widget, verb="Scan")
        self.scan_overlay.sync_to_parent()
        self.ai_sync_overlay = DownloadProgressOverlay(self.central_widget, verb="AI Sync")
        self.ai_sync_overlay.sync_to_parent()
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
        self.lyrics_output = LyricsOutputController(
            self.app_state,
            show_status=self._show_status_message,
            lyrics_views=self._all_lyrics_views,
            export_overlay=self.export_overlay,
            parent=self,
        )
        self.track_maintenance = TrackMaintenanceController(
            self.app_state,
            window=self,
            confirm_bulk=self._confirm_bulk,
            active_track_list_widget=self._active_track_list_widget,
            refresh_visible_library_view=self._refresh_visible_library_view_after_downloads,
            show_status=self._show_status_message,
            normalize_lrclib_base=self._normalize_lrclib_base,
            parent=self,
        )
        self.publish_overlay.cancelRequested.connect(self._cancel_bulk_publish)
        self.scan_overlay.cancelRequested.connect(self._cancel_scan)
        self.ai_sync_overlay.cancelRequested.connect(self._cancel_ai_sync)

        # Background activity button — shows when an overlay is minimized
        self.download_overlay.activeChanged.connect(self._update_bg_activity_button)
        self.export_overlay.activeChanged.connect(self._update_bg_activity_button)
        self.publish_overlay.activeChanged.connect(self._update_bg_activity_button)
        self.scan_overlay.activeChanged.connect(self._update_bg_activity_button)
        self.ai_sync_overlay.activeChanged.connect(self._update_bg_activity_button)
        self.download_overlay.minimized.connect(self._update_bg_activity_button)
        self.export_overlay.minimized.connect(self._update_bg_activity_button)
        self.publish_overlay.minimized.connect(self._update_bg_activity_button)
        self.scan_overlay.minimized.connect(self._update_bg_activity_button)
        self.ai_sync_overlay.minimized.connect(self._update_bg_activity_button)
        self.download_overlay.dismissed.connect(self._update_bg_activity_button)
        self.export_overlay.dismissed.connect(self._update_bg_activity_button)
        self.publish_overlay.dismissed.connect(self._update_bg_activity_button)
        self.scan_overlay.dismissed.connect(self._update_bg_activity_button)
        self.ai_sync_overlay.dismissed.connect(self._update_bg_activity_button)
        self.top_bar.btn_bg_activity.clicked.connect(self._reopen_bg_overlay)

        self.lyrics_view.publishSyncedRequested.connect(self.publish_history.publish_synced)
        self.lyrics_view.publishPlainRequested.connect(self.publish_history.publish_plain)
        self.albums_lyrics_view.publishSyncedRequested.connect(self.publish_history.publish_synced)
        self.albums_lyrics_view.publishPlainRequested.connect(self.publish_history.publish_plain)
        self.artists_lyrics_view.publishSyncedRequested.connect(self.publish_history.publish_synced)
        self.artists_lyrics_view.publishPlainRequested.connect(self.publish_history.publish_plain)
        self.album_artists_lyrics_view.publishSyncedRequested.connect(self.publish_history.publish_synced)
        self.album_artists_lyrics_view.publishPlainRequested.connect(self.publish_history.publish_plain)

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
            album_artists_page=self.album_artists_page,
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
        self.track_list.importLyricsFile.connect(self._import_lyrics_file_as_draft)
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
        self.albums_tab.importLyricsFile.connect(self._import_lyrics_file_as_draft)
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
        self.artists_tab.importLyricsFile.connect(self._import_lyrics_file_as_draft)
        self.artists_tab.bulkDownloadRequested.connect(self._on_bulk_download_requested)
        self.artists_tab.navigateRequested.connect(self.navigate_to)
        self.artists_tab.markInstrumental.connect(self._on_mark_instrumental)
        self.artists_tab.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.artists_tab.clearFiltersRequested.connect(self._reset_track_filters)
        self.artists_tab.clearSearchRequested.connect(self._clear_library_search)
        self.artists_tab.refreshLibraryRequested.connect(self.refresh_library)
        self.artists_tab.configureFoldersRequested.connect(self.open_config_modal)
        # --- Album Artists tab signals ---
        self.album_artists_tab.playTrack.connect(self.on_play_track)
        self.album_artists_tab.previewTrack.connect(self._preview_track)
        self.album_artists_tab.refreshTrack.connect(self.on_refresh_track)
        self.album_artists_tab.bulkRefreshRequested.connect(self.on_refresh_tracks)
        self.album_artists_tab.downloadLyrics.connect(self.on_download_lyrics)
        self.album_artists_tab.exportLyricsFiles.connect(self._export_track_sidecars)
        self.album_artists_tab.importLyricsFile.connect(self._import_lyrics_file_as_draft)
        self.album_artists_tab.bulkDownloadRequested.connect(self._on_bulk_download_requested)
        self.album_artists_tab.navigateRequested.connect(self.navigate_to)
        self.album_artists_tab.markInstrumental.connect(self._on_mark_instrumental)
        self.album_artists_tab.unmarkInstrumental.connect(self._on_unmark_instrumental)
        self.album_artists_tab.clearFiltersRequested.connect(self._reset_track_filters)
        self.album_artists_tab.clearSearchRequested.connect(self._clear_library_search)
        self.album_artists_tab.refreshLibraryRequested.connect(self.refresh_library)
        self.album_artists_tab.configureFoldersRequested.connect(self.open_config_modal)
        self.mylrclib_tab.playTrack.connect(self.on_play_track)

        # --- Filters wiring ---
        self.top_bar.bind_tab_order(self, self.tabs)
        self._register_track_play_shortcuts()
        self._apply_hotkey_preferences(get_config(self.app_state.db))
        self._sync_download_mode_ui()

        # --- Selection counter ---
        self._selection_label = QLabel("")
        self.track_list.table.selectionModel().selectionChanged.connect(self._update_selection_counter)
        self.track_list.table.selectionModel().selectionChanged.connect(self._update_selection_actions_bar)
        self.albums_tab.track_list.table.selectionModel().selectionChanged.connect(self._update_selection_actions_bar)
        self.artists_tab.album_browser.track_list.table.selectionModel().selectionChanged.connect(self._update_selection_actions_bar)
        self.album_artists_tab.album_browser.track_list.table.selectionModel().selectionChanged.connect(self._update_selection_actions_bar)
        self.albums_tab.stack.currentChanged.connect(self._update_selection_actions_bar)
        self.artists_tab.stack.currentChanged.connect(self._update_selection_actions_bar)
        self.artists_tab.album_browser.stack.currentChanged.connect(self._update_selection_actions_bar)
        self.album_artists_tab.stack.currentChanged.connect(self._update_selection_actions_bar)
        self.album_artists_tab.album_browser.stack.currentChanged.connect(self._update_selection_actions_bar)
        self.tabs.currentChanged.connect(self._update_selection_actions_bar)
        self.tabs.currentChanged.connect(self._refresh_active_lyrics_view_layout)

        # initial load
        self._apply_track_filters()
        self.show_queued_notifications()
        self._update_responsive_layout()
        self._apply_startup_view()
        self._update_selection_actions_bar()
        self._refresh_active_lyrics_view_layout()
        QTimer.singleShot(0, self._maybe_show_first_run_onboarding)

        self._apply_styles()

        # Restore persisted window state (geometry, splitter sizes, tab index)
        self._restore_window_state()

    def _create_selection_actions_bar(self):
        bar = QWidget()
        bar.setObjectName("SelectionActionsBar")
        bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(bar)
        set_layout_spacing(layout, margins=(SPACE_2, 0, SPACE_2, 0), spacing=SPACE_1)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        label = QLabel("No selection")
        label.setObjectName("SelectionActionsLabel")
        layout.addWidget(label)

        plain_actions = QWidget(bar)
        plain_actions.setObjectName("SelectionActionGroup")
        plain_layout = QHBoxLayout(plain_actions)
        set_layout_spacing(plain_layout, margins=0, spacing=SPACE_1)
        layout.addWidget(plain_actions)

        separator = QWidget(bar)
        separator.setObjectName("SelectionActionSeparator")
        separator.setFixedWidth(1)
        separator.setFixedHeight(20)
        layout.addWidget(separator)

        menu_actions = QWidget(bar)
        menu_actions.setObjectName("SelectionActionMenuGroup")
        menu_layout = QHBoxLayout(menu_actions)
        set_layout_spacing(menu_layout, margins=0, spacing=SPACE_1)
        layout.addWidget(menu_actions)

        buttons: list[QWidget] = []

        def add_button(text: str, tooltip: str, handler) -> QPushButton:
            button = QPushButton(text)
            button.setObjectName("SelectionActionButton")
            button.setToolTip(tooltip)
            button.clicked.connect(handler)
            plain_layout.addWidget(button)
            buttons.append(button)
            return button

        def add_menu_button(text: str, tooltip: str, menu_items: list[tuple[str, object]]) -> QToolButton:
            button = QToolButton()
            button.setObjectName("SelectionActionMenuButton")
            button.setText(f"{text} v")
            button.setToolTip(tooltip)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

            menu = QMenu(button)
            for item_text, item_handler in menu_items:
                action = menu.addAction(item_text)
                action.triggered.connect(item_handler)
            button.setMenu(menu)

            menu_layout.addWidget(button)
            buttons.append(button)
            return button

        add_button(
            "Refresh",
            "Refresh the selected tracks from their source files on disk.",
            self._refresh_selected_tracks,
        )
        add_menu_button(
            "Download",
            "Download lyrics for the selected tracks using the global download mode.",
            [
                ("Use current mode", lambda: self._download_selected_tracks("use_global")),
                ("Synced only", lambda: self._download_selected_tracks("synced_only")),
                ("Plain only", lambda: self._download_selected_tracks("plain_only")),
            ],
        )
        add_button(
            "Export",
            "Export lyrics files for the selected tracks using the current sidecar settings.",
            self._export_selected_tracks,
        )
        add_menu_button(
            "Instrumental",
            "Mark or unmark the selected tracks as instrumental.",
            [
                ("Mark instrumental", self._mark_selected_tracks_instrumental),
                ("Unmark instrumental", self._unmark_selected_tracks_instrumental),
            ],
        )
        add_menu_button(
            "Publish",
            "Publish lyrics from the selected tracks to LRCLIB.",
            [
                ("Publish synced", lambda: self._publish_selected_tracks(True)),
                ("Publish plain", lambda: self._publish_selected_tracks(False)),
            ],
        )
        layout.addStretch(1)
        bar.setMaximumHeight(44)
        bar.hide()
        return bar, label, buttons

    def _selection_bar_targets(self):
        return [
            (self.selection_actions_bar, self.selection_actions_label, self.selection_action_buttons, self.track_list),
            (
                self.albums_selection_actions_bar,
                self.albums_selection_actions_label,
                self.albums_selection_action_buttons,
                self.albums_tab.track_list,
            ),
            (
                self.artists_selection_actions_bar,
                self.artists_selection_actions_label,
                self.artists_selection_action_buttons,
                self.artists_tab.album_browser.track_list,
            ),
        ]

    def _selected_track_ids_for_toolbar(self) -> list[int]:
        track_list = self._active_track_list_widget() if hasattr(self, "track_list") else None
        if track_list is None:
            return []
        return track_list.selected_track_ids()

    def _download_selected_tracks(self, mode: str) -> None:
        track_ids = self._selected_track_ids_for_toolbar()
        if track_ids:
            self._on_bulk_download_requested(track_ids, mode)

    def _refresh_selected_tracks(self) -> None:
        track_ids = self._selected_track_ids_for_toolbar()
        if track_ids:
            self.on_refresh_tracks(track_ids)

    def _export_selected_tracks(self) -> None:
        track_ids = self._selected_track_ids_for_toolbar()
        if not track_ids:
            return
        for view in self._all_lyrics_views():
            view.set_export_feedback("loading", "Exporting...")
        if not self._export_track_ids(track_ids):
            for view in self._all_lyrics_views():
                view.set_export_feedback("error", "Export Busy")

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

        count = len(self._selected_track_ids_for_toolbar())
        has_selection = count > 0
        label = f"Selected tracks: {count}" if has_selection else "Selected tracks: none"
        active_track_list = self._active_track_list_widget()
        for bar, bar_label, buttons, track_list in self._selection_bar_targets():
            is_active = track_list is active_track_list
            bar.setVisible(is_active)
            if not is_active:
                continue
            bar_label.setText(label)
            for button in buttons:
                button.setEnabled(has_selection)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()
        if hasattr(self, "download_overlay"):
            self.download_overlay.sync_to_parent()
        if hasattr(self, "publish_overlay"):
            self.publish_overlay.sync_to_parent()
        if hasattr(self, "scan_overlay"):
            self.scan_overlay.sync_to_parent()
        if hasattr(self, "ai_sync_overlay"):
            self.ai_sync_overlay.sync_to_parent()
        if hasattr(self, "toasts"):
            self.toasts.sync_to_parent()

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
                if ext in AUDIO_EXTS or ext in {".lrc", ".txt"}:
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event):
        dropped_dirs: list[str] = []
        dropped_files: list[str] = []
        dropped_lyrics: list[str] = []
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
                elif ext in {".lrc", ".txt"}:
                    dropped_lyrics.append(os.path.normpath(path))

        if not dropped_dirs and not dropped_files and not dropped_lyrics:
            return
        event.acceptProposedAction()

        if dropped_dirs:
            self._handle_dropped_directories(dropped_dirs)
        if dropped_files:
            self._handle_dropped_files(dropped_files)
        if dropped_lyrics and self._editing_track_id is not None:
            self._import_lyrics_file_as_draft(int(self._editing_track_id), dropped_lyrics[0])

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
        existing_paths = get_existing_file_paths(self.app_state.db, dropped_files)

        fs_tracks: list = []
        for file_path in dropped_files:
            if file_path in existing_paths:
                skipped += 1
                continue

            fs_track = new_fs_track_from_path(
                file_path,
                lyrics_lookup_subdir=config.lyrics_lookup_subdir,
                lyrics_file_pattern=config.lyrics_file_pattern,
                scan_lyrics_source_mode=getattr(config, "scan_lyrics_source_mode", "both"),
            )
            if fs_track is None:
                skipped += 1
                continue
            fs_tracks.append(fs_track)

        if fs_tracks:
            try:
                add_tracks(self.app_state.db, fs_tracks)
                added = len(fs_tracks)
            except sqlite3.Error as exc:
                logger.warning("Failed to import dropped files: %s", exc)
                skipped += len(fs_tracks)

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

    def _import_lyrics_file_as_draft(self, track_id: int, file_path: str) -> None:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in {".lrc", ".txt"}:
            return

        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as handle:
                text = handle.read().strip()
        except OSError as exc:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to read lyrics file", exc),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
            return

        if not text:
            notify_user(
                self.app_state,
                "Lyrics file is empty.",
                "warning",
                show_status=self._show_status_message,
                status_timeout_ms=3000,
            )
            return

        if ext == ".lrc":
            if not parse_lrc(text):
                notify_user(
                    self.app_state,
                    "The dropped .lrc file does not contain valid timestamps.",
                    "warning",
                    show_status=self._show_status_message,
                    status_timeout_ms=4000,
                )
                return
            lrc, plain = canonical_lyrics_pair(text, "")
        else:
            lrc, plain = "", text

        try:
            update_track_dirty_lyrics(self.app_state.db, int(track_id), lrc, plain)
            track = get_track_by_id(self.app_state.db, int(track_id))
            if self._editing_track_id == int(track_id):
                self._set_track_lyrics_views(track)
            self.track_list.set_dirty_lyrics_state(int(track_id), True)
            self.albums_tab.set_dirty_lyrics_state(int(track_id), True)
            self.artists_tab.set_dirty_lyrics_state(int(track_id), True)
            self.album_artists_tab.set_dirty_lyrics_state(int(track_id), True)
            notify_user(
                self.app_state,
                f"Loaded {os.path.basename(file_path)} as an unsaved lyrics draft.",
                "success",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
        except (sqlite3.Error, ValueError) as exc:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to load lyrics file as draft", exc),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._dirty_lyrics_timer.isActive():
            self._dirty_lyrics_timer.stop()
            self._flush_dirty_lyrics()
        # Cancel running workers before shutdown
        if self._ai_sync_worker is not None and self._ai_sync_worker.isRunning():
            self._ai_sync_worker.requestInterruption()
            if not self._ai_sync_worker.wait(5000):
                notify_user(
                    self.app_state,
                    "AI sync is still shutting down. Please try closing again in a moment.",
                    "warning",
                    show_status=self._show_status_message,
                    status_timeout_ms=4000,
                )
                event.ignore()
                return
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
        from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)):
            return
        if self.app_state.player:
            self.app_state.player.toggle_play_pause()

    def _seek_player(self, ms: int) -> None:
        if self.app_state.player:
            self.app_state.player.seek_ms(ms)

    # ------------------ filters ------------------
    def _apply_track_filters(self):
        library_filters.apply_track_filters(self)
        self._validate_current_selected_track()

    def _schedule_library_search(self):
        library_filters.schedule_library_search(self)

    def _apply_library_search(self):
        library_filters.apply_library_search(self)

    # ------------------ modals ------------------
    def open_config_modal(self):
        dlg = MusicFoldersDialog(self.app_state, self)
        if dlg.exec():
            updated_config = get_config(self.app_state.db)
            self._apply_appearance_preferences(updated_config)
            self._apply_logging_preferences(updated_config)
            self._apply_hotkey_preferences(updated_config)
            self._sync_download_mode_ui()
            self.lrclib_browser_tab.set_lrclib_url(
                self._normalize_lrclib_base(updated_config.lrclib_instance)
            )
            for view in self._all_lyrics_views():
                view.set_reaction_delay_ms(updated_config.reaction_delay_ms)
            after_dirs = get_directories(self.app_state.db)
            if dlg.directories_changed:
                if after_dirs:
                    self.refresh_library()
                else:
                    from db.database import purge_all_tracks
                    purge_all_tracks(self.app_state.db)
                    self._apply_track_filters()
            else:
                self._apply_track_filters()
            self._validate_current_selected_track()

    def _sync_download_mode_ui(self) -> None:
        config = get_config(self.app_state.db)
        self.top_bar.set_download_missing_mode(str(config.download_lyrics_mode or "prefer_synced"))

    def _apply_logging_preferences(self, config) -> None:
        level = apply_logging_verbosity(getattr(config, "logging_verbosity", "info"))
        self._ui_log_handler.setLevel(level)
        logger.debug(
            "Applied logging verbosity: %s (%s)",
            getattr(config, "logging_verbosity", "info"),
            logging.getLevelName(level),
        )

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
        library_actions.refresh_library(self)

    def _update_scan_progress(self, scanned: int, total: int, current_path: str, elapsed_s: float):
        library_actions.update_scan_progress(self, scanned, total, current_path, elapsed_s)

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
            self._refresh_hotkey_hints_after_layout()
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
        library_actions.scan_finished(self, ok, msg)

    def _cancel_scan(self):
        library_actions.cancel_scan(self)

    def _toggle_logs_panel(self, checked: bool) -> None:
        self.log_panel.setVisible(bool(checked))
        self._refresh_hotkey_hints_after_layout()

    def _refresh_hotkey_hints_after_layout(self) -> None:
        if not getattr(self, "hotkey_hints", None) or not self.hotkey_hints.is_visible:
            return
        QTimer.singleShot(0, self.hotkey_hints.refresh_positions)
        QTimer.singleShot(50, self.hotkey_hints.refresh_positions)

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

    def _preview_track(self, track_id: int | None) -> None:
        if track_id is None:
            self._clear_selected_track_views()
            return
        if self._dirty_lyrics_timer.isActive():
            self._dirty_lyrics_timer.stop()
            self._flush_dirty_lyrics()
        try:
            track = get_track_by_id(self.app_state.db, int(track_id))
        except (sqlite3.Error, KeyError, ValueError):
            self._clear_selected_track_views()
            return
        self._editing_track_id = int(track_id)
        self._editing_saved_lyrics = canonical_lyrics_pair(track.lrc_lyrics, track.txt_lyrics)
        self._set_track_lyrics_views(track)

    def _validate_current_selected_track(self) -> None:
        editing_id = getattr(self, "_editing_track_id", None)
        if editing_id is None:
            return
        try:
            get_track_by_id(self.app_state.db, int(editing_id))
        except (sqlite3.Error, KeyError, ValueError, AttributeError):
            self._clear_selected_track_views()

    def _clear_selected_track_views(self) -> None:
        self._editing_track_id = None
        self._editing_saved_lyrics = ("", "")
        for view in self._all_lyrics_views():
            view.set_track_lyrics(
                title="No Track Selected",
                txt_lyrics="",
                lrc_lyrics="",
                instrumental=False,
                dirty_txt_lyrics=None,
                dirty_lrc_lyrics=None,
                dirty_lyrics_present=False,
            )
        for track_list in (
            getattr(self, "track_list", None),
            getattr(getattr(self, "albums_tab", None), "track_list", None),
            getattr(getattr(getattr(self, "artists_tab", None), "album_browser", None), "track_list", None),
        ):
            if track_list and hasattr(track_list, "table") and track_list.table.selectionModel():
                track_list.table.selectionModel().clearSelection()

    def _normalize_dirty_lyrics_state(self, track):
        if not bool(getattr(track, "dirty_lyrics_present", False)):
            return track

        dirty_lrc, dirty_txt = canonical_lyrics_pair(
            getattr(track, "dirty_lrc_lyrics", None),
            getattr(track, "dirty_txt_lyrics", None),
        )
        saved_lrc, saved_txt = canonical_lyrics_pair(
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
        self.album_artists_tab.set_dirty_lyrics_state(int(track.id), False)
        return cleaned

    def on_refresh_track(self, track_id: int) -> None:
        self.on_refresh_tracks([int(track_id)])

    def on_refresh_tracks(self, track_ids: list[int]) -> None:
        library_actions.refresh_tracks(self, track_ids)

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
        if hasattr(self, "album_artists_tab") and hasattr(self.album_artists_tab, "album_browser"):
            self.album_artists_tab.album_browser.track_list.set_now_playing(now_playing.track_id if now_playing else None)

    def _on_player_status_changed(self, status):
        # No text-based status display currently needed
        pass

    # ------------------ lyrics download & save ------------------
    def on_download_lyrics(self, track_id: int):
        library_actions.on_download_lyrics(self, track_id)

    def _on_bulk_download_requested(self, track_ids: list[int], mode: str) -> None:
        library_actions.on_bulk_download_requested(self, track_ids, mode)

    def _download_missing_lyrics(self) -> None:
        library_actions.download_missing_lyrics(self)

    def _set_track_download_state_all(self, track_id: int, state: str) -> None:
        library_actions.set_track_download_state_all(self, track_id, state)

    def _get_primary_track_download_state(self, track_id: int) -> str:
        return library_actions.get_primary_track_download_state(self, track_id)

    def _show_status_message(self, message: str, timeout_ms: int | None = None) -> None:
        message = str(message or "").strip()
        if not message:
            self._clear_status_message()
            return
        self.toasts.show_status(message, timeout_ms)

    def _clear_status_message(self) -> None:
        self.toasts.clear_status()

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
            self._clear_status_message()

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
        elif current is self.album_artists_page:
            route = self.navigation.current_route
            self.album_artists_tab.apply_route(route if route.tab == "album_artists" else LibraryRoute(tab="album_artists", mode="root"))

    def _active_track_list_widget(self):
        current = self.tabs.currentWidget()
        if current is self.tracks_tab:
            return self.track_list
        if current is self.albums_page and self.albums_tab.stack.currentWidget() is self.albums_tab.track_list:
            return self.albums_tab.track_list
        if current is self.artists_page and self.artists_tab.stack.currentWidget() is self.artists_tab.album_browser:
            album_browser = self.artists_tab.album_browser
            if album_browser.stack.currentWidget() is album_browser.track_list:
                return album_browser.track_list
        if current is self.album_artists_page and self.album_artists_tab.stack.currentWidget() is self.album_artists_tab.album_browser:
            album_browser = self.album_artists_tab.album_browser
            if album_browser.stack.currentWidget() is album_browser.track_list:
                return album_browser.track_list
        return None

    @staticmethod
    def _lyrics_state_from_track(track) -> LyricsState:
        return lyrics_actions.lyrics_state_from_track(track)

    def _update_single_track_lyrics_state(self, track) -> None:
        lyrics_actions.update_single_track_lyrics_state(self, track)


    def _on_lyrics_save_requested(self, lrc: str, txt: str):
        lyrics_actions.on_lyrics_save_requested(self, lrc, txt)

    def _on_propagate_lyrics_requested(self, lrc: str, txt: str) -> None:
        lyrics_actions.on_propagate_lyrics_requested(self, lrc, txt)

    def _save_lyrics_text_to_track(self, track_id: int, lrc: str, txt: str):
        return lyrics_actions.save_lyrics_text_to_track(self, track_id, lrc, txt)

    def _mark_track_lyrics_clean(self, track) -> None:
        lyrics_actions.mark_track_lyrics_clean(self, track)

    def _on_dirty_lyrics_changed(self, lrc: str, txt: str) -> None:
        lyrics_actions.on_dirty_lyrics_changed(self, lrc, txt)

    def _flush_dirty_lyrics(self) -> None:
        lyrics_actions.flush_dirty_lyrics(self)

    def _on_discard_draft_requested(self) -> None:
        lyrics_actions.on_discard_draft_requested(self)

    def _on_auto_sync_requested(self) -> None:
        from ui.workers.ai_sync_worker import _check_ai_sync_available, AiSyncWorker, get_missing_ai_dependencies

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
            dlg = AIDependenciesDialog(get_missing_ai_dependencies(), msg, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                ok_after_install, _ = _check_ai_sync_available()
                if ok_after_install:
                    self._on_auto_sync_requested()
            return

        track = get_track_by_id(self.app_state.db, int(track_id))
        ai_sync_settings = load_ai_sync_settings(get_config(self.app_state.db).ui_state_json)
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

        active_view = self._active_lyrics_view()
        # Get plain lyrics source in strict priority:
        # active editor -> dirty draft -> saved plain -> plain derived from saved LRC
        plain_lyrics = active_view.ai_sync_plain_source() if active_view is not None else ""
        if not plain_lyrics:
            if track.dirty_lyrics_present and track.dirty_txt_lyrics:
                plain_lyrics = track.dirty_txt_lyrics
            elif track.txt_lyrics:
                plain_lyrics = track.txt_lyrics
            elif track.lrc_lyrics:
                from core.utils import plain_text_from_lrc
                plain_lyrics = plain_text_from_lrc(track.lrc_lyrics)
        manual_anchors = active_view.ai_sync_manual_anchors() if active_view is not None else []

        for view in self._all_lyrics_views():
            view.btn_auto_sync.setEnabled(False)
            view.btn_auto_sync.setText("Syncing...")

        self.ai_sync_overlay.start_batch("Current track", 8)
        self.ai_sync_overlay.update_progress(0, 8, "AI Auto-Sync", "Preparing AI sync pipeline…")
        self._show_status_message("AI sync starting...")
        sync_track_id = int(track_id)

        worker = AiSyncWorker(
            audio_path,
            plain_lyrics,
            manual_anchors=manual_anchors,
            whisper_model="base",
            device=str(ai_sync_settings.get("device") or "auto"),
            language=str(ai_sync_settings.get("language") or "auto"),
            enable_fuzzy=bool(ai_sync_settings.get("enable_fuzzy", True)),
            fuzzy_threshold=int(ai_sync_settings.get("fuzzy_threshold", 60)),
            enable_demucs_candidate=bool(
                ai_sync_settings.get("enable_demucs_candidate", True)
            ),
        )
        worker.progress.connect(self._on_ai_sync_progress)
        worker.completed.connect(
            lambda ok, msg, lrc, sync_worker=worker: self._on_auto_sync_finished(
                ok,
                msg,
                lrc,
                sync_track_id,
                cancelled_worker=sync_worker is getattr(
                    self, "_ai_sync_cancelled_worker", None
                ),
            )
        )
        worker.finished.connect(lambda: self._on_ai_sync_thread_finished(worker))
        self._ai_sync_worker = worker
        worker.start()

    def _on_auto_sync_finished(
        self,
        ok: bool,
        msg: str,
        lrc: str,
        track_id: int,
        *,
        cancelled_worker: bool = False,
    ) -> None:
        if cancelled_worker:
            return

        for view in self._all_lyrics_views():
            view.btn_auto_sync.setEnabled(True)
            view.btn_auto_sync.setText("Auto Sync")

        overlay = getattr(self, "ai_sync_overlay", None)
        if overlay is not None:
            overlay.append_result("AI Auto-Sync", msg, ok)
            overlay.finish_batch(
                "AI sync cancelled." if msg == "Cancelled." else msg,
                cancelled=(msg == "Cancelled."),
            )
            overlay.queue_auto_close(2200)

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
            track = get_track_by_id(self.app_state.db, int(track_id))
            plain_source = ""
            if track.dirty_lyrics_present and track.dirty_txt_lyrics:
                plain_source = (track.dirty_txt_lyrics or "").strip()
            elif track.txt_lyrics:
                plain_source = (track.txt_lyrics or "").strip()
            plain = plain_source if plain_source else plain_text_from_lrc(lrc)
            update_track_dirty_lyrics(self.app_state.db, int(track_id), lrc.strip(), plain.strip())
            if self._editing_track_id == track_id:
                refreshed_track = get_track_by_id(self.app_state.db, int(track_id))
                self._set_track_lyrics_views(refreshed_track)
            self.track_list.set_dirty_lyrics_state(int(track_id), True)
            self.albums_tab.set_dirty_lyrics_state(int(track_id), True)
            self.artists_tab.set_dirty_lyrics_state(int(track_id), True)
            self.album_artists_tab.set_dirty_lyrics_state(int(track_id), True)
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

    def _on_ai_sync_thread_finished(self, worker) -> None:
        was_cancelled = getattr(self, "_ai_sync_cancelled_worker", None) is worker
        if self._ai_sync_worker is worker:
            self._ai_sync_worker = None
        if getattr(self, "_ai_sync_cancelled_worker", None) is worker:
            self._ai_sync_cancelled_worker = None
        if was_cancelled:
            for view in self._all_lyrics_views():
                view.btn_auto_sync.setEnabled(True)
                view.btn_auto_sync.setText("Auto Sync")

    # ------------------ helpers ------------------
    def _on_ai_sync_progress(self, message: str) -> None:
        raw_message = str(message or "").strip()
        display_message = raw_message
        total = 8
        step = 0
        marker = "__AI_SYNC_PROGRESS__|"
        if raw_message.startswith(marker):
            payload = raw_message[len(marker):]
            parts = payload.split("|", 2)
            if len(parts) == 3:
                try:
                    step = max(0, int(parts[0]))
                    total = max(1, int(parts[1]))
                    display_message = parts[2].strip() or "Working…"
                except (TypeError, ValueError):
                    step = 0
                    total = 8
                    display_message = raw_message
        else:
            lowered = raw_message.lower()
            if "loading audio" in lowered:
                step = 1
            elif "whisperx model" in lowered or "asr model" in lowered:
                step = 2
            elif "transcribing" in lowered:
                step = 3
            elif "forced alignment" in lowered or "aligning detected words" in lowered:
                step = 4
            elif "coverage" in lowered or "relaxed vad" in lowered:
                step = 5
            elif "building lrc" in lowered or "building synced" in lowered:
                step = 6
            elif "aligning lyric lines" in lowered:
                step = 7
            elif "finalizing" in lowered:
                step = 8

        self._show_status_message(display_message)
        overlay = getattr(self, "ai_sync_overlay", None)
        if overlay is None:
            return
        overlay.update_progress(step, total, "AI Auto-Sync", display_message)

        # Watchdog: if building LRC (final step) takes too long, show a soft timeout message
        try:
            # cancel previous watchdog if any when not in building step
            if step != 4 and getattr(self, "_ai_sync_watchdog_timer", None):
                try:
                    self._ai_sync_watchdog_timer.stop()
                except Exception:
                    pass
                self._ai_sync_watchdog_timer = None

            if step >= max(1, total - 2):
                # start a 2-minute watchdog that nudges the overlay if not completed
                if not getattr(self, "_ai_sync_watchdog_timer", None):
                    timer = QTimer(self)
                    timer.setSingleShot(True)
                    timer.setInterval(120000)  # 2 minutes
                    def _on_watchdog():
                        ov = getattr(self, "ai_sync_overlay", None)
                        if ov is not None:
                            ov.update_progress(-1, total, "AI Auto-Sync", "Still processing final alignment — you can cancel")
                    timer.timeout.connect(_on_watchdog)
                    timer.start()
                    self._ai_sync_watchdog_timer = timer
        except Exception:
            # non-fatal; overlay is advisory
            pass

    def _cancel_ai_sync(self) -> None:
        worker = getattr(self, "_ai_sync_worker", None)
        if worker is not None and worker.isRunning():
            self._ai_sync_cancelled_worker = worker
            worker.requestInterruption()
            overlay = getattr(self, "ai_sync_overlay", None)
            if overlay is not None:
                overlay.finish_batch("AI sync cancelled.", cancelled=True)
                overlay.queue_auto_close(1200)

    def _cancel_lyrics_export(self) -> None:
        controller = getattr(self, "lyrics_output", None)
        if controller is not None:
            controller.cancel_export()

    def _normalize_lrclib_base(self, url: str) -> str:
        u = (url or "").strip().rstrip("/")
        if not u:
            u = "https://lrclib.net"
        if not u.endswith("/api"):
            u += "/api"
        return u

    def _sync_track_lyrics_outputs(self, track) -> bool:
        return self.lyrics_output.sync_tracks(
            [int(track.id)],
            on_item_finished=self._on_track_lyrics_output_synced,
            on_finished=self._on_track_lyrics_output_sync_finished,
        )

    def _on_track_lyrics_output_synced(self, track_id: int, payload: dict) -> None:
        if payload.get("sidecar_error") is not None:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to export lyrics files", payload["sidecar_error"]),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
            return

        sidecar_paths = payload.get("sidecar_paths") or ()
        if sidecar_paths:
            self._show_status_message(f"Lyrics exported to {os.path.dirname(sidecar_paths[0])}", 3000)

        if payload.get("embed_error") is not None:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to embed lyrics", payload["embed_error"]),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
        elif payload.get("embedded"):
            self._show_status_message("Lyrics embedded into the audio file.", 3000)

    def _on_track_lyrics_output_sync_finished(self, ok: bool, summary: str, stats: dict) -> None:
        del ok, stats
        if summary:
            self._show_status_message(summary, 2500)

    def _on_lyrics_exported(self, track_id: int, payload: dict) -> None:
        del track_id
        if payload.get("sidecar_error") is not None:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to export lyrics files", payload["sidecar_error"]),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
            return
        sidecar_paths = payload.get("sidecar_paths") or ()
        if sidecar_paths:
            self._show_status_message(f"Lyrics exported to {os.path.dirname(sidecar_paths[0])}", 3000)
        if payload.get("embed_error") is not None:
            log_and_notify(
                self.app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to embed lyrics", payload["embed_error"]),
                "error",
                show_status=self._show_status_message,
                status_timeout_ms=4000,
            )
        elif payload.get("embedded"):
            self._show_status_message("Lyrics embedded into the audio file.", 3000)

    def _on_lyrics_export_finished(self, ok: bool, summary: str, stats: dict) -> None:
        del ok
        cancelled = bool(stats.get("cancelled"))
        failed = int(stats.get("failed", 0))
        state = "error" if cancelled or failed else "success"
        label = "Cancelled" if cancelled else "Exported" if not failed else "Partial"
        for view in self._all_lyrics_views():
            view.set_export_feedback(state, label)
        if summary:
            self._show_status_message(summary, 2500)

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

    def _register_track_play_shortcuts(self) -> None:
        track_lists = [
            self.track_list,
            self.albums_tab.track_list,
            self.artists_tab.album_browser.track_list,
            self.album_artists_tab.album_browser.track_list,
        ]
        for track_list in track_lists:
            for key in ("Return", "Enter"):
                shortcut = QShortcut(QKeySequence(key), track_list.table)
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                shortcut.activated.connect(
                    lambda checked=False, source=track_list: self._play_selected_from_track_list(source)
                )

    def _play_selected_from_track_list(self, track_list) -> None:
        tid = track_list.selected_track_id()
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
        elif current is self.album_artists_page:
            self.album_artists_tab.setSearchValue("")
    def _download_current_track_lyrics(self):
        lyrics_actions.download_current_track_lyrics(self)

    def _search_current_track_lyrics(self):
        lyrics_actions.search_current_track_lyrics(self)

    def _export_current_track_sidecars(self):
        lyrics_actions.export_current_track_sidecars(self)

    def _export_library_tracks(self) -> None:
        widget = self._active_track_list_widget()
        if widget is None:
            self._show_status_message("Select a track list first.")
            return
        self._export_tracks_from_widget(widget)

    def _export_track_sidecars(self, track_id: int):
        self._export_track_ids([int(track_id)])

    def _export_track_ids(self, track_ids: list[int]) -> bool:
        export_config = self._export_config_for_sidecars()
        return self.lyrics_output.export_tracks(
            [int(track_id) for track_id in track_ids],
            export_config=export_config,
            on_item_finished=self._on_lyrics_exported,
            on_finished=self._on_lyrics_export_finished,
        )

    def _export_tracks_from_widget(self, widget) -> bool:
        export_config = self._export_config_for_sidecars()
        scope = widget.export_scope()
        return self.lyrics_output.export_tracks(
            [],
            export_config=export_config,
            export_scope=scope,
            on_item_finished=self._on_lyrics_exported,
            on_finished=self._on_lyrics_export_finished,
        )

    def _export_config_for_sidecars(self):
        config = get_config(self.app_state.db)
        return replace(config, save_lyrics_sidecars=True, try_embed_lyrics=False)

    def _save_active_lyrics(self):
        """Ctrl+S: trigger save on the currently visible lyrics editor."""
        view = self._active_lyrics_view()
        if view is None:
            return
        if view.btn_save.isEnabled():
            view._emit_save()

    def _active_lyrics_view(self) -> LyricsEditorWidget | None:
        current = self.tabs.currentWidget()
        if current is self.tracks_tab:
            return self.lyrics_view
        if current is self.albums_page:
            return self.albums_lyrics_view
        if current is self.artists_page:
            return self.artists_lyrics_view
        if current is self.album_artists_page:
            return self.album_artists_lyrics_view
        return None

    def _move_active_lyrics_selection(self, delta: int) -> bool:
        view = self._active_lyrics_view()
        if view is None:
            return False
        return view.move_selection_by_rows(delta)

    def _refresh_active_lyrics_view_layout(self, *_args) -> None:
        view = self._active_lyrics_view()
        if view is None:
            return
        view.refresh_layout()
        QTimer.singleShot(0, view.refresh_layout)

    def _focus_search(self):
        """Ctrl+F: focus the search box."""
        preferences.focus_search(self)

    def _clear_search(self):
        """Escape: clear the search box and return focus to the track list."""
        preferences.clear_search(self)

    def _toggle_hotkey_hints(self) -> None:
        preferences.toggle_hotkey_hints(self, FEEDBACK_RESET_MS)

    def _apply_hotkey_preferences(self, config) -> None:
        preferences.apply_hotkey_preferences(self, config)

    def _apply_global_shortcuts(self, bindings: dict[str, dict[str, object]]) -> None:
        preferences.apply_global_shortcuts(self, bindings)

    def _replace_global_shortcut(self, action: str, key: str, callback) -> None:
        preferences.replace_global_shortcut(self, action, key, callback)

    def _register_hotkey_hints(self, bindings: dict[str, dict[str, object]] | None = None) -> None:
        preferences.register_hotkey_hints(self, bindings)

    def _wire_lyrics_view(self, view: LyricsEditorWidget) -> None:
        view.app_state = self.app_state
        view.saveRequested.connect(self._on_lyrics_save_requested)
        view.propagateRequested.connect(self._on_propagate_lyrics_requested)
        view.dirtyDraftChanged.connect(self._on_dirty_lyrics_changed)
        view.discardDraftRequested.connect(self._on_discard_draft_requested)
        view.autoSyncRequested.connect(self._on_auto_sync_requested)
        view.seekRequested.connect(self._seek_player)
        view.downloadRequested.connect(self._download_current_track_lyrics)
        view.searchRequested.connect(self._search_current_track_lyrics)
        view.exportFilesRequested.connect(self._export_current_track_sidecars)

    def eventFilter(self, watched, event):
        if watched is self.player_bar.slider and event.type() == QEvent.Type.KeyPress:
            modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if modifiers == Qt.KeyboardModifier.NoModifier:
                if event.key() == Qt.Key.Key_Up and self._move_active_lyrics_selection(-1):
                    return True
                if event.key() == Qt.Key.Key_Down and self._move_active_lyrics_selection(1):
                    return True
        return super().eventFilter(watched, event)

    def _all_lyrics_views(self) -> list[LyricsEditorWidget]:
        views = [self.lyrics_view, self.albums_lyrics_view, self.artists_lyrics_view]
        if hasattr(self, "album_artists_lyrics_view"):
            views.append(self.album_artists_lyrics_view)
        return views

    def _all_library_splitters(self) -> list[QSplitter]:
        splitters = [self.content_splitter, self.albums_splitter, self.artists_splitter]
        if hasattr(self, "album_artists_splitter"):
            splitters.append(self.album_artists_splitter)
        return splitters

    def _connect_library_splitter_sync(self) -> None:
        for splitter in self._all_library_splitters():
            splitter.splitterMoved.connect(
                lambda _pos, _index, current=splitter: self._sync_library_splitters_from(current)
            )

    @staticmethod
    def _splitter_orientation_name(orientation: Qt.Orientation) -> str:
        return "vertical" if orientation == Qt.Orientation.Vertical else "horizontal"

    @staticmethod
    def _parse_splitter_orientation(value) -> Qt.Orientation:
        if str(value).lower() == "vertical":
            return Qt.Orientation.Vertical
        return Qt.Orientation.Horizontal

    def _scaled_splitter_sizes(self, splitter: QSplitter, source_sizes: list[int]) -> list[int]:
        source_total = max(1, sum(max(0, int(value)) for value in source_sizes))
        target_total = sum(max(0, int(value)) for value in splitter.sizes())
        if target_total <= 0:
            target_total = source_total
        first = max(1, int(round(target_total * max(0, int(source_sizes[0])) / source_total)))
        second = max(1, target_total - first)
        return [first, second]

    def _build_library_splitter_state(self) -> dict[str, object]:
        sizes = [int(value) for value in self.content_splitter.sizes()]
        return {
            "orientation": self._splitter_orientation_name(self.content_splitter.orientation()),
            "sizes": sizes,
        }

    def _apply_library_splitter_state(self, orientation: Qt.Orientation, sizes: list[int]) -> None:
        if len(sizes) != 2 or not all(int(value) > 0 for value in sizes):
            return
        self._syncing_library_splitters = True
        try:
            for splitter in self._all_library_splitters():
                if splitter.orientation() != orientation:
                    splitter.setOrientation(orientation)
                if splitter is self.content_splitter:
                    splitter.setSizes([int(value) for value in sizes])
                else:
                    splitter.setSizes(self._scaled_splitter_sizes(splitter, sizes))
        finally:
            self._syncing_library_splitters = False

    def _restore_library_splitter_state(self, state: dict[str, object]) -> None:
        shared = state.get("library_splitter") if isinstance(state.get("library_splitter"), dict) else None
        sizes: list[int] | None = None
        orientation = Qt.Orientation.Horizontal
        if shared is not None:
            raw_sizes = shared.get("sizes")
            if isinstance(raw_sizes, list):
                try:
                    parsed = [int(value) for value in raw_sizes]
                except (TypeError, ValueError):
                    parsed = []
                if len(parsed) == 2 and all(value > 0 for value in parsed):
                    sizes = parsed
                    orientation = self._parse_splitter_orientation(shared.get("orientation"))

        if sizes is None:
            for key, splitter in [
                ("tracks_splitter", self.content_splitter),
                ("albums_splitter", self.albums_splitter),
                ("artists_splitter", self.artists_splitter),
            ]:
                raw_sizes = state.get(key)
                if not isinstance(raw_sizes, list):
                    continue
                try:
                    parsed = [int(value) for value in raw_sizes]
                except (TypeError, ValueError):
                    continue
                if len(parsed) == 2 and all(value > 0 for value in parsed):
                    sizes = parsed
                    orientation = splitter.orientation()
                    break

        if sizes is not None:
            self._apply_library_splitter_state(orientation, sizes)

    def _sync_library_splitters_from(self, source: QSplitter) -> None:
        if self._syncing_library_splitters:
            return
        if source not in self._all_library_splitters():
            return
        sizes = [int(value) for value in source.sizes()]
        if len(sizes) != 2 or not all(value > 0 for value in sizes):
            return
        self._syncing_library_splitters = True
        try:
            for splitter in self._all_library_splitters():
                if splitter is source:
                    continue
                if splitter.orientation() != source.orientation():
                    splitter.setOrientation(source.orientation())
                splitter.setSizes(self._scaled_splitter_sizes(splitter, sizes))
        finally:
            self._syncing_library_splitters = False

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
        preferences.reset_refresh_feedback(self)

    def _update_responsive_layout(self):
        preferences.update_responsive_layout(self)

    def _save_window_state(self):
        preferences.save_window_state(self)

    def _build_window_state_payload(self) -> dict[str, object]:
        return preferences.build_window_state_payload(self)

    def _persist_window_state_payload(self, state: dict[str, object]) -> None:
        preferences.persist_window_state_payload(self, state)

    def _restore_window_state(self):
        preferences.restore_window_state(self)

    def _load_window_state_payload(self) -> dict[str, object]:
        return preferences.load_window_state_payload(self)

    def _apply_styles(self):
        preferences.apply_styles(self)

    def _appearance_scale(self, ui_scale_percent: int) -> float:
        return preferences.appearance_scale(ui_scale_percent)

    def _apply_appearance_preferences(self, config) -> None:
        preferences.apply_appearance_preferences(self, config)
        if hasattr(self, "track_list"):
            self.track_list.set_show_lyrics_column(bool(config.show_line_count))
            self.track_list.set_show_duration_column(True)
            self.track_list.apply_current_palette()
        if hasattr(self, "albums_tab"):
            self.albums_tab.apply_current_palette()
        if hasattr(self, "artists_tab"):
            self.artists_tab.apply_current_palette()
        if hasattr(self, "album_artists_tab"):
            self.album_artists_tab.apply_current_palette()
        self._apply_styles()
        if hasattr(self, "top_bar"):
            self.top_bar.apply_current_palette()
        if hasattr(self, "albums_lyrics_view"):
            self.albums_lyrics_view._apply_styles()
        if hasattr(self, "artists_lyrics_view"):
            self.artists_lyrics_view._apply_styles()
        if hasattr(self, "album_artists_lyrics_view"):
            self.album_artists_lyrics_view._apply_styles()
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
        elif route.tab == "album_artists":
            self.album_artists_tab.apply_route(route)
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
        return library_actions.confirm_bulk(self, title, text, count)


    def _on_mark_instrumental(self, track_ids: list[int]):
        controller = getattr(self, "track_maintenance", None)
        if controller is not None:
            controller.mark_instrumental(track_ids)
            return
        library_actions.on_mark_instrumental(self, track_ids, mark_tracks=mark_tracks_instrumental)

    def _on_unmark_instrumental(self, track_ids: list[int]):
        controller = getattr(self, "track_maintenance", None)
        if controller is not None:
            controller.unmark_instrumental(track_ids)
            return
        library_actions.on_unmark_instrumental(self, track_ids, unmark_tracks=unmark_tracks_instrumental)

    def _cancel_bulk_publish(self) -> None:
        worker = getattr(self.publish_history, "_bulk_worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()

    def _update_bg_activity_button(self, *_args) -> None:
        """Show the background-activity button when any overlay is active but hidden."""
        overlays = [
            getattr(self, "download_overlay", None),
            getattr(self, "export_overlay", None),
            getattr(self, "publish_overlay", None),
            getattr(self, "scan_overlay", None),
            getattr(self, "ai_sync_overlay", None),
        ]
        has_background_activity = any(
            overlay is not None and overlay.is_active and not overlay.isVisible()
            for overlay in overlays
        )
        self.top_bar.btn_bg_activity.setVisible(has_background_activity)

    def _reopen_bg_overlay(self) -> None:
        """Re-show whichever overlay is running in the background."""
        overlays = [
            getattr(self, "download_overlay", None),
            getattr(self, "export_overlay", None),
            getattr(self, "publish_overlay", None),
            getattr(self, "scan_overlay", None),
            getattr(self, "ai_sync_overlay", None),
        ]
        for overlay in overlays:
            if overlay is not None and overlay.is_active:
                overlay.reopen()
                break

    def _publish_instrumental_to_lrclib(self, track_ids: list[int]) -> None:
        controller = getattr(self, "track_maintenance", None)
        if controller is not None:
            controller.publish_instrumental(track_ids)
            return
        library_actions.publish_instrumental_to_lrclib(self, track_ids)
