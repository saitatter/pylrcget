from __future__ import annotations

import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import requests

from .contracts import DownloadMode, TrackLookupContext


@dataclass(slots=True)
class TidalLyricsPayload:
    plain_lyrics: str | None
    synced_lyrics: str | None
    source: str | None = None
    country_code: str | None = None


class TidalLyricsTransport(Protocol):
    """Lyrics transport kept independent from TIDAL catalogue resolution."""

    def get_lyrics(
        self,
        tidal_track_id: str,
        *,
        cancel_event: threading.Event | None = None,
        track: TrackLookupContext | None = None,
        requested_mode: DownloadMode = "prefer_synced",
    ) -> TidalLyricsPayload | None:
        ...


class OfficialTidalLyricsError(RuntimeError):
    """Raised when the official TIDAL lyrics relation cannot be read."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        self.status_code = status_code
        self.retry_after_s = retry_after_s
        super().__init__(message)


class OfficialTidalLyricsTransport:
    """Read lyrics exposed by the official TIDAL catalogue API.

    TIDAL exposes lyrics as an optional relationship on the track resource.
    The public API may return an empty relationship for a track; that is a
    clean miss and lets the provider router continue to the next source.
    """

    provider_id = "tidal"
    base_url = "https://openapi.tidal.com/v2"
    default_country_fallbacks = ("RO", "US", "GB", "DE", "MY")

    def __init__(
        self,
        access_token: str,
        *,
        country_code: str | None = None,
        country_codes: Sequence[str] | None = None,
        session: requests.Session | None = None,
        timeout_s: float = 10.0,
        on_rate_limit: Callable[[float], None] | None = None,
    ) -> None:
        self.access_token = str(access_token).strip()
        if not self.access_token:
            raise ValueError("TIDAL access token is required")
        self.country_code = country_code
        self.country_codes = _normalize_country_codes(
            country_code,
            country_codes,
            fallback_codes=self.default_country_fallbacks,
        )
        self.session = session or requests.Session()
        self.timeout_s = max(0.1, float(timeout_s))
        self.on_rate_limit = on_rate_limit

    def get_lyrics(
        self,
        tidal_track_id: str,
        *,
        cancel_event: threading.Event | None = None,
        track: TrackLookupContext | None = None,
        requested_mode: DownloadMode = "prefer_synced",
    ) -> TidalLyricsPayload | None:
        del track, requested_mode
        if cancel_event is not None and cancel_event.is_set():
            return None
        for country in self.country_codes:
            if cancel_event is not None and cancel_event.is_set():
                return None
            params: dict[str, object] = {"include": "lyrics"}
            if country is not None:
                params["countryCode"] = country
            try:
                response = self.session.get(
                    f"{self.base_url}/tracks/{tidal_track_id}",
                    params=params,
                    headers={
                        "Accept": "application/vnd.api+json",
                        "Authorization": f"Bearer {self.access_token}",
                    },
                    timeout=self.timeout_s,
                )
            except requests.RequestException as exc:
                raise OfficialTidalLyricsError(f"TIDAL lyrics request failed: {exc}") from exc
            if response.status_code == 404:
                continue
            retry_after = None
            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
                if retry_after is not None and self.on_rate_limit is not None:
                    self.on_rate_limit(retry_after)
            if response.status_code >= 400:
                detail = (response.text or "")[:300]
                raise OfficialTidalLyricsError(
                    f"TIDAL lyrics request failed ({response.status_code}): {detail or 'HTTP error'}",
                    status_code=response.status_code,
                    retry_after_s=retry_after,
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise OfficialTidalLyricsError("TIDAL lyrics response was not valid JSON") from exc
            if not isinstance(payload, dict):
                raise OfficialTidalLyricsError("TIDAL lyrics response was not a JSON object")
            lyrics = _parse_official_lyrics_payload(payload)
            if lyrics is not None:
                lyrics.country_code = country
                return lyrics
        return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("TIDAL lyrics fields must be strings or null")
    return value.strip() or None


def _parse_official_lyrics_payload(payload: dict[str, object]) -> TidalLyricsPayload | None:
    """Accept the JSON:API relationship shape and tolerate future field names."""

    objects: list[dict[str, object]] = []
    data = payload.get("data")
    if isinstance(data, dict):
        objects.append(data)
        relationships = data.get("relationships")
        if isinstance(relationships, dict):
            lyrics_relationship = relationships.get("lyrics")
            if isinstance(lyrics_relationship, dict):
                relation_data = lyrics_relationship.get("data")
                if isinstance(relation_data, dict):
                    objects.append(relation_data)
                elif isinstance(relation_data, list):
                    objects.extend(item for item in relation_data if isinstance(item, dict))
    included = payload.get("included")
    if isinstance(included, list):
        objects.extend(item for item in included if isinstance(item, dict))

    plain: str | None = None
    synced: str | None = None
    for item in objects:
        attributes = item.get("attributes")
        if not isinstance(attributes, dict):
            attributes = item
        synced = synced or _first_text(
            attributes,
            "lrcText",
            "lrc_text",
            "syncedLyrics",
            "synced_lyrics",
            "subtitles",
        )
        plain = plain or _first_text(
            attributes,
            "plainText",
            "plain_text",
            "plainLyrics",
            "plain_lyrics",
        )
        if plain is None:
            generic = _first_text(attributes, "lyrics", "text")
            if generic:
                if _looks_synced(generic):
                    synced = synced or generic
                else:
                    plain = generic
    if not plain and not synced:
        return None
    return TidalLyricsPayload(plain_lyrics=plain, synced_lyrics=synced, source="official")


def _normalize_country_codes(
    country_code: str | None,
    country_codes: Sequence[str] | None,
    *,
    fallback_codes: Sequence[str],
) -> tuple[str | None, ...]:
    values = country_codes if country_codes is not None else ()
    normalized: list[str | None] = []
    for raw in values:
        code = str(raw or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", code) and code not in normalized:
            normalized.append(code)
    primary = str(country_code or "").strip().upper()
    if primary and primary != "AUTO" and re.fullmatch(r"[A-Z]{2}", primary):
        normalized.insert(0, primary)
    elif not normalized:
        normalized.append(None)
        for raw in fallback_codes:
            code = str(raw or "").strip().upper()
            if re.fullmatch(r"[A-Z]{2}", code) and code not in normalized:
                normalized.append(code)
    return tuple(normalized)


def _first_text(attributes: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = _optional_text(attributes.get(key))
        if value:
            return value
    return None


def _looks_synced(value: str) -> bool:
    return bool(re.search(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]", value))


def _retry_after_seconds(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None
