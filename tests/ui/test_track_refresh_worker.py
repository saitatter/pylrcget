from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from db.database import initialize_database
from tests.test_support import touch_text
from ui.workers.track_refresh_worker import TrackRefreshWorker


class TrackRefreshWorkerTests(unittest.TestCase):
    def test_worker_reports_refreshed_removed_and_failed_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "song.mp3"
                touch_text(audio, "audio")

                worker = TrackRefreshWorker(str(Path(tmp) / "pylrcget.db.sqlite3"), [1, 2, 3])
                results: list[tuple[bool, str, dict]] = []
                worker.finishedRefresh.connect(lambda ok, summary, stats: results.append((ok, summary, stats)))

                with patch(
                    "ui.workers.track_refresh_worker.refresh_track_from_file",
                    side_effect=[
                        SimpleNamespace(id=1),
                        None,
                        ValueError("boom"),
                    ],
                ):
                    worker.run()

                self.assertEqual(len(results), 1)
                ok, summary, stats = results[0]
                self.assertFalse(ok)
                self.assertIn("removed", summary.lower())
                self.assertEqual(stats["refreshed"], [1])
                self.assertEqual(stats["removed"], [2])
                self.assertEqual(stats["failed"], [3])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
