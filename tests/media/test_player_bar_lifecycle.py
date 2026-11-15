from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from shiboken6 import delete

from tests.test_support import qt_app
from ui.player_bar import PlayerBar


def test_player_event_filter_survives_speed_combo_destruction():
    app = qt_app()
    bar = PlayerBar(None)
    try:
        delete(bar.cmb_speed)
        assert not bar.eventFilter(bar, QEvent(QEvent.Type.ChildRemoved))
    finally:
        bar.deleteLater()
        QCoreApplication.sendPostedEvents(bar, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_speed_editor_still_commits_on_enter():
    app = qt_app()
    bar = PlayerBar(None)
    bar._on_custom_speed_committed = Mock()
    try:
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        assert bar.eventFilter(bar.cmb_speed.lineEdit(), event)
        bar._on_custom_speed_committed.assert_called_once_with()
    finally:
        bar.deleteLater()
        QCoreApplication.sendPostedEvents(bar, QEvent.Type.DeferredDelete)
        app.processEvents()
