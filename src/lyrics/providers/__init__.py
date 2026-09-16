"""Lyrics provider contracts and provider implementations."""

from .contracts import (
    DownloadMode,
    LyricsProvider,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    TrackLookupContext,
)
from .lrclib import LrclibProvider
from .matching import (
    MatchQuality,
    TrackMatchMetadata,
    TrackMatchScore,
    normalize_isrc,
    normalize_match_text,
    provider_result_metadata,
    score_track_match,
)
from .router import (
    ACCEPT_FINAL,
    CONTINUE,
    KEEP_AS_FALLBACK,
    REJECT,
    LyricsProviderRouter,
    LyricsResultSelector,
    SelectionDecision,
)
from .tidal import (
    TidalCatalogueClient,
    TidalCatalogueError,
    TidalCatalogueNotFoundError,
    TidalTrack,
    TidalTrackResolution,
)

__all__ = [
    "ACCEPT_FINAL",
    "CONTINUE",
    "KEEP_AS_FALLBACK",
    "REJECT",
    "DownloadMode",
    "LrclibProvider",
    "LyricsProvider",
    "LyricsProviderCapabilities",
    "LyricsProviderResult",
    "LyricsProviderRouter",
    "LyricsResultSelector",
    "MatchQuality",
    "SelectionDecision",
    "TidalCatalogueClient",
    "TidalCatalogueError",
    "TidalCatalogueNotFoundError",
    "TidalTrack",
    "TidalTrackResolution",
    "TrackLookupContext",
    "TrackMatchMetadata",
    "TrackMatchScore",
    "normalize_isrc",
    "normalize_match_text",
    "provider_result_metadata",
    "score_track_match",
]
