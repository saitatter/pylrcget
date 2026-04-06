from __future__ import annotations

import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "ui" / "qss"
    return Path(__file__).resolve().parent / "qss"


def load_stylesheet(name: str, **replacements: str) -> str:
    content = (_base_dir() / name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content
