from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from core.lrclib_client import LrcLibError, NotFoundError, RateLimitError
from db.database import add_tracks, get_track_by_id, initialize_database
from tests import test_support as _test_support  # noqa: F401
from tests.test_support import make_fs_track, touch_text
from ui.workers.bulk_lyrics_download_worker import (
    MAX_PARALLEL_DOWNLOAD_WORKERS,
    BulkLyricsDownloadWorker,
)
from ui.workers.lyrics_download_worker import LyricsDownloadWorker


class _ImmediateFuture:
    def __init__(self, fn, *args):
        self._fn = fn
        self._args = args

    def result(self):
        return self._fn(*self._args)

    def cancel(self):
        return False


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
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
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

    def test_not_found_falls_back_to_alternative_search(self):
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
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                with (
                    patch("ui.services.lyrics_download_service.time.sleep") as sleep_mock,
                    patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls,
                ):
                    api_cls.return_value.get_lyrics.side_effect = NotFoundError(404, "Not Found")
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertFalse(ok)
                self.assertIn("No lyrics found", msg)
                self.assertEqual(tid, int(track["id"]))
                sleep_mock.assert_not_called()
                self.assertEqual(api_cls.return_value.get_lyrics.call_count, 1)
                self.assertGreater(api_cls.return_value.search_lyrics.call_count, 0)
            finally:
                db.close()

    def test_generic_not_found_error_falls_back_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "missing_generic.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist Missing", album="Album Missing", title="Song Missing")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                with (
                    patch("ui.services.lyrics_download_service.time.sleep") as sleep_mock,
                    patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls,
                ):
                    api_cls.return_value.get_lyrics.side_effect = LrcLibError(400, "Bad Request", "not found")
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertFalse(ok)
                self.assertIn("No lyrics found", msg)
                self.assertEqual(tid, int(track["id"]))
                sleep_mock.assert_not_called()
                self.assertEqual(api_cls.return_value.get_lyrics.call_count, 1)
                self.assertGreater(api_cls.return_value.search_lyrics.call_count, 0)
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
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
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

    def test_not_found_uses_relaxed_match_with_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "relaxed.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Air Supply", album="Greatest Hits", title="All Out Of Love")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                relaxed_result = SimpleNamespace(
                    artist_name="Air Supply",
                    track_name="All Out of Love",
                    album_name="Lost in Love",
                    duration=240,
                    plain_lyrics="plain text",
                    synced_lyrics="[00:01.00]plain text",
                    instrumental=False,
                )
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.side_effect = NotFoundError(404, "Not Found")
                    api_cls.return_value.search_lyrics.return_value = [relaxed_result]
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertTrue(ok)
                self.assertIn("Match:", msg)
                self.assertEqual(tid, int(track["id"]))

                refreshed = get_track_by_id(db, int(track["id"]))
                self.assertEqual(refreshed.lrc_lyrics, "[00:01.00]plain text")
                self.assertIsNone(refreshed.txt_lyrics)
            finally:
                db.close()

    def test_synced_download_preserves_existing_plain_lyrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "preserve_plain.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)
                track_id = int(track["id"])
                db.execute("UPDATE tracks SET txt_lyrics = ? WHERE id = ?", ("existing plain", track_id))
                db.commit()

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_id=track_id,
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                fake_lyrics = SimpleNamespace(
                    synced_lyrics="[00:01.00]synced text",
                    plain_lyrics="lrclib plain should not replace",
                )
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.return_value = fake_lyrics
                    worker.run()

                self.assertEqual(len(finished), 1)
                self.assertTrue(finished[0][0])
                refreshed = get_track_by_id(db, track_id)
                self.assertEqual(refreshed.lrc_lyrics, "[00:01.00]synced text")
                self.assertEqual(refreshed.txt_lyrics, "existing plain")
            finally:
                db.close()

    def test_retryable_alternative_search_error_stops_remaining_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "rate_limited_relaxed.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.side_effect = NotFoundError(404, "Not Found")
                    api_cls.return_value.search_lyrics.side_effect = RateLimitError(429, "Too Many Requests", "slow down")
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertFalse(ok)
                self.assertIn("Download failed", msg)
                self.assertIn("429", msg)
                self.assertEqual(tid, int(track["id"]))
                self.assertEqual(api_cls.return_value.search_lyrics.call_count, 1)
            finally:
                db.close()

    def test_perfect_alternative_match_stops_remaining_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "perfect_relaxed.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                finished: list[tuple[bool, str, int]] = []
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="prefer_synced",
                )
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                perfect_result = SimpleNamespace(
                    artist_name="Artist",
                    track_name="Song",
                    album_name="Album",
                    duration=180,
                    plain_lyrics="plain text",
                    synced_lyrics="[00:01.00]plain text",
                    instrumental=False,
                )
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.side_effect = NotFoundError(404, "Not Found")
                    api_cls.return_value.search_lyrics.return_value = [perfect_result]
                    worker.run()

                self.assertEqual(len(finished), 1)
                ok, msg, tid = finished[0]
                self.assertTrue(ok)
                self.assertIn("Match: 100%", msg)
                self.assertEqual(tid, int(track["id"]))
                self.assertEqual(api_cls.return_value.search_lyrics.call_count, 1)
            finally:
                db.close()

    def test_bulk_download_parallelizes_track_searches(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                tracks = []
                for index in range(6):
                    audio = Path(tmp) / f"bulk_{index}.mp3"
                    touch_text(audio, "a")
                    tracks.append(make_fs_track(audio, artist=f"Artist {index}", album="Album", title=f"Song {index}"))
                add_tracks(db, tracks)
                track_ids = [int(row["id"]) for row in db.execute("SELECT id FROM tracks ORDER BY id").fetchall()]

                worker = BulkLyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_ids=track_ids,
                    lrclib_instance="https://lrclib.net/api",
                    download_mode="prefer_synced",
                )
                finished: list[tuple[bool, str, dict]] = []
                progress: list[tuple[int, int, str, str]] = []
                worker.finishedBatch.connect(lambda ok, msg, stats: finished.append((ok, msg, stats)))
                worker.progress.connect(lambda current, total, label, status, elapsed: progress.append((current, total, label, status)))

                fake_lyrics = SimpleNamespace(synced_lyrics=None, plain_lyrics="plain text")
                with patch("ui.workers.bulk_lyrics_download_worker.LrcLibAPI") as api_cls, patch(
                    "ui.workers.bulk_lyrics_download_worker.ThreadPoolExecutor"
                ) as executor_cls:
                    api_cls.return_value.get_lyrics.return_value = fake_lyrics
                    executor_cls.return_value.submit.side_effect = _ImmediateFuture

                    with patch("ui.workers.bulk_lyrics_download_worker.wait") as wait_mock:
                        def fake_wait(pending, timeout, return_when):
                            del timeout
                            del return_when
                            future = next(iter(pending))
                            return {future}, set(pending) - {future}

                        wait_mock.side_effect = fake_wait
                        worker.run()

                executor_cls.assert_called_once()
                self.assertLessEqual(executor_cls.call_args.kwargs["max_workers"], MAX_PARALLEL_DOWNLOAD_WORKERS)
                self.assertEqual(len(finished), 1)
                self.assertEqual(finished[0][2]["ok"], len(track_ids))
                completed_values = [current for current, *_ in progress if current >= 0]
                self.assertEqual(completed_values, sorted(completed_values))
                self.assertEqual(completed_values[-1], len(track_ids))
                self.assertTrue(any(current == -1 for current, *_ in progress))
                for track_id in track_ids:
                    refreshed = get_track_by_id(db, int(track_id))
                    self.assertIsNone(refreshed.txt_lyrics)
                    self.assertIsNone(refreshed.lrc_lyrics)
            finally:
                db.close()

    def test_bulk_download_cancel_does_not_wait_for_running_searches(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "cancel.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
                track_ids = [int(row["id"]) for row in db.execute("SELECT id FROM tracks ORDER BY id").fetchall()]

                worker = BulkLyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_ids=track_ids,
                    lrclib_instance="https://lrclib.net/api",
                    download_mode="prefer_synced",
                )
                finished: list[tuple[bool, str, dict]] = []
                worker.finishedBatch.connect(lambda ok, msg, stats: finished.append((ok, msg, stats)))

                with patch("ui.workers.bulk_lyrics_download_worker.ThreadPoolExecutor") as executor_cls:
                    future = executor_cls.return_value.submit.return_value

                    with patch.object(worker, "isInterruptionRequested", side_effect=[False, True, True, True]):
                        worker.run()

                future.cancel.assert_called_once()
                executor_cls.return_value.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
                self.assertEqual(len(finished), 1)
                self.assertFalse(finished[0][0])
                self.assertTrue(finished[0][2]["cancelled"])
            finally:
                db.close()

    def test_bulk_download_skips_invalid_duration_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "too_long.mp3"
                touch_text(audio, "a")
                add_tracks(
                    db,
                    [
                        replace(
                            make_fs_track(audio, artist="Modern Talking", album="25 Years of Disco-Pop CD1", title="Medley"),
                            duration=4000.0,
                        )
                    ],
                )
                track_ids = [int(row["id"]) for row in db.execute("SELECT id FROM tracks ORDER BY id").fetchall()]
                worker = BulkLyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_ids=track_ids,
                    lrclib_instance="https://lrclib.net/api",
                    download_mode="prefer_synced",
                )
                results: list[tuple[int, bool, str, str]] = []
                finished: list[tuple[bool, str, dict]] = []
                worker.itemFinished.connect(lambda track_id, ok, label, msg: results.append((track_id, ok, label, msg)))
                worker.finishedBatch.connect(lambda ok, msg, stats: finished.append((ok, msg, stats)))

                with patch("ui.workers.bulk_lyrics_download_worker.LrcLibAPI") as api_cls, patch(
                    "ui.workers.bulk_lyrics_download_worker.ThreadPoolExecutor"
                ) as executor_cls:
                    worker.run()

                api_cls.assert_not_called()
                executor_cls.assert_not_called()
                self.assertEqual(len(results), 1)
                self.assertFalse(results[0][1])
                self.assertIn("Skipped without request", results[0][3])
                self.assertEqual(finished[0][2]["failed"], 1)
            finally:
                db.close()

    def test_single_download_skips_invalid_duration_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "too_long_single.mp3"
                touch_text(audio, "a")
                add_tracks(
                    db,
                    [replace(make_fs_track(audio, artist="Artist", album="Album", title="Long Track"), duration=4000.0)],
                )
                track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])
                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_id=track_id,
                    download_mode="prefer_synced",
                )
                finished: list[tuple[bool, str, int]] = []
                worker.finished.connect(lambda ok, msg, tid: finished.append((ok, msg, tid)))

                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    worker.run()

                api_cls.assert_not_called()
                self.assertEqual(len(finished), 1)
                self.assertFalse(finished[0][0])
                self.assertIn("Skipped without request", finished[0][1])
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
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
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
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
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
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
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
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
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

    def test_plain_only_removes_hour_style_timestamps_without_dropping_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "hours.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist F", album="Album F", title="Song F")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                worker = LyricsDownloadWorker(
                    db_path=str(Path(tmp) / "pylrcget.db.sqlite3"),
                    track_id=int(track["id"]),
                    download_mode="plain_only",
                )

                fake_lyrics = SimpleNamespace(
                    synced_lyrics="[01:02:03.45]Long intro\n[01:02:05.00][Verse 1]",
                    plain_lyrics=None,
                )
                with patch("ui.services.lyrics_download_service.LrcLibAPI") as api_cls:
                    api_cls.return_value.get_lyrics.return_value = fake_lyrics
                    worker.run()

                refreshed = get_track_by_id(db, int(track["id"]))
                self.assertEqual(refreshed.txt_lyrics, "Long intro\n[Verse 1]")
            finally:
                db.close()
