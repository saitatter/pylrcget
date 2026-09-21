from __future__ import annotations

import json
import sqlite3

from db.database import CURRENT_DB_VERSION
from db.migrations import upgrade_database_if_needed


def test_v5_migration_materializes_source_defaults_without_losing_ui_state():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute(
            """
            CREATE TABLE config_data (
                id INTEGER PRIMARY KEY,
                ui_state_json TEXT DEFAULT ''
            )
            """
        )
        db.execute(
            "INSERT INTO config_data (id, ui_state_json) VALUES (1, ?)",
            (json.dumps({"editor_auto_edit_on_add_line": True}),),
        )
        db.execute("PRAGMA user_version=5")
        db.commit()

        upgrade_database_if_needed(db, 5)

        state = json.loads(db.execute("SELECT ui_state_json FROM config_data").fetchone()[0])
        assert state["editor_auto_edit_on_add_line"] is True
        assert state["lyrics_sources"]["enabled"] == {
            "lrclib": True,
            "musixmatch": False,
        }
        assert int(db.execute("PRAGMA user_version").fetchone()[0]) == CURRENT_DB_VERSION
    finally:
        db.close()
