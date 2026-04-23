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

    def test_nonzero_legacy_version_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pylrcget.db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute("CREATE TABLE legacy_table (id INTEGER PRIMARY KEY, value TEXT)")
                db.execute("INSERT INTO legacy_table (value) VALUES ('old')")
                db.execute("PRAGMA user_version=24")
                db.commit()

                upgrade_database_if_needed(db, 24)

                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, 24)
                legacy = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_table'"
                ).fetchone()
                self.assertIsNotNone(legacy)
                config = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='config_data'"
                ).fetchone()
                self.assertIsNone(config)
            finally:
                db.close()

    def test_v23_adds_lyrics_lookup_subdir_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute(
                    """
                    CREATE TABLE config_data (
                        download_lyrics_mode TEXT DEFAULT 'prefer_synced'
                    )
                    """
                )
                db.execute("INSERT INTO config_data(download_lyrics_mode) VALUES (?)", ("prefer_synced",))
                db.execute("PRAGMA user_version=22")
                db.commit()

                upgrade_database_if_needed(db, 22)

                columns = {row["name"] for row in db.execute("PRAGMA table_info(config_data)").fetchall()}
                self.assertIn("lyrics_lookup_subdir", columns)
                row = db.execute("SELECT lyrics_lookup_subdir FROM config_data LIMIT 1").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["lyrics_lookup_subdir"], "")
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)
            finally:
                db.close()

    def test_v24_adds_appearance_preference_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute(
                    """
                    CREATE TABLE config_data (
                        lyrics_lookup_subdir TEXT DEFAULT ''
                    )
                    """
                )
                db.execute("INSERT INTO config_data(lyrics_lookup_subdir) VALUES ('lyrics')")
                db.execute("PRAGMA user_version=23")
                db.commit()

                upgrade_database_if_needed(db, 23)

                columns = {row["name"] for row in db.execute("PRAGMA table_info(config_data)").fetchall()}
                self.assertTrue({"ui_scale_percent", "font_size_mode", "show_album_art", "startup_view"} <= columns)
                row = db.execute(
                    """
                    SELECT ui_scale_percent, font_size_mode, show_album_art, startup_view
                    FROM config_data
                    LIMIT 1
                    """
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(int(row["ui_scale_percent"]), 100)
                self.assertEqual(row["font_size_mode"], "normal")
                self.assertEqual(int(row["show_album_art"]), 1)
                self.assertEqual(row["startup_view"], "remember_last")
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
