from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ui.style_loader import load_stylesheet
from ui.theme_tokens import STYLE_TOKENS, set_theme_tokens

FONT_SIZE_POINTS = {
    "small": 9.0,
    "normal": 10.0,
    "large": 11.0,
}


def _prefers_dark(app: QApplication) -> bool | None:
    style_hints = app.styleHints()
    color_scheme = getattr(style_hints, "colorScheme", None)
    if callable(color_scheme):
        return color_scheme() == Qt.ColorScheme.Dark
    return None


def _base_app_font(app: QApplication) -> QFont:
    stored = app.property("_lrcget_base_font")
    if isinstance(stored, QFont):
        return QFont(stored)

    font = QFont(app.font())
    app.setProperty("_lrcget_base_font", QFont(font))
    return font


def _apply_app_font(
    app: QApplication,
    *,
    ui_scale_percent: int = 100,
    font_size_mode: str = "normal",
) -> None:
    base_font = _base_app_font(app)
    scale = max(75, min(200, int(ui_scale_percent or 100))) / 100.0
    base_points = FONT_SIZE_POINTS.get(str(font_size_mode or "normal"), FONT_SIZE_POINTS["normal"])

    font = QFont(base_font)
    font.setPointSizeF(base_points * scale)
    app.setFont(font)


def apply_app_theme(
    app: QApplication,
    theme_mode: str | None = None,
    *,
    ui_scale_percent: int = 100,
    font_size_mode: str = "normal",
) -> None:
    app.setStyle("Fusion")
    set_theme_tokens(theme_mode, prefers_dark=_prefers_dark(app))
    _apply_app_font(app, ui_scale_percent=ui_scale_percent, font_size_mode=font_size_mode)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(STYLE_TOKENS["color-bg-app"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(STYLE_TOKENS["color-text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(STYLE_TOKENS["color-bg-app"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(STYLE_TOKENS["color-bg-panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(STYLE_TOKENS["color-bg-panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(STYLE_TOKENS["color-text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(STYLE_TOKENS["color-text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(STYLE_TOKENS["color-bg-control"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(STYLE_TOKENS["color-text"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(STYLE_TOKENS["color-accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(STYLE_TOKENS["color-bg-app"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(STYLE_TOKENS["color-accent"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(STYLE_TOKENS["color-placeholder"]))
    palette.setColor(QPalette.ColorRole.Mid, QColor(STYLE_TOKENS["color-border"]))
    palette.setColor(QPalette.ColorRole.Dark, QColor(STYLE_TOKENS["color-border-strong"]))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))

    disabled_text = QColor(STYLE_TOKENS["color-text-muted"])
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(STYLE_TOKENS["color-border"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(STYLE_TOKENS["color-text-soft"]))

    app.setPalette(palette)
    app.setStyleSheet(load_stylesheet("app.qss"))
