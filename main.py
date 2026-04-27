import os
import sys
import logging
import shutil
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.state import AppState
from db.database import get_config, initialize_database
from db.migrations import DB_FILENAME
from ui.app_theme import apply_app_theme
from ui.icon_loader import load_app_icon
from ui.main_window import MainWindow

def debug_print_schema(db) -> None:
    for table in ("tracks", "albums"):
        cur = db.execute(f"PRAGMA table_info({table})")
        print(f"\n[{table} table schema]")
        for _cid, name, col_type, _notnull, _default, _pk in cur.fetchall():
            print(f"- {name} ({col_type})")

def _migrate_old_nested_app_data(base: str) -> None:
    # Migrate from old nested layout (PyLrcGet/PyLrcGet -> PyLrcGet).
    old_nested = os.path.join(base, "PyLrcGet")
    if not os.path.isdir(old_nested):
        return
    base_path = Path(base).resolve()
    old_nested_path = Path(old_nested).resolve()
    if old_nested_path.parent != base_path or old_nested_path.name != "PyLrcGet":
        logging.warning("Refusing to remove unexpected old app data path: %s", old_nested)
        return

    for item in os.listdir(old_nested):
        src = os.path.join(old_nested, item)
        dst = os.path.join(base, item)
        if not os.path.exists(dst):
            try:
                os.rename(src, dst)
            except OSError as exc:
                logging.warning("Failed to migrate app data from %s to %s: %s", src, dst, exc)

    try:
        shutil.rmtree(old_nested_path)
    except OSError:
        logging.warning("Failed to remove old app data directory %s", old_nested, exc_info=True)

def get_app_data_dir() -> str:
    app = QApplication.instance()
    if app is not None and not app.applicationName():
        app.setApplicationName("PyLrcGet")
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)

    _migrate_old_nested_app_data(base)
    os.makedirs(base, exist_ok=True)
    return base

def configure_logging(app_data_dir: str) -> str:
    logs_dir = os.path.join(app_data_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "pylrcget.log")

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
    app_state.db_path = os.path.join(app_data_dir, DB_FILENAME)
    app_state.log_path = configure_logging(app_data_dir)

    app_state.db = initialize_database(app_data_dir)

    if os.getenv("LRCGET_DEBUG_SCHEMA") == "1":
        debug_print_schema(app_state.db)

    return app_state
def main() -> int:
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("PyLrcGet")
    qt_app.setOrganizationName("")
    qt_app.setWindowIcon(load_app_icon())
    app_data_dir = get_app_data_dir()
    app_state = init_app_state(app_data_dir)
    config = get_config(app_state.db)
    apply_app_theme(
        qt_app,
        config.theme_mode,
        ui_scale_percent=config.ui_scale_percent,
        font_size_mode=config.font_size_mode,
    )
    main_window = MainWindow(app_state)
    main_window.show()
    main_window._startup_player_timer = QTimer(main_window)
    main_window._startup_player_timer.setSingleShot(True)
    main_window._startup_player_timer.timeout.connect(main_window.initialize_player_backend)
    main_window._startup_player_timer.start(50)

    return qt_app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
