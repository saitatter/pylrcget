from __future__ import annotations

import logging
from collections.abc import Mapping


def build_lookup_diagnostics(
    *,
    provider: str,
    track_id: int | None,
    lookup_method: str,
    isrc_lookup: str,
    candidate_count: int,
    selected_remote_id: str | None,
    score: float | None,
    reason: str,
    result_type: str,
    elapsed_ms: float,
    cache_hit: bool = False,
    http_status_category: str | None = None,
) -> dict[str, object]:
    """Create safe, provider-neutral diagnostics with no filesystem data."""

    return {
        "provider": str(provider),
        "track_id": track_id,
        "lookup_method": str(lookup_method),
        "isrc_lookup": str(isrc_lookup),
        "candidate_count": max(0, int(candidate_count)),
        "selected_remote_id": selected_remote_id,
        "score": round(float(score), 2) if score is not None else None,
        "reason": str(reason),
        "result_type": str(result_type),
        "elapsed_ms": round(max(0.0, float(elapsed_ms)), 2),
        "cache_hit": bool(cache_hit),
        "http_status_category": http_status_category,
    }


def log_lookup_diagnostics(logger: logging.Logger, diagnostics: Mapping[str, object]) -> None:
    """Emit structured fields while keeping the human log message generic."""

    payload = dict(diagnostics)
    logger.debug(
        "lyrics provider lookup",
        extra={
            "lyrics_lookup": payload,
            "lyrics_provider": payload.get("provider"),
            "lyrics_track_id": payload.get("track_id"),
        },
    )


def lyrics_result_type(plain_lyrics: str | None, synced_lyrics: str | None) -> str:
    if synced_lyrics and synced_lyrics.strip():
        return "synced"
    if plain_lyrics and plain_lyrics.strip():
        return "plain"
    return "no_match"


def http_status_category(status_code: int | None) -> str | None:
    if status_code is None:
        return None
    code = int(status_code)
    return f"{code // 100}xx" if 100 <= code <= 599 else "unknown"
