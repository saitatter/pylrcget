from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from .contracts import (
    DownloadMode,
    LyricsProvider,
    LyricsProviderResult,
    TrackLookupContext,
)

ACCEPT_FINAL: Final = "ACCEPT_FINAL"
KEEP_AS_FALLBACK: Final = "KEEP_AS_FALLBACK"
REJECT: Final = "REJECT"
CONTINUE: Final = "CONTINUE"


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    action: str
    candidate: LyricsProviderResult | None = None


class LyricsResultSelector:
    """Apply download-mode semantics to provider-neutral results."""

    def consider(
        self,
        candidate: LyricsProviderResult,
        requested_mode: DownloadMode,
    ) -> SelectionDecision:
        has_plain = bool((candidate.plain_lyrics or "").strip())
        has_synced = bool((candidate.synced_lyrics or "").strip())
        if not has_plain and not has_synced:
            return SelectionDecision(REJECT)

        if requested_mode == "synced_only":
            if has_synced:
                return SelectionDecision(ACCEPT_FINAL, candidate)
            return SelectionDecision(KEEP_AS_FALLBACK, candidate)

        if requested_mode == "plain_only":
            return SelectionDecision(ACCEPT_FINAL, candidate)

        if has_synced:
            return SelectionDecision(ACCEPT_FINAL, candidate)
        return SelectionDecision(KEEP_AS_FALLBACK, candidate)


class LyricsProviderRouter:
    """Try providers in priority order and select one result for the app."""

    def __init__(self, providers: Sequence[LyricsProvider]) -> None:
        self.providers = tuple(providers)

    def lookup(
        self,
        track: TrackLookupContext,
        *,
        requested_mode: DownloadMode,
        cancel_event: threading.Event | None = None,
    ) -> LyricsProviderResult | None:
        selector = LyricsResultSelector()
        fallback: LyricsProviderResult | None = None

        for index, provider in enumerate(self.providers):
            if cancel_event is not None and cancel_event.is_set():
                return None
            try:
                candidate = provider.lookup(
                    track,
                    requested_mode=requested_mode,
                    cancel_event=cancel_event,
                )
            except Exception:
                if index == len(self.providers) - 1:
                    raise
                continue
            if candidate is None:
                continue

            decision = selector.consider(candidate, requested_mode)
            if decision.action == ACCEPT_FINAL:
                return decision.candidate
            if decision.action == KEEP_AS_FALLBACK and fallback is None:
                fallback = decision.candidate

        return fallback
