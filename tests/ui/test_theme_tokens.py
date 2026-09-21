from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.tracklist_models import DownloadState, LyricsState, TrackListRow
from ui.models.track_table_model import TrackTableModel
from ui.style_loader import load_stylesheet
from ui.theme_tokens import get_theme_tokens, set_theme_tokens
from ui.widgets.album_list_widget import AlbumListWidget


@pytest.mark.parametrize(
    ("theme", "expected"),
    [
        (
            "DarkTheme",
            {
                "color-success-bg": "#102A20",
                "color-success-border": "#237A50",
                "color-success-text": "#75E0A7",
                "color-warning-bg": "#2B210C",
                "color-warning-border": "#B88214",
                "color-warning-text": "#FEC84B",
                "color-error-bg": "#321414",
                "color-error-border": "#D24A4A",
                "color-error-text": "#FDA29B",
                "color-info-bg": "#10243B",
                "color-info-border": "#316DA8",
                "color-info-text": "#8CC8FF",
            },
        ),
        (
            "LightTheme",
            {
                "color-success-bg": "#ECFDF3",
                "color-success-border": "#ABEFC6",
                "color-success-text": "#067647",
                "color-warning-bg": "#FFFAEB",
                "color-warning-border": "#FEDF89",
                "color-warning-text": "#B54708",
                "color-error-bg": "#FEF3F2",
                "color-error-border": "#FECDCA",
                "color-error-text": "#B42318",
                "color-info-bg": "#EFF8FF",
                "color-info-border": "#B2DDFF",
                "color-info-text": "#175CD3",
            },
        ),
    ],
)
def test_core_theme_semantic_colors_are_palette_aware(theme: str, expected: dict[str, str]) -> None:
    tokens = get_theme_tokens(theme)

    for token, value in expected.items():
        assert tokens[token] == value


def test_optional_theme_keeps_its_palette_mode_for_semantic_fallbacks() -> None:
    tokens = get_theme_tokens("SpotifyTheme")

    assert tokens["palette-mode"] == "dark"
    assert tokens["color-success-bg"] == "#102A20"


def test_typography_tokens_use_the_modern_desktop_scale() -> None:
    tokens = get_theme_tokens("LightTheme")

    assert tokens["font-family-base"].startswith("'Segoe UI Variable Text', 'Segoe UI'")
    assert tokens["font-size-xs"] == "11px"
    assert tokens["font-size-sm"] == "12px"
    assert tokens["font-size-md"] == "13px"
    assert tokens["font-size-lg"] == "16px"


def test_spacing_and_control_tokens_use_the_compact_desktop_metrics() -> None:
    tokens = get_theme_tokens("LightTheme")

    assert tokens["space-5"] == "24px"
    assert tokens["control-height-compact"] == "28px"
    assert tokens["control-height-normal"] == "34px"
    assert tokens["control-height-prominent"] == "38px"
    assert tokens["control-height-primary"] == "44px"
    assert tokens["radius-sm"] == "6px"
    assert tokens["radius-md"] == "8px"
    assert tokens["radius-lg"] == "10px"


def test_album_table_reloads_qss_after_palette_change() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    set_theme_tokens("DarkTheme")
    widget = AlbumListWidget(SimpleNamespace(db=None))

    try:
        set_theme_tokens("LightTheme")
        widget.apply_current_palette()

        assert "#fafafa" in widget.styleSheet()
        assert "#303030" not in widget.styleSheet()
    finally:
        widget.deleteLater()
        set_theme_tokens("DarkTheme")


def test_checked_checkbox_focus_keeps_light_accent_fill() -> None:
    set_theme_tokens("LightTheme")
    try:
        stylesheet = load_stylesheet("app.qss")

        assert "QCheckBox::indicator:checked:focus" in stylesheet
        assert "QCheckBox::indicator:checked:hover" in stylesheet
        assert "QCheckBox:hover {" in stylesheet
        assert "QCheckBox:hover::indicator" not in stylesheet
        assert "background: #3f51b5;" in stylesheet
        assert "background: #5f5fc4;" in stylesheet
    finally:
        set_theme_tokens("DarkTheme")


def test_light_theme_lyrics_statuses_use_semantic_text_colors() -> None:
    set_theme_tokens("LightTheme")
    try:
        row = TrackListRow(
            track_id=1,
            title="Song",
            artist="Artist",
            artist_id=None,
            album="Album",
            album_id=None,
            track_number=1,
            duration_s=120,
            lyrics_state=LyricsState.NONE,
            download_state=DownloadState.IDLE,
        )
        model = TrackTableModel([row])

        assert model.data(model.index(0, 3), Qt.ForegroundRole).name() == "#b42318"

        model._rows[0] = replace(row, lyrics_state=LyricsState.SYNCED)
        assert model.data(model.index(0, 3), Qt.ForegroundRole).name() == "#067647"
    finally:
        set_theme_tokens("DarkTheme")


def test_selection_actions_have_explicit_disabled_light_theme_style() -> None:
    set_theme_tokens("LightTheme")
    try:
        stylesheet = load_stylesheet("main_window.qss")
        assert "QPushButton#SelectionActionButton:disabled" in stylesheet
        assert "QToolButton#SelectionActionMenuButton:disabled" in stylesheet
        assert "background: #e5e7eb;" in stylesheet
        assert "color: #475569;" in stylesheet
    finally:
        set_theme_tokens("DarkTheme")
