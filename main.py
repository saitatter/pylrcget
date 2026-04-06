import os
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.state import AppState, Notify
from db.database import initialize_database
from player.player import Player
from ui.main_window import MainWindow

app_state = AppState()

def debug_print_schema(db) -> None:
    for table in ("tracks", "albums"):
        cur = db.execute(f"PRAGMA table_info({table})")
        print(f"\n[{table} table schema]")
        for _cid, name, col_type, _notnull, _default, _pk in cur.fetchall():
            print(f"- {name} ({col_type})")

def get_app_data_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    os.makedirs(base, exist_ok=True)
    return base

def init_app_state() -> AppState:
    app_state = AppState()

    app_data_dir = get_app_data_dir()
    app_state.app_data_dir = app_data_dir
    app_state.db_path = os.path.join(app_data_dir, "db.sqlite3")

    app_state.db = initialize_database(app_data_dir)

    if os.getenv("LRCGET_DEBUG_SCHEMA") == "1":
        debug_print_schema(app_state.db)

    try:
        app_state.player = Player()
    except Exception as e:
        app_state.player = None
        app_state.queued_notifications.append(
            Notify(message=f"Failed to initialize audio player: {e}", notify_type="error")
        )

    return app_state

def main() -> int:
    qt_app = QApplication(sys.argv)

    app_state = init_app_state()
    main_window = MainWindow(app_state)
    main_window.show()

    return qt_app.exec()

if __name__ == "__main__":
    raise SystemExit(main())

