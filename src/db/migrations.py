from __future__ import annotations

import logging
import os
import sqlite3

from db.database import CURRENT_DB_VERSION
from db.schema import SCHEMA_V1_SQL

logger = logging.getLogger(__name__)

DB_FILENAME = "pylrcget.db.sqlite3"


def initialize_database(app_data_dir: str) -> sqlite3.Connection:
    os.makedirs(app_data_dir, exist_ok=True)
    sqlite_path = os.path.join(app_data_dir, DB_FILENAME)
    logger.info("Database file path: %s", sqlite_path)

    db = sqlite3.connect(sqlite_path)
    db.row_factory = sqlite3.Row

    existing_version = int(db.execute("PRAGMA user_version").fetchone()[0])
    upgrade_database_if_needed(db, existing_version)

    return db


def upgrade_database_if_needed(db: sqlite3.Connection, existing_version: int) -> None:
    logger.info("Existing database version: %d", existing_version)

    if existing_version == CURRENT_DB_VERSION:
        return

    if existing_version > CURRENT_DB_VERSION:
        logger.warning("Database version is newer than this build. Skipping migration.")
        return

    if existing_version == 0:
        logger.info("Initialize database version %d...", CURRENT_DB_VERSION)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA_V1_SQL)
        db.execute(f"PRAGMA user_version={CURRENT_DB_VERSION}")
        db.commit()
        return

    if existing_version < 2:
        logger.info("Upgrade database version %d -> 2...", existing_version)
        db.execute("ALTER TABLE tracks ADD COLUMN dirty_lrc_lyrics TEXT")
        db.execute("ALTER TABLE tracks ADD COLUMN dirty_txt_lyrics TEXT")
        db.execute("ALTER TABLE tracks ADD COLUMN dirty_lyrics_present BOOLEAN DEFAULT 0")
        db.execute("PRAGMA user_version=2")
        db.commit()
        existing_version = 2

    if existing_version < 3:
        logger.info("Upgrade database version %d -> 3...", existing_version)
        # Deduplicate any existing rows before adding unique index
        db.execute("""
            DELETE FROM tracks WHERE id NOT IN (
                SELECT MIN(id) FROM tracks GROUP BY file_path
            )
        """)
        # Replace non-unique index with unique index
        db.execute("DROP INDEX IF EXISTS idx_tracks_file_path")
        db.execute("CREATE UNIQUE INDEX idx_tracks_file_path ON tracks(file_path)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tracks_dirty ON tracks(dirty_lyrics_present)")
        db.execute("PRAGMA user_version=3")
        db.commit()
        return

    raise RuntimeError(
        f"Unsupported database upgrade path: {existing_version} -> {CURRENT_DB_VERSION}. "
        "Add an explicit migration step before increasing CURRENT_DB_VERSION."
    )
