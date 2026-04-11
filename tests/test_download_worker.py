from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_support as _test_support  # noqa: F401
from db.database import add_tracks, get_track_by_id, initialize_database
from tests.test_support import make_fs_track, touch_text
from ui.workers.lyrics_download_worker import LyricsDownloadWorker


class LyricsDownloadWorkerTests(unittest.TestCase):
    def test_synced_only_mode_rejects_plain_only_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "plain_only.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist A", album="Album A", title="Song A")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "db.sqlite3"),
                    track_id=int(track["id"]),
                    synced_only=True,
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                fake_lyrics = SimpleNamespace(synced_lyrics=None, plain_lyrics="plain text")
                with patch("ui.workers.lyrics_download_worker.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.return_value = fake_lyrics
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertFalse(ok)
                self.assertIn("synced-only mode", msg)
                self.assertEqual(tid, int(track["id"]))

                refreshed = get_track_by_id(db, int(track["id"]))
                self.assertIsNone(refreshed.lrc_lyrics)
                self.assertIsNone(refreshed.txt_lyrics)
            finally:
                db.close()

    def test_default_mode_saves_plain_only_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "plain_ok.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist B", album="Album B", title="Song B")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "db.sqlite3"),
                    track_id=int(track["id"]),
                    synced_only=False,
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                fake_lyrics = SimpleNamespace(synced_lyrics=None, plain_lyrics="plain text")
                with patch("ui.workers.lyrics_download_worker.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.return_value = fake_lyrics
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertTrue(ok)
                self.assertIn("plain lyrics", msg)
                self.assertEqual(tid, int(track["id"]))

                refreshed = get_track_by_id(db, int(track["id"]))
                self.assertEqual(refreshed.txt_lyrics, "plain text")
                self.assertIsNone(refreshed.lrc_lyrics)
            finally:
                db.close()
