from __future__ import annotations

import base64
import sys
from pathlib import Path

from ui.theme_tokens import STYLE_TOKENS


def _ui_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "ui"
    return Path(__file__).resolve().parent


def asset_path(*parts: str) -> Path:
    return _ui_base_dir().joinpath(*parts)


def _update_chevron_icon(color_hex: str) -> None:
    try:
        svg_path = asset_path("assets", "icons", "chevron-down.svg")
        svg_content = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color_hex}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="m6 9 6 6 6-6"/></svg>'
        )
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(svg_content, encoding="utf-8")
    except Exception:
        pass


def load_stylesheet(name: str, **replacements: str) -> str:
    text_muted_color = STYLE_TOKENS.get("color-text-muted", "#94a3b8")
    _update_chevron_icon(text_muted_color)

    content = asset_path("qss", name).read_text(encoding="utf-8")
    asset_url = asset_path().as_posix()
    content = content.replace("{{asset-url}}", asset_url)

    for key, value in STYLE_TOKENS.items():
        content = content.replace("{{" + key + "}}", value)
    for key, value in replacements.items():
        content = content.replace("{{" + key + "}}", value)
    return content
