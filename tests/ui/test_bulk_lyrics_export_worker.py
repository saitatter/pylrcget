from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_support import HAS_QT, qt_app
from ui.workers.bulk_lyrics_export_worker import (
    BulkLyricsExportWorker,
    TrackExportScope,
)


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class BulkLyricsExportWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_run_summarizes_export_skip_and_failure(self):
        db_path = Path(self._testMethodName + ".sqlite").resolve()
        if db_path.exists():
            db_path.unlink()

        class DummyTrack:
            def __init__(self, track_id: int, has_lyrics: bool) -> None:
                self.id = track_id
                self.title = f"Track {track_id}"
                self.artist_name = "Artist"
                self.txt_lyrics = "plain" if has_lyrics else ""
                self.lrc_lyrics = ""

        def fake_get_track_by_id(_db, track_id: int):
            return DummyTrack(track_id, track_id != 2)

        def fake_sync(track, _config):
            if track.id == 3:
                raise RuntimeError("boom")
            return SimpleNamespace(
                sidecar_paths=(f"/tmp/{track.id}.lrc",),
                embedded=False,
                sidecar_error=None,
                embed_error=None,
            )

        items: list[tuple] = []
        finished: list[tuple] = []
        worker = BulkLyricsExportWorker(
            str(db_path),
            [1, 2, 3],
            SimpleNamespace(save_lyrics_sidecars=True, try_embed_lyrics=False),
        )
        worker.itemFinished.connect(lambda *args: items.append(args))
        worker.finishedBatch.connect(lambda *args: finished.append(args))

        with patch("ui.workers.bulk_lyrics_export_worker.get_track_by_id", side_effect=fake_get_track_by_id), patch(
            "ui.workers.bulk_lyrics_export_worker.sync_track_outputs_with_result",
            side_effect=fake_sync,
        ):
            worker.run()

        self.assertEqual(len(items), 3)
        self.assertTrue(items[0][1])
        self.assertFalse(items[1][1])
        self.assertFalse(items[2][1])
        self.assertEqual(len(finished), 1)
        ok, summary, stats = finished[0]
        self.assertFalse(ok)
        self.assertIn("1 exported", summary)
        self.assertIn("1 skipped", summary)
        self.assertIn("1 failed", summary)
        self.assertEqual(stats["exported"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["failed"], 1)

        if db_path.exists():
            db_path.unlink()

    def test_scope_query_returns_matching_track_ids(self):
        db_path = Path(self._testMethodName + ".sqlite").resolve()
        if db_path.exists():
            db_path.unlink()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE artists (id INTEGER PRIMARY KEY, name TEXT, name_lower TEXT);
            CREATE TABLE albums (
                id INTEGER PRIMARY KEY,
                name TEXT,
                name_lower TEXT,
                album_artist_name TEXT,
                album_artist_name_lower TEXT
            );
            CREATE TABLE tracks (
                id INTEGER PRIMARY KEY,
                file_path TEXT,
                file_name TEXT,
                title TEXT,
                title_lower TEXT,
                artist_id INTEGER,
                album_id INTEGER,
                duration REAL,
                track_number INTEGER,
                txt_lyrics TEXT,
                lrc_lyrics TEXT,
                dirty_txt_lyrics TEXT,
                dirty_lrc_lyrics TEXT,
                dirty_lyrics_present INTEGER,
                instrumental INTEGER
            );
            """
        )
        conn.executemany("INSERT INTO artists VALUES (?, ?, ?)", [(1, "Artist A", "artist a"), (2, "Artist B", "artist b")])
        conn.executemany(
            "INSERT INTO albums VALUES (?, ?, ?, ?, ?)",
            [
                (1, "Album A", "album a", "Artist A", "artist a"),
                (2, "Album B", "album b", "Artist B", "artist b"),
            ],
        )
        conn.executemany(
            "INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "/a.mp3", "a.mp3", "Hello World", "hello world", 1, 1, 120.0, 1, "lyrics", None, None, None, 0, 0),
                (2, "/b.mp3", "b.mp3", "Other Song", "other song", 2, 2, 121.0, 2, "lyrics", None, None, None, 0, 0),
            ],
        )
        conn.commit()

        worker = BulkLyricsExportWorker(
            str(db_path),
            None,
            SimpleNamespace(save_lyrics_sidecars=True, try_embed_lyrics=False),
            export_scope=TrackExportScope(search_query="hello", artist_id=1, album_id=1),
        )
        ids = worker._load_track_ids(conn, worker.export_scope)
        self.assertEqual(ids, [1])
        conn.close()

        if db_path.exists():
            db_path.unlink()
