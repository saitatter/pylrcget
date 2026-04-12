from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import test_support as _test_support  # noqa: F401
from db.database import CURRENT_DB_VERSION
from db.migrations import upgrade_database_if_needed


class MigrationTests(unittest.TestCase):
    def test_v21_migrates_legacy_synced_only_flag_when_mode_column_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute(
                    """
                    CREATE TABLE config_data (
                        download_synced_only INTEGER DEFAULT 0,
                        download_lyrics_mode TEXT DEFAULT 'prefer_synced'
                    )
                    """
                )
                db.execute(
                    "INSERT INTO config_data(download_synced_only, download_lyrics_mode) VALUES (?, ?)",
                    (1, "prefer_synced"),
                )
                db.execute("PRAGMA user_version=20")
                db.commit()

                upgrade_database_if_needed(db, 20)

                row = db.execute("SELECT download_lyrics_mode FROM config_data LIMIT 1").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["download_lyrics_mode"], "synced_only")
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)
            finally:
                db.close()

    def test_v21_adds_missing_mode_column_and_migrates_legacy_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute(
                    """
                    CREATE TABLE config_data (
                        download_synced_only INTEGER DEFAULT 0
                    )
                    """
                )
                db.execute("INSERT INTO config_data(download_synced_only) VALUES (?)", (1,))
                db.execute("PRAGMA user_version=20")
                db.commit()

                upgrade_database_if_needed(db, 20)

                columns = {row["name"] for row in db.execute("PRAGMA table_info(config_data)").fetchall()}
                self.assertIn("download_lyrics_mode", columns)
                row = db.execute("SELECT download_lyrics_mode FROM config_data LIMIT 1").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["download_lyrics_mode"], "synced_only")
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)
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


if __name__ == "__main__":
    unittest.main()
