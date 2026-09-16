"""Lyrics provider contracts and provider implementations."""

from .contracts import (
    DownloadMode,
    LyricsProvider,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    TrackLookupContext,
)

__all__ = [
    "DownloadMode",
    "LyricsProvider",
    "LyricsProviderCapabilities",
    "LyricsProviderResult",
    "TrackLookupContext",
]
