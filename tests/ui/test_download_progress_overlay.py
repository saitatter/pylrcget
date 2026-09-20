from __future__ import annotations

from PySide6.QtCore import Qt

from tests import test_support as _test_support  # noqa: F401
from tests.test_support import qt_app
from ui.widgets.download_progress_overlay import DownloadProgressOverlay


def test_retry_button_uses_cancel_style_and_centered_actions():
    qt_app()
    overlay = DownloadProgressOverlay()

    assert overlay.retry_failed_btn.objectName() == overlay.stop_btn.objectName()
    assert overlay.retry_failed_btn.objectName() == "DownloadOverlayStop"
    assert overlay.actions_row.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert overlay.actions_row.alignment() & Qt.AlignmentFlag.AlignVCenter
