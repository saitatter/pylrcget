"""Lyrics provider contracts and provider implementations."""

from .contracts import (
    DownloadMode,
    LyricsProvider,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    TrackLookupContext,
)
from .lrclib import LrclibProvider

__all__ = [
    "DownloadMode",
    "LrclibProvider",
    "LyricsProvider",
    "LyricsProviderCapabilities",
    "LyricsProviderResult",
    "TrackLookupContext",
]
