import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.state import AppState, Notify
from db.database import get_config, initialize_database
from player.player import Player
from ui.app_theme import apply_app_theme
from ui.main_window import MainWindow

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

def configure_logging(app_data_dir: str) -> str:
    logs_dir = os.path.join(app_data_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "lrcget.log")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)s  %(name)s: %(message)s",
        "%H:%M:%S",
    )

    has_stream = any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler)
        for handler in root.handlers
    )
    if not has_stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    target_path = os.path.abspath(log_path)
    has_file = any(
        os.path.abspath(getattr(handler, "baseFilename", "")) == target_path
        for handler in root.handlers
        if getattr(handler, "baseFilename", None)
    )
    if not has_file:
        file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return log_path


def init_app_state(app_data_dir: str | None = None) -> AppState:
    app_state = AppState()

    app_data_dir = app_data_dir or get_app_data_dir()
    app_state.app_data_dir = app_data_dir
    app_state.db_path = os.path.join(app_data_dir, "db.sqlite3")
    app_state.log_path = configure_logging(app_data_dir)

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
    app_data_dir = get_app_data_dir()
    qt_app = QApplication(sys.argv)
    app_state = init_app_state(app_data_dir)
    apply_app_theme(qt_app, get_config(app_state.db).theme_mode)
    main_window = MainWindow(app_state)
    main_window.show()

    return qt_app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
