from __future__ import annotations

import sys
from pathlib import Path

from ui.theme_tokens import STYLE_TOKENS


def _ui_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "ui"
    return Path(__file__).resolve().parent


def asset_path(*parts: str) -> Path:
    return _ui_base_dir().joinpath(*parts)


def load_stylesheet(name: str, **replacements: str) -> str:
    content = asset_path("qss", name).read_text(encoding="utf-8")
    for key, value in STYLE_TOKENS.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    for key, value in replacements.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content
