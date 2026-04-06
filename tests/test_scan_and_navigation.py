from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.models import FsTrack
from db.database import add_tracks, get_album_rows, get_artist_rows, get_library_file_index, initialize_database
from db.queries import find_artist
from library.scan_library import (
    MutagenError,
    get_audio_file_signature,
    iter_audio_paths,
    new_fs_track_from_path,
    preview_audio_path_exclusions,
)
from ui.workers.library_scanner import LibraryScanner
try:
    from PySide6.QtWidgets import QApplication
    from ui.widgets.album_list_widget import AlbumListWidget
    from ui.widgets.artist_list_widget import ArtistListWidget
    HAS_QT = True
except Exception:
    QApplication = None  # type: ignore[assignment]
    AlbumListWidget = None  # type: ignore[assignment]
    ArtistListWidget = None  # type: ignore[assignment]
    HAS_QT = False


def _touch_text(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_fs_track(path: Path, *, artist: str, album: str, title: str) -> FsTrack:
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


class ScanLibraryHelpersTests(unittest.TestCase):
    def test_get_audio_file_signature_includes_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            txt = root / "track.txt"
            lrc = root / "track.lrc"

            _touch_text(audio, "audio")
            time.sleep(0.02)
            _touch_text(txt, "plain lyrics")
            time.sleep(0.02)
            _touch_text(lrc, "[00:01.00]synced")

            sig = get_audio_file_signature(str(audio))
            self.assertIsNotNone(sig[0])
            self.assertEqual(sig[1], audio.stat().st_size + txt.stat().st_size + lrc.stat().st_size)
            self.assertEqual(sig[0], max(audio.stat().st_mtime, txt.stat().st_mtime, lrc.stat().st_mtime))

    def test_iter_audio_paths_and_preview_apply_path_and_regex_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_a = root / "Music" / "keep.mp3"
            include_b = root / "Music" / "sub" / "keep.flac"
            excluded_dir_file = root / "Podcasts" / "skip.mp3"
            excluded_regex_file = root / "Music" / "demo_track.mp3"
            non_audio = root / "Music" / "note.txt"

            for path in (include_a, include_b, excluded_dir_file, excluded_regex_file, non_audio):
                _touch_text(path, "x")

            paths = iter_audio_paths(
                [str(root)],
                excluded_paths=str(root / "Podcasts"),
                excluded_patterns=r"demo",
            )
            self.assertEqual({Path(p).name for p in paths}, {"keep.mp3", "keep.flac"})

            included, excluded = preview_audio_path_exclusions(
                [str(root)],
                excluded_paths=str(root / "Podcasts"),
                excluded_patterns=r"demo",
            )
            self.assertEqual({Path(p).name for p in included}, {"keep.mp3", "keep.flac"})
            self.assertEqual({Path(p).name for p in excluded}, {"demo_track.mp3"})

    def test_new_fs_track_from_path_skips_corrupt_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "broken.mp3"
            _touch_text(audio, "not really audio")

            with patch("library.scan_library.MutagenFile", side_effect=MutagenError("bad frame sync")):
                track = new_fs_track_from_path(str(audio))

            self.assertIsNone(track)


class ArtistAlbumQueryTests(unittest.TestCase):
    def test_get_album_rows_filters_by_track_artist_not_album_artist_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio_a = Path(tmp) / "artist_a.mp3"
                audio_b = Path(tmp) / "artist_b.mp3"
                _touch_text(audio_a, "a")
                _touch_text(audio_b, "b")

                add_tracks(
                    db,
                    [
                        _make_fs_track(audio_a, artist="Artist A", album="Album Shared", title="Song A"),
                        _make_fs_track(audio_b, artist="Artist B", album="Album Other", title="Song B"),
                    ],
                )

                artist_a_id = find_artist(db, "Artist A")
                rows = get_album_rows(db, artist_id=artist_a_id)
                album_names = [row["album_name"] for row in rows]
                self.assertEqual(album_names, ["Album Shared"])
            finally:
                db.close()


class LibraryScannerIncrementalTests(unittest.TestCase):
    def test_library_scanner_skips_unchanged_reindexes_new_and_removes_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            db_path = str(Path(tmp) / "db.sqlite3")
            music_dir = Path(tmp) / "Music"
            music_dir.mkdir(parents=True, exist_ok=True)

            unchanged = music_dir / "unchanged.mp3"
            removed = music_dir / "removed.mp3"
            added = music_dir / "added.mp3"
            _touch_text(unchanged, "same")
            _touch_text(removed, "gone later")

            add_tracks(
                db,
                [
                    _make_fs_track(unchanged, artist="Artist 1", album="Album 1", title="Unchanged"),
                    _make_fs_track(removed, artist="Artist 2", album="Album 2", title="Removed"),
                ],
            )
            db.close()

            removed.unlink()
            _touch_text(added, "new file")

            calls: list[str] = []

            def fake_new_fs_track(path: str, *, signature=None):
                calls.append(Path(path).name)
                if Path(path).name == "added.mp3":
                    return FsTrack(
                        file_path=path,
                        file_name="added.mp3",
                        title="Added",
                        album="Album 3",
                        artist="Artist 3",
                        album_artist="Artist 3",
                        duration=210.0,
                        txt_lyrics=None,
                        lrc_lyrics=None,
                        track_number=1,
                        modified_time=signature[0] if signature else None,
                        file_size=signature[1] if signature else None,
                    )
                return None

            scanner = LibraryScanner(db_path, [str(music_dir)])
            with patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track):
                scanner.run()

            db2 = sqlite3.connect(db_path)
            db2.row_factory = sqlite3.Row
            try:
                index = get_library_file_index(db2)
                names = {Path(path).name for path in index}
                self.assertEqual(names, {"unchanged.mp3", "added.mp3"})
                self.assertEqual(calls, ["added.mp3"])
            finally:
                db2.close()


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget bucket tests")
class NavigationBucketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_album_widget_merges_unknown_album_bucket(self):
        app_state = SimpleNamespace(db=sqlite3.connect(":memory:"))
        widget = AlbumListWidget(app_state)
        try:
            rows = [
                {"album_id": 1, "album_name": "Unknown Album", "artist_name": "Artist A", "track_count": 2},
                {"album_id": 2, "album_name": "Album", "artist_name": "Artist B", "track_count": 3},
                {"album_id": 3, "album_name": "Real Album", "artist_name": "Artist C", "track_count": 1},
            ]
            with patch("ui.widgets.album_list_widget.get_directories", return_value=["C:/Music"]), patch(
                "db.database.get_album_rows", return_value=rows
            ):
                widget.refresh()

            self.assertEqual(widget.model.rowCount(), 2)
            names = [widget.model.index(row, 0).data() for row in range(widget.model.rowCount())]
            self.assertIn("N/A", names)

            na_row = names.index("N/A")
            bucket_ids = widget.model.index(na_row, 0).data(role=0x0100)  # Qt.UserRole
            self.assertEqual(bucket_ids, (1, 2))
            self.assertEqual(widget.model.index(na_row, 2).data(), "5")
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_artist_widget_merges_unknown_artist_bucket(self):
        app_state = SimpleNamespace(db=sqlite3.connect(":memory:"))
        widget = ArtistListWidget(app_state)
        try:
            rows = [
                {"artist_id": 1, "artist_name": "Unknown Artist", "album_count": 2, "track_count": 4},
                {"artist_id": 2, "artist_name": "Artist", "album_count": 1, "track_count": 3},
                {"artist_id": 3, "artist_name": "Real Artist", "album_count": 1, "track_count": 2},
            ]
            with patch("ui.widgets.artist_list_widget.get_directories", return_value=["C:/Music"]), patch(
                "db.database.get_artist_rows", return_value=rows
            ):
                widget.refresh()

            self.assertEqual(widget.model.rowCount(), 2)
            names = [widget.model.index(row, 0).data() for row in range(widget.model.rowCount())]
            self.assertIn("N/A", names)

            na_row = names.index("N/A")
            bucket_ids = widget.model.index(na_row, 0).data(role=0x0100)  # Qt.UserRole
            self.assertEqual(bucket_ids, (1, 2))
            self.assertEqual(widget.model.index(na_row, 2).data(), "7")
        finally:
            widget.deleteLater()
            app_state.db.close()


if __name__ == "__main__":
    unittest.main()
