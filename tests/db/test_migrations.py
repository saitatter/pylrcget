from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import test_support as _test_support  # noqa: F401
from db.database import CURRENT_DB_VERSION
from db.migrations import upgrade_database_if_needed


class MigrationTests(unittest.TestCase):
    def test_fresh_database_initializes_current_schema(self):
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
                        "scan_worker_count",
                        "ui_scale_percent",
                        "font_size_mode",
                        "show_album_art",
                        "startup_view",
                        "playback_speed",
                        "playback_volume",
                        "lyrics_sidecar_format",
                        "lyrics_embed_format",
                        "scan_lyrics_source_mode",
                        "hotkey_bindings_json",
                        "ui_state_json",
                    }
                    <= config_columns
                )
                track_columns = {
                    row["name"] for row in db.execute("PRAGMA table_info(tracks)").fetchall()
                }
                self.assertTrue(
                    {"dirty_lrc_lyrics", "dirty_txt_lyrics", "dirty_lyrics_present"} <= track_columns
                )

                row = db.execute(
                    """
                    SELECT download_lyrics_mode,
                           lyrics_lookup_subdir,
                           scan_lyrics_source_mode,
                           scan_worker_count,
                           ui_scale_percent,
                           font_size_mode,
                           show_album_art,
                           startup_view,
                           lyrics_sidecar_format,
                              lyrics_embed_format,
                              hotkey_bindings_json,
                              ui_state_json
                    FROM config_data
                    LIMIT 1
                    """
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["download_lyrics_mode"], "prefer_synced")
                self.assertEqual(row["lyrics_lookup_subdir"], "")
                self.assertEqual(row["scan_lyrics_source_mode"], "both")
                self.assertEqual(int(row["scan_worker_count"]), 4)
                self.assertEqual(int(row["ui_scale_percent"]), 100)
                self.assertEqual(row["font_size_mode"], "normal")
                self.assertEqual(int(row["show_album_art"]), 1)
                self.assertEqual(row["startup_view"], "remember_last")
                self.assertEqual(row["lyrics_sidecar_format"], "both")
                self.assertEqual(row["lyrics_embed_format"], "both")
                self.assertEqual(row["hotkey_bindings_json"], "")
                self.assertEqual(row["ui_state_json"], "")
            finally:
                db.close()

    def test_v1_database_upgrades_dirty_lyrics_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pylrcget.db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute(
                    """
                    CREATE TABLE tracks (
                        id INTEGER PRIMARY KEY,
                        file_path TEXT,
                        file_name TEXT,
                        title TEXT,
                        title_lower TEXT,
                        album_id INTEGER,
                        artist_id INTEGER,
                        duration FLOAT,
                        lrc_lyrics TEXT,
                        txt_lyrics TEXT,
                        instrumental BOOLEAN DEFAULT 0,
                        track_number INTEGER,
                        modified_time REAL,
                        file_size INTEGER
                    )
                    """
                )
                db.execute("PRAGMA user_version=1")
                db.commit()

                upgrade_database_if_needed(db, 1)

                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)
                track_columns = {
                    row["name"] for row in db.execute("PRAGMA table_info(tracks)").fetchall()
                }
                self.assertTrue(
                    {"dirty_lrc_lyrics", "dirty_txt_lyrics", "dirty_lyrics_present"} <= track_columns
                )
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

    def test_v2_database_upgrades_lyrics_output_format_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pylrcget.db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute(
                    """
                    CREATE TABLE config_data (
                        id INTEGER PRIMARY KEY,
                        download_lyrics_mode TEXT DEFAULT 'prefer_synced',
                        save_lyrics_sidecars BOOLEAN DEFAULT 1,
                        try_embed_lyrics BOOLEAN DEFAULT 1
                    )
                    """
                )
                db.execute("INSERT INTO config_data (id) VALUES (1)")
                db.execute("PRAGMA user_version=2")
                db.commit()

                upgrade_database_if_needed(db, 2)

                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)
                columns = {row["name"] for row in db.execute("PRAGMA table_info(config_data)").fetchall()}
                self.assertTrue({"lyrics_sidecar_format", "lyrics_embed_format"} <= columns)
                row = db.execute(
                    "SELECT lyrics_sidecar_format, lyrics_embed_format, hotkey_bindings_json, ui_state_json FROM config_data LIMIT 1"
                ).fetchone()
                self.assertEqual(row["lyrics_sidecar_format"], "both")
                self.assertEqual(row["lyrics_embed_format"], "both")
                self.assertEqual(row["hotkey_bindings_json"], "")
                self.assertEqual(row["ui_state_json"], "")
            finally:
                db.close()

    def test_v3_database_upgrades_hotkey_bindings_and_ui_state_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pylrcget.db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute(
                    """
                    CREATE TABLE config_data (
                        id INTEGER PRIMARY KEY,
                        download_lyrics_mode TEXT DEFAULT 'prefer_synced',
                        save_lyrics_sidecars BOOLEAN DEFAULT 1,
                        try_embed_lyrics BOOLEAN DEFAULT 1,
                        lyrics_sidecar_format TEXT DEFAULT 'both',
                        lyrics_embed_format TEXT DEFAULT 'both'
                    )
                    """
                )
                db.execute("INSERT INTO config_data (id) VALUES (1)")
                db.execute("PRAGMA user_version=3")
                db.commit()

                upgrade_database_if_needed(db, 3)

                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)
                columns = {row["name"] for row in db.execute("PRAGMA table_info(config_data)").fetchall()}
                self.assertIn("hotkey_bindings_json", columns)
                self.assertIn("ui_state_json", columns)
                row = db.execute(
                    "SELECT hotkey_bindings_json, ui_state_json FROM config_data LIMIT 1"
                ).fetchone()
                self.assertEqual(row["hotkey_bindings_json"], "")
                self.assertEqual(row["ui_state_json"], "")
            finally:
                db.close()

    def test_v5_database_upgrades_scan_lyrics_source_mode_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pylrcget.db.sqlite3"
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            try:
                db.execute(
                    """
                    CREATE TABLE config_data (
                        id INTEGER PRIMARY KEY,
                        download_lyrics_mode TEXT DEFAULT 'prefer_synced',
                        save_lyrics_sidecars BOOLEAN DEFAULT 1,
                        try_embed_lyrics BOOLEAN DEFAULT 1,
                        lyrics_sidecar_format TEXT DEFAULT 'both',
                        lyrics_embed_format TEXT DEFAULT 'both',
                        hotkey_bindings_json TEXT DEFAULT '',
                        ui_state_json TEXT DEFAULT ''
                    )
                    """
                )
                db.execute("INSERT INTO config_data (id) VALUES (1)")
                db.execute("PRAGMA user_version=5")
                db.commit()

                upgrade_database_if_needed(db, 5)

                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, CURRENT_DB_VERSION)
                columns = {row["name"] for row in db.execute("PRAGMA table_info(config_data)").fetchall()}
                self.assertIn("scan_lyrics_source_mode", columns)
                row = db.execute(
                    "SELECT scan_lyrics_source_mode FROM config_data LIMIT 1"
                ).fetchone()
                self.assertEqual(row["scan_lyrics_source_mode"], "both")
            finally:
                db.close()

if __name__ == "__main__":
    unittest.main()
