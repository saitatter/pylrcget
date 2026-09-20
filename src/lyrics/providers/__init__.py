"""Lyrics provider contracts and provider implementations."""

from .contracts import (
    DownloadMode,
    LyricsProvider,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    TrackLookupContext,
)
from .diagnostics import (
    build_lookup_diagnostics,
    http_status_category,
    log_lookup_diagnostics,
    lyrics_result_type,
)
from .errors import ProviderError, ProviderErrorKind, classify_provider_error
from .execution import (
    ProviderExecutionCoordinator,
    ProviderExecutionPolicy,
    get_provider_execution_policy,
)
from .health import ProviderHealthState, is_fatal_provider_error
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
from .result_cache import LookupKey, ProviderLookupResultCache
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
from .tidal_auth import (
    KeyringTidalTokenStore,
    TidalAccessContext,
    TidalAuthenticationError,
    TidalOAuthSession,
    TidalSessionProvider,
    TidalTokenStore,
)
from .tidal_cache import CachedTidalCatalogueResolver
from .tidal_provider import TidalCatalogueResolver, TidalProvider
from .tidal_transport import (
    ExternalTidalHelperError,
    ExternalTidalLyricsTransport,
    OfficialTidalLyricsError,
    OfficialTidalLyricsTransport,
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
    "KeyringTidalTokenStore",
    "LookupKey",
    "LrclibProvider",
    "LyricsProvider",
    "LyricsProviderCapabilities",
    "LyricsProviderResult",
    "LyricsProviderRouter",
    "LyricsResultSelector",
    "MatchQuality",
    "OfficialTidalLyricsError",
    "OfficialTidalLyricsTransport",
    "ProviderError",
    "ProviderErrorKind",
    "ProviderExecutionCoordinator",
    "ProviderExecutionPolicy",
    "ProviderHealthState",
    "ProviderLookupResultCache",
    "SelectionDecision",
    "TidalAccessContext",
    "TidalAuthenticationError",
    "TidalCatalogueClient",
    "TidalCatalogueError",
    "TidalCatalogueNotFoundError",
    "TidalCatalogueResolver",
    "TidalLyricsPayload",
    "TidalLyricsTransport",
    "TidalOAuthSession",
    "TidalProvider",
    "TidalSessionProvider",
    "TidalTokenStore",
    "TidalTrack",
    "TidalTrackResolution",
    "TrackLookupContext",
    "TrackMatchMetadata",
    "TrackMatchScore",
    "build_lookup_diagnostics",
    "classify_provider_error",
    "get_provider_execution_policy",
    "http_status_category",
    "is_fatal_provider_error",
    "local_metadata_fingerprint",
    "log_lookup_diagnostics",
    "lyrics_result_type",
    "normalize_isrc",
    "normalize_match_text",
    "provider_result_metadata",
    "score_track_match",
]
