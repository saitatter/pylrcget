from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ui.style_loader import load_stylesheet


def apply_app_theme(app: QApplication) -> None:
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#020617"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e5e7eb"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#020617"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#030712"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#020617"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e5e7eb"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e5e7eb"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#0b1222"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e5e7eb"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#38bdf8"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#020617"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#38bdf8"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6b7280"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#1f2937"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))

    disabled_text = QColor("#6b7280")
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor("#1f2937"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor("#9ca3af"))

    app.setPalette(palette)
    app.setStyleSheet(load_stylesheet("app.qss"))
