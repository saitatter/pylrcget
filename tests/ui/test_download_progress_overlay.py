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


def test_lyrics_search_overlay_reports_matches_found_before_saving():
    qt_app()
    overlay = DownloadProgressOverlay()

    overlay.start_batch("Synced only", 2)
    overlay.append_result("First", "Candidate found.", True)
    overlay.finish_batch("Lyrics search complete.")

    assert overlay.ok_label.text() == "1 MATCH FOUND"
    assert overlay.title_label.text() == "Search Complete"
    assert overlay.actions_row.alignment() & Qt.AlignmentFlag.AlignVCenter
