from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import sqlite3
from types import SimpleNamespace

from core.models import FsTrack
from library.scan_library import get_audio_file_signature

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from ui.widgets.album_list_widget import AlbumListWidget
    from ui.widgets.artist_list_widget import ArtistListWidget
    from ui.widgets.track_list_widget import TrackListWidget

    HAS_QT = True
except Exception:
    Qt = None  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]
    AlbumListWidget = None  # type: ignore[assignment]
    ArtistListWidget = None  # type: ignore[assignment]
    TrackListWidget = None  # type: ignore[assignment]
    HAS_QT = False


def touch_text(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_fs_track(path: Path, *, artist: str, album: str, title: str) -> FsTrack:
    signature = get_audio_file_signature(str(path))
    return FsTrack(
        file_path=str(path),
        file_name=path.name,
        title=title,
        album=album,
        artist=artist,
        album_artist=artist,
        duration=180.0,
        txt_lyrics=None,
        lrc_lyrics=None,
        track_number=1,
        modified_time=signature[0],
        file_size=signature[1],
    )


def qt_app():
    if QApplication is None:
        return None
    return QApplication.instance() or QApplication([])


def simple_app_state(db: sqlite3.Connection | None = None) -> SimpleNamespace:
    return SimpleNamespace(db=db or sqlite3.connect(":memory:"))
