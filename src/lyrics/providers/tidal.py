from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from urllib.parse import quote

import requests

from .contracts import TrackLookupContext
from .diagnostics import build_lookup_diagnostics, log_lookup_diagnostics
from .matching import (
    MatchQuality,
    TrackMatchMetadata,
    TrackMatchScore,
    normalize_isrc,
    score_track_match,
)

logger = logging.getLogger(__name__)

TIDAL_CATALOGUE_BASE_URL = "https://openapi.tidal.com/v2"
TIDAL_DEFAULT_TIMEOUT_S = 10.0
_TIDAL_ID_RE = re.compile(r"^[A-Za-z0-9:_-]+$")


class TidalCatalogueError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = int(status_code)
        self.message = message
        super().__init__(f"TIDAL catalogue request failed ({self.status_code}): {message}")


class TidalCatalogueNotFoundError(TidalCatalogueError):
    pass


@dataclass(frozen=True, slots=True)
class TidalTrack:
    provider_track_id: str
    title: str | None
    artists: tuple[str, ...]
    album: str | None
    album_artist: str | None
    duration_seconds: float | None
    track_number: int | None
    isrc: str | None

    def match_metadata(self) -> TrackMatchMetadata:
        return TrackMatchMetadata(
            title=self.title,
            artists=self.artists,
            album=self.album,
            album_artist=self.album_artist,
            duration_seconds=self.duration_seconds,
            track_number=self.track_number,
            isrc=self.isrc,
        )


@dataclass(frozen=True, slots=True)
class TidalTrackResolution:
    track: TidalTrack
    score: TrackMatchScore


class TidalCatalogueClient:
    """Authorized TIDAL catalogue client; it does not retrieve lyrics."""

    def __init__(
        self,
        access_token: str | None = None,
        *,
        country_code: str | None = None,
        base_url: str = TIDAL_CATALOGUE_BASE_URL,
        session: requests.Session | None = None,
        timeout_s: float = TIDAL_DEFAULT_TIMEOUT_S,
        search_limit: int = 10,
    ) -> None:
        self._access_token = access_token
        self.country_code = country_code
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self.timeout_s = float(timeout_s)
        self.search_limit = max(1, int(search_limit))

    def lookup_by_isrc(self, isrc: str) -> list[TidalTrack]:
        normalized = normalize_isrc(isrc)
        if normalized is None:
            return []
        try:
            payload = self._get(
                "/tracks",
                params={
                    "filter[isrc]": normalized,
                    "include": "artists,albums",
                },
            )
        except TidalCatalogueNotFoundError:
            return []
        return _parse_tracks(payload)

    def search_tracks(self, title: str, artist: str) -> list[TidalTrack]:
        query = " ".join(part.strip() for part in (artist, title) if part and part.strip())
        if not query:
            return []
        encoded_query = quote(query, safe="")
        try:
            payload = self._get(
                f"/searchResults/{encoded_query}/relationships/tracks",
                params={
                    "include": "artists,albums",
                    "limit": self.search_limit,
                },
            )
        except TidalCatalogueNotFoundError:
            return []
        return _parse_tracks(payload)

    def get_track(self, provider_track_id: str) -> TidalTrack:
        if not _TIDAL_ID_RE.fullmatch(str(provider_track_id)):
            raise ValueError("Invalid TIDAL track id")
        payload = self._get(
            f"/tracks/{quote(str(provider_track_id), safe='')}",
            params={"include": "artists,albums"},
        )
        tracks = _parse_tracks(payload)
        if not tracks:
            raise TidalCatalogueNotFoundError(404, "Track was not returned")
        return tracks[0]

    def resolve_track(self, local: TrackLookupContext) -> TidalTrackResolution | None:
        started_at = time.perf_counter()
        candidates: list[TidalTrack] = []
        lookup_method = "metadata"
        isrc_lookup = "not_requested"
        if local.isrc:
            candidates.extend(self.lookup_by_isrc(local.isrc))
            isrc_lookup = "hit" if candidates else "miss"
            lookup_method = "isrc" if candidates else "metadata"
        if not candidates:
            primary_artist = local.artists[0] if local.artists else ""
            candidates.extend(self.search_tracks(local.title or "", primary_artist))
        if not candidates:
            diagnostics = build_lookup_diagnostics(
                provider="tidal",
                track_id=local.track_id,
                lookup_method=lookup_method,
                isrc_lookup=isrc_lookup,
                candidate_count=0,
                selected_remote_id=None,
                score=None,
                reason="no_candidates",
                result_type="no_match",
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
            )
            log_lookup_diagnostics(logger, diagnostics)
            return None

        scored = [
            (score_track_match(local, candidate.match_metadata()), candidate)
            for candidate in candidates
        ]
        scored.sort(key=lambda item: (-item[0].score, item[1].provider_track_id))
        score, track = scored[0]
        if score.quality not in {MatchQuality.EXACT_ID, MatchQuality.HIGH}:
            diagnostics = build_lookup_diagnostics(
                provider="tidal",
                track_id=local.track_id,
                lookup_method=lookup_method,
                isrc_lookup=isrc_lookup,
                candidate_count=len(candidates),
                selected_remote_id=track.provider_track_id,
                score=score.score,
                reason="low_confidence",
                result_type="low_confidence",
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
            )
            log_lookup_diagnostics(logger, diagnostics)
            return None
        diagnostics = build_lookup_diagnostics(
            provider="tidal",
            track_id=local.track_id,
            lookup_method=lookup_method,
            isrc_lookup=isrc_lookup,
            candidate_count=len(candidates),
            selected_remote_id=track.provider_track_id,
            score=score.score,
            reason=score.method,
            result_type="match",
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        )
        log_lookup_diagnostics(logger, diagnostics)
        return TidalTrackResolution(
            track=track,
            score=replace(score, diagnostics={**score.diagnostics, **diagnostics}),
        )

    def _get(self, path: str, *, params: dict[str, object]) -> dict:
        headers = {
            "Accept": "application/vnd.tidal.v1+json",
            "Content-Type": "application/vnd.tidal.v1+json",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        response = self._session.get(
            f"{self.base_url}{path}",
            params=self._request_params(params),
            headers=headers,
            timeout=self.timeout_s,
        )
        if response.status_code == 404:
            raise TidalCatalogueNotFoundError(404, "Not found")
        if response.status_code >= 400:
            message = (getattr(response, "text", "") or "")[:200]
            raise TidalCatalogueError(response.status_code, message or "HTTP error")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TidalCatalogueError(502, "Invalid JSON response") from exc
        if not isinstance(payload, dict):
            raise TidalCatalogueError(502, "Unexpected JSON response")
        return payload

    def _request_params(self, params: dict[str, object]) -> dict[str, object]:
        result = dict(params)
        country = (self.country_code or "").strip()
        if country and country.casefold() != "auto":
            result["countryCode"] = country.upper()
        return result


def _parse_tracks(payload: dict) -> list[TidalTrack]:
    data = payload.get("data", [])
    items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    included = payload.get("included", [])
    included_by_key = {
        (str(item.get("type", "")), str(item.get("id", ""))): item
        for item in included
        if isinstance(item, dict)
    }
    tracks: list[TidalTrack] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        track = _parse_track(item, included_by_key)
        if track is None or track.provider_track_id in seen_ids:
            continue
        seen_ids.add(track.provider_track_id)
        tracks.append(track)
    return tracks


def _parse_track(item: dict, included: Mapping[tuple[str, str], dict]) -> TidalTrack | None:
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
    provider_track_id = str(item.get("id") or attributes.get("id") or "").strip()
    if not provider_track_id:
        return None

    artist_values = _related_values(item, attributes, "artists", included)
    if not artist_values:
        artist_values = _text_values(attributes.get("artist"))
    album_values = _related_values(item, attributes, "albums", included)
    if not album_values:
        album_values = _related_values(item, attributes, "album", included)
    album = album_values[0] if album_values else _first_text(attributes.get("album"))
    duration = _number(attributes.get("duration", attributes.get("durationSeconds")))
    track_number = _integer(attributes.get("trackNumber", attributes.get("track_number")))
    return TidalTrack(
        provider_track_id=provider_track_id,
        title=_first_text(attributes.get("title", attributes.get("name"))),
        artists=tuple(artist_values),
        album=album,
        album_artist=_first_text(attributes.get("albumArtist", attributes.get("album_artist"))),
        duration_seconds=duration,
        track_number=track_number,
        isrc=normalize_isrc(_first_text(attributes.get("isrc"))),
    )


def _related_values(
    item: dict,
    attributes: dict,
    relationship_name: str,
    included: Mapping[tuple[str, str], dict],
) -> list[str]:
    direct = attributes.get(relationship_name)
    values = _text_values(direct)
    if values:
        return values
    relationships = item.get("relationships")
    relationship = relationships.get(relationship_name) if isinstance(relationships, dict) else None
    related_data = relationship.get("data") if isinstance(relationship, dict) else None
    refs = related_data if isinstance(related_data, list) else [related_data] if isinstance(related_data, dict) else []
    values = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        related = included.get((str(ref.get("type", "")), str(ref.get("id", ""))))
        if related is None:
            continue
        related_attributes = related.get("attributes") if isinstance(related.get("attributes"), dict) else related
        value = _first_text(related_attributes.get("name", related_attributes.get("title")))
        if value:
            values.append(value)
    return values


def _text_values(value) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        text = _first_text(item)
        if text:
            result.append(text)
    return result


def _first_text(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("name", value.get("title"))
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
