from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from tests import test_support as _test_support  # noqa: F401
from tests.test_support import qt_app
from ui.workers.lyrics_retry_search_worker import MAX_PARALLEL_QUERY_WORKERS, LyricsRetrySearchWorker


class LyricsRetrySearchWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = qt_app()

    def test_continues_after_one_relaxed_query_fails(self):
        track = SimpleNamespace(
            id=12,
            title="All Out Of Love",
            artist_name="Air Supply",
            album_name="Greatest Hits",
        )
        result = SimpleNamespace(
            artist_name="Air Supply",
            track_name="All Out of Love",
            album_name="Lost in Love",
            duration=240,
            plain_lyrics="plain",
            synced_lyrics="[00:01.00]plain",
            instrumental=False,
        )
        fake_search = MagicMock(side_effect=[RuntimeError("network"), [result], [], [], []])
        fake_api = SimpleNamespace(search_lyrics=fake_search)
        worker = LyricsRetrySearchWorker("library.sqlite", [12], "https://lrclib.net/api")
        emitted: list[tuple[list, str]] = []
        worker.finishedSearch.connect(lambda candidates, error: emitted.append((candidates, error)))

        with patch("ui.workers.lyrics_retry_search_worker.sqlite3.connect") as connect_mock, patch(
            "ui.workers.lyrics_retry_search_worker.get_track_by_id",
            return_value=track,
        ), patch("ui.workers.lyrics_retry_search_worker.LrcLibAPI", return_value=fake_api), patch(
            "ui.workers.lyrics_retry_search_worker.time.sleep"
        ):
            connect_mock.return_value.close.return_value = None
            worker.run()

        self.assertEqual(len(emitted), 1)
        candidates, error = emitted[0]
        self.assertEqual(error, "")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].track_id, 12)
        self.assertGreater(fake_api.search_lyrics.call_count, 1)

    def test_stops_after_good_relaxed_match(self):
        track = SimpleNamespace(
            id=13,
            title="All Out Of Love",
            artist_name="Air Supply",
            album_name="Greatest Hits",
        )
        result = SimpleNamespace(
            artist_name="Air Supply",
            track_name="All Out of Love",
            album_name="Lost in Love",
            duration=240,
            plain_lyrics="plain",
            synced_lyrics="[00:01.00]plain",
            instrumental=False,
        )
        fake_search = MagicMock(return_value=[result])
        fake_api = SimpleNamespace(search_lyrics=fake_search)
        worker = LyricsRetrySearchWorker("library.sqlite", [13], "https://lrclib.net/api")
        emitted: list[tuple[list, str]] = []
        worker.finishedSearch.connect(lambda candidates, error: emitted.append((candidates, error)))

        with patch("ui.workers.lyrics_retry_search_worker.sqlite3.connect") as connect_mock, patch(
            "ui.workers.lyrics_retry_search_worker.get_track_by_id",
            return_value=track,
        ), patch("ui.workers.lyrics_retry_search_worker.LrcLibAPI", return_value=fake_api), patch(
            "ui.workers.lyrics_retry_search_worker.time.sleep"
        ):
            connect_mock.return_value.close.return_value = None
            worker.run()

        self.assertEqual(len(emitted), 1)
        candidates, error = emitted[0]
        self.assertEqual(error, "")
        self.assertEqual(len(candidates), 1)
        self.assertGreaterEqual(candidates[0].score, 90)
        self.assertGreaterEqual(fake_api.search_lyrics.call_count, 1)

    def test_parallel_retry_search_caps_query_workers(self):
        track = SimpleNamespace(
            id=14,
            title="All Out Of Love",
            artist_name="Air Supply",
            album_name="Greatest Hits",
        )
        fake_api = SimpleNamespace(search_lyrics=MagicMock(return_value=[]))
        worker = LyricsRetrySearchWorker("library.sqlite", [14], "https://lrclib.net/api")
        emitted: list[tuple[list, str]] = []
        worker.finishedSearch.connect(lambda candidates, error: emitted.append((candidates, error)))

        with patch("ui.workers.lyrics_retry_search_worker.sqlite3.connect") as connect_mock, patch(
            "ui.workers.lyrics_retry_search_worker.get_track_by_id",
            return_value=track,
        ), patch("ui.workers.lyrics_retry_search_worker.LrcLibAPI", return_value=fake_api), patch(
            "ui.workers.lyrics_retry_search_worker.ThreadPoolExecutor"
        ) as executor_cls:
            executor_cls.return_value.__enter__.return_value.submit.side_effect = lambda fn, *args: SimpleNamespace(
                result=lambda: fn(*args),
                cancel=lambda: False,
            )
            with patch("ui.workers.lyrics_retry_search_worker.wait") as wait_mock:
                def fake_wait(pending, return_when):
                    del return_when
                    future = next(iter(pending))
                    return {future}, set(pending) - {future}

                wait_mock.side_effect = fake_wait
                connect_mock.return_value.close.return_value = None
                worker.run()

        executor_cls.assert_called_once()
        self.assertLessEqual(executor_cls.call_args.kwargs["max_workers"], MAX_PARALLEL_QUERY_WORKERS)
        self.assertEqual(len(emitted), 1)


if __name__ == "__main__":
    unittest.main()
