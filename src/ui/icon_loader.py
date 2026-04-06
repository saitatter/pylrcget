from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ui.style_loader import asset_path


def load_svg_icon(name: str, size: int = 20, color: str = "#e5e7eb") -> QIcon:
    svg = _load_svg_markup(name, color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def load_svg_pixmap(name: str, size: int = 56, color: str = "#94a3b8") -> QPixmap:
    svg = _load_svg_markup(name, color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def _load_svg_markup(name: str, color: str) -> str:
    svg_path = asset_path("assets", "icons", name)
    content = svg_path.read_text(encoding="utf-8")
    return content.replace("currentColor", color)
