from __future__ import annotations

from enum import Enum

import requests

from core.lrclib_client import LrcLibError

from .tidal import TidalCatalogueError
from .tidal_transport import ExternalTidalHelperError, OfficialTidalLyricsError


class ProviderErrorKind(str, Enum):
    NOT_FOUND = "not_found"
    AUTH_REQUIRED = "auth_required"
    AUTH_EXPIRED = "auth_expired"
    RATE_LIMITED = "rate_limited"
    TEMPORARY = "temporary"
    UNSUPPORTED = "unsupported"
    LOW_CONFIDENCE = "low_confidence"
    INVALID_RESPONSE = "invalid_response"
    CANCELLED = "cancelled"
    FATAL = "fatal"


class ProviderError(RuntimeError):
    """Optional typed error for provider implementations and integrations."""

    def __init__(
        self,
        provider_id: str,
        kind: ProviderErrorKind,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        self.provider_id = str(provider_id)
        self.kind = kind
        self.status_code = status_code
        super().__init__(message)


def classify_provider_error(error: Exception) -> ProviderErrorKind:
    """Map legacy provider exceptions to stable router behavior."""

    if isinstance(error, ProviderError):
        return error.kind
    if error.__class__.__name__ == "LyricsMatchCancelled":
        return ProviderErrorKind.CANCELLED
    if isinstance(error, ExternalTidalHelperError):
        return ProviderErrorKind.FATAL
    if isinstance(error, OfficialTidalLyricsError):
        if error.status_code is not None:
            return _classify_http_status(error.status_code)
        return ProviderErrorKind.TEMPORARY
    if isinstance(error, TidalCatalogueError):
        return _classify_http_status(error.status_code)
    if isinstance(error, LrcLibError):
        return _classify_http_status(error.status_code)
    if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return ProviderErrorKind.TEMPORARY
    if isinstance(error, ValueError):
        return ProviderErrorKind.INVALID_RESPONSE
    return ProviderErrorKind.TEMPORARY


def _classify_http_status(status_code: int) -> ProviderErrorKind:
    if status_code == 401:
        return ProviderErrorKind.AUTH_EXPIRED
    if status_code == 403:
        return ProviderErrorKind.AUTH_REQUIRED
    if status_code == 404:
        return ProviderErrorKind.NOT_FOUND
    if status_code == 429:
        return ProviderErrorKind.RATE_LIMITED
    if status_code >= 500:
        return ProviderErrorKind.TEMPORARY
    return ProviderErrorKind.INVALID_RESPONSE
