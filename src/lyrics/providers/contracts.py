from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Literal, Protocol

DownloadMode = Literal["prefer_synced", "synced_only", "plain_only"]


@dataclass(slots=True, frozen=True)
class TrackLookupContext:
    """Provider-independent metadata used to search for one track's lyrics."""

    track_id: int | None
    file_path: str
    title: str | None
    artists: tuple[str, ...]
    album: str | None
    album_artist: str | None
    duration_seconds: float | None
    track_number: int | None
    isrc: str | None


@dataclass(slots=True)
class LyricsProviderResult:
    """Lyrics and match metadata returned by a provider lookup."""

    provider: str
    provider_track_id: str | None
    plain_lyrics: str | None
    synced_lyrics: str | None
    instrumental: bool
    match_score: float
    match_method: str
    remote_title: str | None
    remote_artist: str | None
    remote_album: str | None
    remote_duration_seconds: float | None
    remote_isrc: str | None
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class LyricsProviderCapabilities:
    """Features exposed by a lyrics provider."""

    plain: bool
    synced: bool
    search: bool
    isrc_lookup: bool
    authentication_required: bool


class LyricsProvider(Protocol):
    """Minimal provider boundary used by the lyrics router."""

    provider_id: str
    display_name: str

    def capabilities(self) -> LyricsProviderCapabilities:
        ...

    def lookup(
        self,
        track: TrackLookupContext,
        *,
        requested_mode: DownloadMode,
        cancel_event: threading.Event | None = None,
    ) -> LyricsProviderResult | None:
        ...
