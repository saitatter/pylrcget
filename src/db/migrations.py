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
        logger.info("Initialize database version 1...")
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA_V1_SQL)
        db.execute(f"PRAGMA user_version={CURRENT_DB_VERSION}")
        db.commit()
        return

    raise RuntimeError(
        f"Unsupported database upgrade path: {existing_version} -> {CURRENT_DB_VERSION}. "
        "Add an explicit migration step before increasing CURRENT_DB_VERSION."
    )
