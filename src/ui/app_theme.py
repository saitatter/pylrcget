from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ui.style_loader import load_stylesheet
from ui.theme_tokens import STYLE_TOKENS, set_theme_tokens


def _prefers_dark(app: QApplication) -> bool | None:
    style_hints = app.styleHints()
    color_scheme = getattr(style_hints, "colorScheme", None)
    if callable(color_scheme):
        return color_scheme() == Qt.ColorScheme.Dark
    return None


def apply_app_theme(app: QApplication, theme_mode: str | None = None) -> None:
    app.setStyle("Fusion")
    set_theme_tokens(theme_mode, prefers_dark=_prefers_dark(app))

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
