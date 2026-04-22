from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import test_support as _test_support  # noqa: F401
from db.database import CURRENT_DB_VERSION
from db.migrations import upgrade_database_if_needed


class MigrationTests(unittest.TestCase):
    def test_fresh_database_initializes_current_schema_at_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pylrcget.db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                upgrade_database_if_needed(db, 0)

                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)

                config_columns = {
                    row["name"] for row in db.execute("PRAGMA table_info(config_data)").fetchall()
                }
                self.assertTrue(
                    {
                        "download_lyrics_mode",
                        "lyrics_lookup_subdir",
                        "ui_scale_percent",
                        "font_size_mode",
                        "show_album_art",
                        "startup_view",
                        "playback_speed",
                        "playback_volume",
                    }
                    <= config_columns
                )

                row = db.execute(
                    """
                    SELECT download_lyrics_mode,
                           lyrics_lookup_subdir,
                           ui_scale_percent,
                           font_size_mode,
                           show_album_art,
                           startup_view
                    FROM config_data
                    LIMIT 1
                    """
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["download_lyrics_mode"], "prefer_synced")
                self.assertEqual(row["lyrics_lookup_subdir"], "")
                self.assertEqual(int(row["ui_scale_percent"]), 100)
                self.assertEqual(row["font_size_mode"], "normal")
                self.assertEqual(int(row["show_album_art"]), 1)
                self.assertEqual(row["startup_view"], "remember_last")
            finally:
                db.close()

    def test_nonzero_legacy_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pylrcget.db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                with self.assertRaises(RuntimeError):
                    upgrade_database_if_needed(db, 24)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
