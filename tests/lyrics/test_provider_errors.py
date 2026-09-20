from __future__ import annotations

import pytest
import requests

from core.lrclib_client import LrcLibError
from lyrics.providers import (
    ProviderError,
    ProviderErrorKind,
    classify_provider_error,
)
from lyrics.providers.tidal import TidalCatalogueError
from lyrics.providers.tidal_transport import (
    OfficialTidalLyricsError,
)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (LrcLibError(404, "Not Found", "missing"), ProviderErrorKind.NOT_FOUND),
        (LrcLibError(429, "Too Many Requests", "slow down"), ProviderErrorKind.RATE_LIMITED),
        (TidalCatalogueError(401, "expired"), ProviderErrorKind.AUTH_EXPIRED),
        (TidalCatalogueError(403, "forbidden"), ProviderErrorKind.AUTH_REQUIRED),
        (TidalCatalogueError(503, "unavailable"), ProviderErrorKind.TEMPORARY),
        (requests.exceptions.Timeout("slow"), ProviderErrorKind.TEMPORARY),
        (OfficialTidalLyricsError("expired", status_code=401), ProviderErrorKind.AUTH_EXPIRED),
        (OfficialTidalLyricsError("slow", status_code=429), ProviderErrorKind.RATE_LIMITED),
        (ValueError("bad payload"), ProviderErrorKind.INVALID_RESPONSE),
        (RuntimeError("temporary provider error"), ProviderErrorKind.TEMPORARY),
    ],
)
def test_legacy_provider_errors_are_classified(error, kind):
    assert classify_provider_error(error) is kind


def test_typed_provider_error_keeps_explicit_kind_and_context():
    error = ProviderError(
        "tidal",
        ProviderErrorKind.UNSUPPORTED,
        "catalogue endpoint unavailable",
        status_code=501,
    )

    assert classify_provider_error(error) is ProviderErrorKind.UNSUPPORTED
    assert error.provider_id == "tidal"
    assert error.status_code == 501
