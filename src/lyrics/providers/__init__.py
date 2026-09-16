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
    local_metadata_fingerprint,
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
from .tidal_auth import TidalAccessContext, TidalSessionProvider
from .tidal_cache import CachedTidalCatalogueResolver
from .tidal_transport import (
    ExternalTidalHelperError,
    ExternalTidalLyricsTransport,
    TidalLyricsPayload,
    TidalLyricsTransport,
)

__all__ = [
    "ACCEPT_FINAL",
    "CONTINUE",
    "KEEP_AS_FALLBACK",
    "REJECT",
    "CachedTidalCatalogueResolver",
    "DownloadMode",
    "ExternalTidalHelperError",
    "ExternalTidalLyricsTransport",
    "LrclibProvider",
    "LyricsProvider",
    "LyricsProviderCapabilities",
    "LyricsProviderResult",
    "LyricsProviderRouter",
    "LyricsResultSelector",
    "MatchQuality",
    "SelectionDecision",
    "TidalAccessContext",
    "TidalCatalogueClient",
    "TidalCatalogueError",
    "TidalCatalogueNotFoundError",
    "TidalLyricsPayload",
    "TidalLyricsTransport",
    "TidalSessionProvider",
    "TidalTrack",
    "TidalTrackResolution",
    "TrackLookupContext",
    "TrackMatchMetadata",
    "TrackMatchScore",
    "local_metadata_fingerprint",
    "normalize_isrc",
    "normalize_match_text",
    "provider_result_metadata",
    "score_track_match",
]
