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
