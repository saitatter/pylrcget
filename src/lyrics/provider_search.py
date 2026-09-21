from __future__ import annotations

import threading
from collections.abc import Callable

from lyrics.providers.contracts import (
    LyricsProvider,
    LyricsSearchContext,
    LyricsSearchResult,
)
from lyrics.providers.lrclib import LrclibProvider
from lyrics.providers.musixmatch import MusixmatchClient, MusixmatchProvider


def build_search_providers(
    lrclib_instance: str,
    settings: dict[str, object],
    *,
    notify: Callable[[str], None] | None = None,
) -> tuple[LyricsProvider, ...]:
    """Build the enabled providers in the configured priority order."""
    raw_enabled = settings.get("enabled")
    enabled = raw_enabled if isinstance(raw_enabled, dict) else {}
    raw_priority = settings.get("priority")
    priority = raw_priority if isinstance(raw_priority, list) else []
    providers: dict[str, LyricsProvider] = {}

    if bool(enabled.get("lrclib", False)):
        providers["lrclib"] = LrclibProvider(lrclib_instance, notify=notify)

    if bool(enabled.get("musixmatch", False)):
        raw_musixmatch = settings.get("musixmatch")
        musixmatch = raw_musixmatch if isinstance(raw_musixmatch, dict) else {}
        providers["musixmatch"] = MusixmatchProvider(
            MusixmatchClient(
                mode=str(musixmatch.get("mode") or "website"),
                api_key=str(musixmatch.get("api_key") or ""),
            ),
            notify=notify,
        )

    ordered: list[LyricsProvider] = []
    for raw_provider_id in priority:
        provider_id = str(raw_provider_id).strip().casefold()
        if provider_id in providers:
            ordered.append(providers[provider_id])
    return tuple(ordered)


def search_configured_providers(
    lrclib_instance: str,
    settings: dict[str, object],
    context: LyricsSearchContext,
    *,
    cancel_event: threading.Event | None = None,
) -> tuple[list[LyricsSearchResult], list[str]]:
    """Search every enabled provider and keep partial results on provider errors."""
    results: list[LyricsSearchResult] = []
    errors: list[str] = []
    providers = build_search_providers(lrclib_instance, settings)
    if not providers:
        return [], ["No enabled lyrics providers."]

    for provider in providers:
        if cancel_event is not None and cancel_event.is_set():
            break
        try:
            results.extend(provider.search(context, cancel_event=cancel_event))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{provider.display_name}: {exc}")
    return results, errors
