from __future__ import annotations

from typing import Literal

LyricsSource = Literal[
    "lrclib",
    "musixmatch",
    "tidal",
    "external",
    "embedded",
    "sidecar",
    "manual",
    "ai",
    "unknown",
]

KNOWN_LYRICS_SOURCES = frozenset(
    {"lrclib", "musixmatch", "tidal", "external", "embedded", "sidecar", "manual", "ai", "unknown"}
)


def normalize_lyrics_source(source: str | None) -> str | None:
    if source is None:
        return None
    normalized = str(source).strip().casefold()
    if not normalized:
        return None
    return normalized if normalized in KNOWN_LYRICS_SOURCES else "unknown"
