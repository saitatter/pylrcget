from __future__ import annotations

import os
import sqlite3

from db.schema import SCHEMA_V1_SQL
from db.database import CURRENT_DB_VERSION

def initialize_database(app_data_dir: str) -> sqlite3.Connection:
    os.makedirs(app_data_dir, exist_ok=True)
    sqlite_path = os.path.join(app_data_dir, "db.sqlite3")
    print(f"Database file path: {sqlite_path}")

    db = sqlite3.connect(sqlite_path)
    db.row_factory = sqlite3.Row

    existing_version = int(db.execute("PRAGMA user_version").fetchone()[0])
    upgrade_database_if_needed(db, existing_version)

    return db


def upgrade_database_if_needed(db: sqlite3.Connection, existing_version: int) -> None:
    print(f"Existing database version: {existing_version}")

    if existing_version >= CURRENT_DB_VERSION:
        return

    def _column_exists(table: str, column: str) -> bool:
        rows = db.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(row["name"]) == column for row in rows)

    # v1
    if existing_version <= 0:
        print("Migrate database version 1...")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA user_version=1")
        db.executescript(SCHEMA_V1_SQL)
        db.commit()

    # v2
    if existing_version <= 1:
        print("Migrate database version 2...")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA user_version=2")
        db.executescript("""
            ALTER TABLE tracks ADD COLUMN txt_lyrics TEXT;
            CREATE INDEX idx_tracks_title ON tracks(title);
            CREATE INDEX idx_albums_name ON albums(name);
            CREATE INDEX idx_artists_name ON artists(name);
        """)
        db.commit()

    # v3
    if existing_version <= 2:
        print("Migrate database version 3...")
        db.execute("PRAGMA user_version=3")
        db.execute("ALTER TABLE tracks ADD COLUMN instrumental BOOLEAN")
        db.commit()

    # v4
    if existing_version <= 3:
        print("Migrate database version 4...")
        db.execute("PRAGMA user_version=4")
        db.executescript("""
            ALTER TABLE tracks ADD COLUMN title_lower TEXT;
            ALTER TABLE albums ADD COLUMN name_lower TEXT;
            ALTER TABLE artists ADD COLUMN name_lower TEXT;
            CREATE INDEX idx_tracks_title_lower ON tracks(title_lower);
            CREATE INDEX idx_albums_name_lower ON albums(name_lower);
            CREATE INDEX idx_artists_name_lower ON artists(name_lower);
        """)
        db.commit()

    # v5
    if existing_version <= 4:
        print("Migrate database version 5...")
        db.execute("PRAGMA user_version=5")
        db.executescript("""
            ALTER TABLE tracks ADD COLUMN track_number INTEGER;
            ALTER TABLE albums ADD COLUMN album_artist_name TEXT;
            ALTER TABLE albums ADD COLUMN album_artist_name_lower TEXT;
            ALTER TABLE config_data ADD COLUMN theme_mode TEXT DEFAULT 'auto';
            ALTER TABLE config_data ADD COLUMN lrclib_instance TEXT DEFAULT 'https://lrclib.net';
            CREATE INDEX idx_albums_album_artist_name_lower ON albums(album_artist_name_lower);
            CREATE INDEX idx_tracks_track_number ON tracks(track_number);

            DELETE FROM tracks;
            DELETE FROM albums;
            DELETE FROM artists;
            UPDATE library_data SET init = 0;
        """)
        db.commit()

    # v6
    if existing_version <= 5:
        print("Migrate database version 6...")
        db.execute("PRAGMA user_version=6")
        db.executescript("""
            ALTER TABLE config_data ADD COLUMN skip_tracks_with_synced_lyrics BOOLEAN DEFAULT 0;
            ALTER TABLE config_data ADD COLUMN skip_tracks_with_plain_lyrics BOOLEAN DEFAULT 0;
            UPDATE config_data SET skip_tracks_with_synced_lyrics = skip_not_needed_tracks;
        """)
        db.commit()

    # v7
    if existing_version <= 6:
        print("Migrate database version 7...")
        db.execute("PRAGMA user_version=7")
        db.execute("ALTER TABLE config_data ADD COLUMN show_line_count BOOLEAN DEFAULT 1")
        db.commit()

    # v8
    if existing_version <= 7:
        print("Migrate database version 8...")
        db.execute("PRAGMA user_version=8")
        db.executescript("""
            ALTER TABLE config_data ADD COLUMN lyrics_output_dir TEXT DEFAULT '';
            ALTER TABLE config_data ADD COLUMN lyrics_file_pattern TEXT DEFAULT '{artist} - {title}';
        """)
        db.commit()

    # v9
    if existing_version <= 8:
        print("Migrate database version 9...")
        db.execute("PRAGMA user_version=9")
        db.executescript("""
            ALTER TABLE config_data ADD COLUMN save_lyrics_sidecars BOOLEAN DEFAULT 1;
            UPDATE config_data SET save_lyrics_sidecars = 1;
        """)
        db.commit()

    # v10
    if existing_version <= 9:
        print("Migrate database version 10...")
        db.executescript("""
            ALTER TABLE config_data ADD COLUMN scan_excluded_paths TEXT DEFAULT '';
            ALTER TABLE config_data ADD COLUMN scan_excluded_patterns TEXT DEFAULT '';
        """)
        db.commit()
        db.execute("PRAGMA user_version=10")

    # v11
    if existing_version <= 10:
        print("Migrate database version 11...")
        db.executescript("""
            ALTER TABLE tracks ADD COLUMN modified_time REAL;
            ALTER TABLE tracks ADD COLUMN file_size INTEGER;
            CREATE INDEX idx_tracks_file_path ON tracks(file_path);
        """)
        db.commit()
        db.execute("PRAGMA user_version=11")

    # v12
    if existing_version <= 11:
        print("Migrate database version 12...")
        # Reserved migration slot kept for compatibility with pre-merge development databases.
        db.execute("PRAGMA user_version=12")

    # v13
    if existing_version <= 12:
        print("Migrate database version 13...")
        db.executescript("""
            ALTER TABLE config_data ADD COLUMN reaction_delay_ms INTEGER DEFAULT 0;
        """)
        db.commit()
        db.execute("PRAGMA user_version=13")

    # v14
    if existing_version <= 13:
        print("Migrate database version 14...")
        db.executescript("""
            ALTER TABLE config_data ADD COLUMN playback_speed REAL DEFAULT 1.0;
        """)
        db.commit()
        db.execute("PRAGMA user_version=14")

    # v15
    if existing_version <= 14:
        print("Migrate database version 15...")
        db.executescript("""
            DROP TABLE IF EXISTS scan_directory_state;
            DROP TABLE IF EXISTS scan_cache_meta;
        """)
        db.commit()
        db.execute("PRAGMA user_version=15")
    # v16
    if existing_version <= 15:
        print("Migrate database version 16...")
        db.executescript("""
            ALTER TABLE config_data ADD COLUMN last_library_route TEXT DEFAULT '';
        """)
        db.commit()
        db.execute("PRAGMA user_version=16")

    # v17
    if existing_version <= 16:
        print("Migrate database version 17...")
        db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_tracks_artist_id ON tracks(artist_id);
            CREATE INDEX IF NOT EXISTS idx_tracks_album_id ON tracks(album_id);
            CREATE INDEX IF NOT EXISTS idx_tracks_artist_album ON tracks(artist_id, album_id);
            CREATE INDEX IF NOT EXISTS idx_tracks_album_track_number ON tracks(album_id, track_number);
        """)
        db.commit()
        db.execute("PRAGMA user_version=17")

    # v18
    if existing_version <= 17:
        print("Migrate database version 18...")
        db.executescript("""
            ALTER TABLE config_data ADD COLUMN playback_volume REAL DEFAULT 0.7;
        """)
        db.commit()
        db.execute("PRAGMA user_version=18")

    # v19
    if existing_version <= 18:
        print("Migrate database version 19...")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS publish_history (
                id INTEGER PRIMARY KEY,
                track_id INTEGER,
                title TEXT NOT NULL,
                artist_name TEXT NOT NULL,
                album_name TEXT NOT NULL,
                publish_kind TEXT NOT NULL,
                publish_status TEXT NOT NULL DEFAULT 'Published',
                lrclib_instance TEXT NOT NULL,
                published_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_publish_history_published_at
                ON publish_history(published_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_publish_history_track_id
                ON publish_history(track_id);
        """)
        db.commit()
        db.execute("PRAGMA user_version=19")

    # v20
    if existing_version <= 19:
        print("Migrate database version 20...")
        if not _column_exists("config_data", "download_lyrics_mode"):
            db.execute(
                "ALTER TABLE config_data ADD COLUMN download_lyrics_mode TEXT DEFAULT 'prefer_synced'"
            )
        db.commit()
        db.execute("PRAGMA user_version=20")

    # v21
    if existing_version <= 20:
        print("Migrate database version 21...")
        if not _column_exists("config_data", "download_lyrics_mode"):
            db.execute(
                "ALTER TABLE config_data ADD COLUMN download_lyrics_mode TEXT DEFAULT 'prefer_synced'"
            )

        if _column_exists("config_data", "download_synced_only"):
            db.execute("""
                UPDATE config_data
                SET download_lyrics_mode = CASE
                    WHEN download_synced_only = 1 THEN 'synced_only'
                    ELSE 'prefer_synced'
                END
                WHERE download_lyrics_mode = 'prefer_synced'
                   OR download_lyrics_mode IS NULL
                   OR TRIM(download_lyrics_mode) = ''
            """)

        db.commit()
        db.execute("PRAGMA user_version=21")
