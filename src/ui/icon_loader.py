from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ui.style_loader import asset_path


def load_app_icon() -> QIcon:
    svg_path = asset_path("assets", "app-icon.svg")
    icon = QIcon(str(svg_path))
    if not icon.isNull():
        return icon
    return load_svg_icon("audio-lines.svg", 32)


def load_svg_icon(name: str, size: int = 20, color: str = "#e5e7eb") -> QIcon:
    return QIcon(_render_svg_to_pixmap(name, size, color))


def load_svg_pixmap(name: str, size: int = 56, color: str = "#94a3b8") -> QPixmap:
    return _render_svg_to_pixmap(name, size, color)


def _render_svg_to_pixmap(name: str, size: int, color: str) -> QPixmap:
    svg = _load_svg_markup(name, color)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if not svg:
        return pixmap

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return pixmap

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return pixmap

@lru_cache(maxsize=64)
def _load_svg_markup(name: str, color: str) -> str:
    try:
        svg_path = asset_path("assets", "icons", name)
        content = svg_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return content.replace("currentColor", color)
