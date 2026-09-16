from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests

from db.database import initialize_database
from tests import test_support as _test_support  # noqa: F401
from ui.dialogs.publish_lyrics_dialog import PublishWorker
from ui.workers.bulk_publish_instrumental_worker import BulkPublishInstrumentalWorker
from ui.workers.bulk_publish_worker import BulkPublishWorker


class PublishRetryTests(TestCase):
    def test_bulk_instrumental_publish_reports_cancellation_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            db.close()
            worker = BulkPublishInstrumentalWorker(
                str(Path(tmp) / "pylrcget.db.sqlite3"),
                [1],
                "https://example.invalid/api",
            )
            finished: list[tuple[bool, str, dict]] = []
            worker.finished.connect(lambda ok, msg, stats: finished.append((ok, msg, stats)))
            worker.isInterruptionRequested = lambda: True

            with patch("ui.workers.bulk_publish_instrumental_worker.LrcLibAPI"):
                worker.run()

            self.assertEqual(len(finished), 1)
            ok, message, stats = finished[0]
            self.assertFalse(ok)
            self.assertIn("cancelled", message.lower())
            self.assertTrue(stats["cancelled"])
            self.assertEqual(stats["ok"], 0)

    def test_publish_dialog_retries_request_challenge_timeout(self):
        payload = {
            "title": "Song",
            "artistName": "Artist",
            "albumName": "Album",
            "duration": 120,
            "plainLyrics": "plain",
            "syncedLyrics": "[00:00.00]plain",
        }
        worker = PublishWorker(payload, "https://lrclib.net/api")
        finished: list[tuple[bool, str]] = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        api = MagicMock()
        api.request_challenge.side_effect = [
            requests.exceptions.Timeout("slow challenge"),
            ("prefix", "ff" * 32),
        ]

        with (
            patch("ui.dialogs.publish_lyrics_dialog.LrcLibAPI", return_value=api),
            patch("core.lrclib_client.solve_challenge", return_value="0"),
            patch("ui.dialogs.publish_lyrics_dialog.time.sleep") as sleep_mock,
        ):
            worker.run()

        self.assertEqual(finished, [(True, "Lyrics were published successfully.")])
        self.assertEqual(api.request_challenge.call_count, 2)
        api.publish_lyrics.assert_called_once()
        sleep_mock.assert_called_once_with(0.5)

    def test_bulk_publish_retries_timeout(self):
        api = MagicMock()
        api.publish_lyrics.side_effect = [requests.exceptions.Timeout("slow publish"), None]

        with patch("ui.workers.bulk_publish_worker.time.sleep") as sleep_mock:
            BulkPublishWorker._publish_with_retry(api, "Song", "Artist", "Album", 120, "plain", "[00:00.00]plain")

        self.assertEqual(api.publish_lyrics.call_count, 2)
        sleep_mock.assert_called_once_with(0.5)

    def test_bulk_instrumental_publish_retries_timeout(self):
        api = MagicMock()
        api.publish_lyrics.side_effect = [requests.exceptions.Timeout("slow publish"), None]

        with patch("ui.workers.bulk_publish_instrumental_worker.time.sleep") as sleep_mock:
            BulkPublishInstrumentalWorker._publish_with_retry(api, "Song", "Artist", "Album", 120)

        self.assertEqual(api.publish_lyrics.call_count, 2)
        for call in api.publish_lyrics.call_args_list:
            self.assertTrue(call.kwargs["instrumental"])
        sleep_mock.assert_called_once_with(0.5)
