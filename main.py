import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QStandardPaths
from core.state import AppState, Notify
from db.database import initialize_database
from player.player import Player
from ui.main_window import MainWindow

app_state = AppState()

def get_app_data_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    os.makedirs(base, exist_ok=True)
    return base

def init_app_state():
    app_data_dir = get_app_data_dir()

    # ✅ store paths on state
    app_state.app_data_dir = app_data_dir
    app_state.db_path = os.path.join(app_data_dir, "db.sqlite3")

    # initialize database connection
    app_state.db = initialize_database(app_data_dir)

    try:
        app_state.player = Player()
    except Exception as e:
        app_state.queued_notifications.append(
            Notify(message=f"Failed to initialize audio player: {e}", notify_type="error")
        )

def main():
    qt_app = QApplication(sys.argv)
    init_app_state()

    main_window = MainWindow(app_state)
    main_window.show()

    main_window.player_timer = QTimer()
    # ... your timer setup if needed

    sys.exit(qt_app.exec())

if __name__ == "__main__":
    main()
