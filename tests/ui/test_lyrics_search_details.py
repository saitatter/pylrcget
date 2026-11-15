from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QTimer

from lyrics.providers.contracts import LyricsSearchResult
from tests.test_support import qt_app
from ui.controllers.lyrics_search_details_controller import (
    LyricsSearchDetailsController,
)
from ui.dialogs.search_lyrics_dialog import SearchLyricsDialog
from ui.widgets.lrclib_browser_widget import LrclibBrowserWidget


def _summary(record_id="7"):
    return LyricsSearchResult(
        provider="lrclib", provider_track_id=record_id, title="Song", artist="Artist", album="Album",
        duration_seconds=180, instrumental=False, has_plain_lyrics=True, has_synced_lyrics=True,
        lyrics_loaded=False,
    )


def test_controller_loads_lyrics_off_the_gui_thread(monkeypatch):
    import threading
    app = qt_app()
    gui_thread = threading.get_ident()
    calls = []
    def api(_instance, *, is_cancelled):
        def get_lyrics_by_id(record_id):
            calls.append((record_id, threading.get_ident(), is_cancelled()))
            return SimpleNamespace(plain_lyrics="plain", synced_lyrics="[00:01.00]line", instrumental=False)
        return SimpleNamespace(get_lyrics_by_id=get_lyrics_by_id)
    monkeypatch.setattr("ui.workers.lyrics_search_details_worker.LrcLibAPI", api)
    controller = LyricsSearchDetailsController()
    emitted = []
    loop = QEventLoop()
    controller.loaded.connect(lambda *args: (emitted.append(args), loop.quit()))
    controller.request("https://example.test/api", _summary())
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    assert emitted and emitted[0][1].lyrics_loaded
    assert emitted[0][1].synced_lyrics == "[00:01.00]line"
    assert calls[0][0] == "7" and calls[0][1] != gui_thread and calls[0][2] is False
    for worker in tuple(controller._workers):
        worker.wait()
    app.processEvents()


def test_controller_discards_cancelled_selection():
    app = qt_app()
    controller = LyricsSearchDetailsController()
    emitted = []
    controller.loaded.connect(lambda *args: emitted.append(args))
    summary = _summary()
    controller.cancel()
    controller._on_completed(0, summary, replace(summary, lyrics_loaded=True), "")
    assert emitted == []
    app.processEvents()


def test_removed_lyrics_report_an_error_instead_of_applying_empty_text(monkeypatch):
    from ui.workers.lyrics_search_details_worker import LyricsSearchDetailsWorker
    app = qt_app()
    monkeypatch.setattr(
        "ui.workers.lyrics_search_details_worker.LrcLibAPI",
        lambda *_args, **_kwargs: SimpleNamespace(get_lyrics_by_id=lambda _: SimpleNamespace(
            plain_lyrics=None, synced_lyrics=None, instrumental=False,
        )),
    )
    worker = LyricsSearchDetailsWorker("https://example.test/api", _summary(), 1)
    emitted = []
    worker.completed.connect(lambda *args: emitted.append(args))
    worker.run()
    assert emitted[0][2] is None
    assert "no longer contains lyrics" in emitted[0][3]
    worker.deleteLater()
    app.processEvents()


def test_search_dialog_fetches_selected_summary_before_applying(monkeypatch):
    app = qt_app()
    dialog = SearchLyricsDialog("https://example.test/api")
    requests = []
    monkeypatch.setattr(dialog._details, "request", lambda *args: requests.append(args))
    emitted = []
    dialog.lyricsSelected.connect(lambda *args: emitted.append(args))
    summary = _summary()
    dialog._on_search_finished([summary], "")
    assert dialog.table.item(0, 4).text() == "Synced"
    dialog.table.selectRow(0)
    dialog._use_selected()
    assert len(requests) == 1 and emitted == []
    assert not dialog.use_btn.isEnabled()
    loaded = replace(summary, lyrics_loaded=True, plain_lyrics="plain", synced_lyrics="synced")
    dialog._on_details_loaded(summary, loaded, "")
    assert emitted == [("plain", "synced")]
    dialog.close()
    app.processEvents()


def test_browser_ignores_stale_details_and_reuses_loaded_result(monkeypatch):
    app = qt_app()
    browser = LrclibBrowserWidget(SimpleNamespace())
    requests = []
    monkeypatch.setattr(browser._details, "request", lambda *args: requests.append(args))
    first, second = _summary(), _summary("8")
    browser._on_search_finished([first, second], "")
    browser.table.selectRow(0)
    browser.table.selectRow(1)
    loaded_first = replace(first, lyrics_loaded=True, plain_lyrics="wrong")
    browser._on_details_loaded(first, loaded_first, "")
    assert browser.plain_preview.toPlainText() == ""
    loaded_second = replace(second, lyrics_loaded=True, plain_lyrics="right")
    browser._on_details_loaded(second, loaded_second, "")
    assert browser.plain_preview.toPlainText() == "right"
    assert browser.copy_plain_btn.isEnabled()
    assert browser.publish_btn.isEnabled()
    assert len(requests) == 2
    browser._on_selection_changed()
    assert len(requests) == 2
    browser.close()
    app.processEvents()


def test_dialog_detail_failure_keeps_the_selection_available_for_retry(monkeypatch):
    app = qt_app()
    dialog = SearchLyricsDialog("https://example.test/api")
    monkeypatch.setattr(dialog._details, "request", lambda *_: None)
    summary = _summary()
    dialog._on_search_finished([summary], "")
    dialog.table.selectRow(0)
    dialog._use_selected()
    dialog._on_details_loaded(summary, None, "offline")
    assert dialog.use_btn.isEnabled()
    assert "offline" in dialog.status_label.text()
    assert dialog.result() == 0
    dialog.close()
    app.processEvents()
