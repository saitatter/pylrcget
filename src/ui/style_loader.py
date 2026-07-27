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


def _svg_chevron(color_hex: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color_hex}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="m6 9 6 6 6-6"/></svg>'
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def load_stylesheet(name: str, **replacements: str) -> str:
    content = asset_path("qss", name).read_text(encoding="utf-8")
    asset_url = asset_path().as_posix()
    content = content.replace("{{asset-url}}", asset_url)

    text_muted_color = STYLE_TOKENS.get("color-text-muted", "#94a3b8")
    accent_color = STYLE_TOKENS.get("color-accent", "#38bdf8")
    content = content.replace("{{chevron-down-uri}}", _svg_chevron(text_muted_color))
    content = content.replace("{{chevron-down-hover-uri}}", _svg_chevron(accent_color))

    for key, value in STYLE_TOKENS.items():
        content = content.replace("{{" + key + "}}", value)
    for key, value in replacements.items():
        content = content.replace("{{" + key + "}}", value)
    return content
