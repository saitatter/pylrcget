from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from PySide6.QtCore import QByteArray, QEvent, QPoint, QPointF, QRect
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPalette,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QHeaderView,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from core.tracklist_models import DownloadState, LyricsState, TrackListRow
from db.database import initialize_database
from tests.test_support import (
    HAS_QT,
    AlbumListWidget,
    ArtistListWidget,
    Qt,
    TrackListWidget,
    qt_app,
    simple_app_state,
)
from ui.controllers.navigation_controller import NavigationController
from ui.controllers.top_bar_controller import TopBarController
from ui.delegates.actions_delegate import ActionsDelegate
from ui.delegates.lyrics_status_delegate import LyricsStatusDelegate
from ui.dialogs.lyrics_diff_dialog import _normalized_diff_lines
from ui.dialogs.lyrics_propagate_dialog import (
    HAS_LYRICS_ROLE,
    LyricsDiffButtonDelegate,
    LyricsPropagateDialog,
)
from ui.dialogs.music_folders_dialog import MusicFoldersDialog
from ui.hotkeys import serialize_lyrics_hotkeys
from ui.library_routes import (
    albums_detail,
    artists_detail,
    tracks_album,
    tracks_all,
    tracks_artist,
)
from ui.main_window import MainWindow
from ui.player_bar import PLAYER_COVER_SIZE, PlayerBar
from ui.theme_tokens import get_theme_tokens
from ui.widgets.hotkey_hints import HotkeyHintManager
from ui.widgets.lrclib_browser_widget import _BrowserPublishDialog
from ui.widgets.lyrics_editor_widget import (
    LINE_NUMBER_COLUMN,
    TIMESTAMP_MS_ROLE,
    LyricsEditorWidget,
)
from ui.widgets.toast import ToastManager

__all__ = [name for name in globals() if not name.startswith("__")]
__all__.extend(["_BrowserPublishDialog", "_normalized_diff_lines"])
