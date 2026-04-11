from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lrclib.exceptions import NotFoundError, RateLimitError
import requests

from tests import test_support as _test_support  # noqa: F401
from db.database import add_tracks, get_track_by_id, initialize_database
from tests.test_support import make_fs_track, touch_text
from ui.workers.lyrics_download_worker import LyricsDownloadWorker


class LyricsDownloadWorkerTests(unittest.TestCase):
    def test_retries_retryable_lrclib_errors_before_succeeding(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "retry_ok.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist Retry", album="Album Retry", title="Song Retry")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                progress: list[str] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))
                worker.progress.connect(progress.append)

                fake_lyrics = SimpleNamespace(synced_lyrics=None, plain_lyrics="plain text")
                with (
                    patch("ui.services.lyrics_download_service.time.sleep") as sleep_mock,
                    patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls,
                ):
                    api_cls.return_value.get_lyrics.side_effect = [
                        requests.exceptions.Timeout("slow network"),
                        fake_lyrics,
                    ]
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertTrue(ok)
                self.assertIn("plain lyrics", msg)
                self.assertEqual(tid, int(track["id"]))
                self.assertTrue(any("attempt 1/3" in item for item in progress))
                self.assertTrue(any("attempt 2/3" in item for item in progress))
                self.assertTrue(any("retrying in 0.5s" in item for item in progress))
                sleep_mock.assert_called_once_with(0.5)
            finally:
                db.close()

    def test_does_not_retry_not_found_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "missing.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist Missing", album="Album Missing", title="Song Missing")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                response = requests.Response()
                response.status_code = 404
                response.reason = "Not Found"
                response.url = "https://lrclib.net/api/get"
                response._content = b"not found"
                with (
                    patch("ui.services.lyrics_download_service.time.sleep") as sleep_mock,
                    patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls,
                ):
                    api_cls.return_value.get_lyrics.side_effect = NotFoundError(response)
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertFalse(ok)
                self.assertIn("Download failed", msg)
                self.assertEqual(tid, int(track["id"]))
                sleep_mock.assert_not_called()
                self.assertEqual(api_cls.return_value.get_lyrics.call_count, 1)
            finally:
                db.close()

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
                    download_mode="synced_only",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                fake_lyrics = SimpleNamespace(synced_lyrics=None, plain_lyrics="plain text")
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
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
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                fake_lyrics = SimpleNamespace(synced_lyrics=None, plain_lyrics="plain text")
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
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

    def test_plain_only_mode_derives_plain_from_synced(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "synced_only.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist C", album="Album C", title="Song C")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="plain_only",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                fake_lyrics = SimpleNamespace(
                    synced_lyrics="[00:10.00] hello\n[00:12.00] world",
                    plain_lyrics=None,
                )
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.return_value = fake_lyrics
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertTrue(ok)
                self.assertIn("plain lyrics", msg)
                self.assertEqual(tid, int(track["id"]))

                refreshed = get_track_by_id(db, int(track["id"]))
                self.assertEqual(refreshed.txt_lyrics, "hello\nworld")
                self.assertIsNone(refreshed.lrc_lyrics)
            finally:
                db.close()

    def test_plain_only_preserves_non_timestamp_bracket_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "headers.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist D", album="Album D", title="Song D")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="plain_only",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                fake_lyrics = SimpleNamespace(
                    synced_lyrics="[00:10.00][Chorus]\n[00:12.00]world",
                    plain_lyrics=None,
                )
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.return_value = fake_lyrics
                    worker.run()

                self.assertEqual(len(finished), 1)
                refreshed = get_track_by_id(db, int(track["id"]))
                self.assertEqual(refreshed.txt_lyrics, "[Chorus]\nworld")
            finally:
                db.close()

    def test_plain_only_removes_inline_timestamps_without_dropping_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "inline.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist E", album="Album E", title="Song E")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="plain_only",
                )

                fake_lyrics = SimpleNamespace(
                    synced_lyrics="[offset:120]\nLead [00:10.00] line\n[00:12.00][Chorus]",
                    plain_lyrics=None,
                )
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.return_value = fake_lyrics
                    worker.run()

                refreshed = get_track_by_id(db, int(track["id"]))
                self.assertEqual(refreshed.txt_lyrics, "[offset:120]\nLead  line\n[Chorus]")
            finally:
                db.close()
