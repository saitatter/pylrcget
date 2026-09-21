from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import quote, urljoin

import requests

from .contracts import (
    DownloadMode,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    TrackLookupContext,
)
from .diagnostics import (
    build_lookup_diagnostics,
    log_lookup_diagnostics,
    lyrics_result_type,
)
from .errors import ProviderError, ProviderErrorKind
from .matching import MatchQuality, TrackMatchMetadata, score_track_match

logger = logging.getLogger(__name__)

MUSIXMATCH_PROVIDER_ID = "musixmatch"
MUSIXMATCH_WEBSITE_BASE_URL = "https://www.musixmatch.com"
MUSIXMATCH_DESKTOP_BASE_URL = "https://apic-desktop.musixmatch.com/ws/1.1/"
MUSIXMATCH_OFFICIAL_BASE_URL = "https://api.musixmatch.com/ws/1.1/"
MUSIXMATCH_APP_ID = "web-desktop-app-v1.0"
_TIMESTAMP_RE = re.compile(r"\[\d{1,3}:\d{2}(?:\.\d{1,3})?\]")


class MusixmatchError(ProviderError):
    """A typed error from the Musixmatch public or desktop API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        kind: ProviderErrorKind | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        resolved_kind = kind or _error_kind_for_status(status_code)
        super().__init__(MUSIXMATCH_PROVIDER_ID, resolved_kind, message, status_code=status_code)
        self.retry_after_s = retry_after_s


@dataclass(frozen=True, slots=True)
class MusixmatchTrack:
    provider_track_id: str
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    isrc: str | None
    instrumental: bool
    has_lyrics: bool
    has_subtitles: bool
    share_url: str | None = None


@dataclass(frozen=True, slots=True)
class MusixmatchLyrics:
    plain_lyrics: str | None
    synced_lyrics: str | None
    instrumental: bool = False


class MusixmatchClient:
    """Small client for the official API and the public desktop transport.

    The desktop transport is the compatibility path used by the old desktop
    Musixmatch clients. It obtains a short-lived user token and does not need a
    user account. An official API key can be configured when available.
    """

    def __init__(
        self,
        *,
        mode: str = "website",
        api_key: str = "",
        session: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        normalized_mode = str(mode or "website").strip().casefold()
        if normalized_mode not in {"website", "desktop", "official"}:
            raise ValueError("Musixmatch mode must be 'website', 'desktop' or 'official'")
        if normalized_mode == "official" and not str(api_key or "").strip():
            raise MusixmatchError(
                "Musixmatch API mode requires an API key.",
                kind=ProviderErrorKind.AUTH_REQUIRED,
            )
        self.mode = normalized_mode
        self.api_key = str(api_key or "").strip()
        self.base_url = (base_url or self._default_base_url()).rstrip("/") + "/"
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
                ),
            }
        )
        self._token: str | None = None
        self._token_lock = threading.Lock()
        self._website_lyrics: dict[str, MusixmatchLyrics] = {}

    def search(self, track: TrackLookupContext, *, cancel_event: threading.Event | None = None) -> list[MusixmatchTrack]:
        self._check_cancelled(cancel_event)
        if self.mode == "website":
            website_tracks = self._search_website(track, cancel_event=cancel_event)
            if website_tracks:
                return website_tracks
            # The web page has no search API that is stable for desktop clients.
            # Keep the legacy desktop endpoint as a best-effort fallback.
            return self._search_desktop(track, cancel_event=cancel_event)
        return self._search_desktop(track, cancel_event=cancel_event) if self.mode == "desktop" else self._search_official(
            track,
            cancel_event=cancel_event,
        )

    def _search_official(
        self,
        track: TrackLookupContext,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[MusixmatchTrack]:
        artist = next(iter(track.artists), "")
        params: dict[str, object] = {
            "page": 1,
            "page_size": 20,
            "s_track_rating": "desc",
            "q": " ".join(part for part in (artist, track.title or "") if part).strip(),
            "q_track": track.title or "",
            "q_artist": artist,
            "q_album": track.album or "",
        }
        params.update({"apikey": self.api_key, "f_has_lyrics": 1})
        payload = self._request_json("track.search", params, cancel_event=cancel_event)
        return self._parse_search_tracks(payload)

    def _search_desktop(
        self,
        track: TrackLookupContext,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[MusixmatchTrack]:
        artist = next(iter(track.artists), "")
        params: dict[str, object] = {
            "page": 1,
            "page_size": 20,
            "s_track_rating": "desc",
            "q": " ".join(part for part in (artist, track.title or "") if part).strip(),
            "q_track": track.title or "",
            "q_artist": artist,
            "q_album": track.album or "",
            "app_id": MUSIXMATCH_APP_ID,
            "usertoken": self._get_user_token(cancel_event=cancel_event),
            "quorum_factor": "1.0",
        }
        payload = self._request_json("macro.search", params, cancel_event=cancel_event)
        return self._parse_search_tracks(payload)

    def _parse_search_tracks(self, payload: dict[str, object]) -> list[MusixmatchTrack]:

        body = _message_body(payload)
        result_list = body.get("track_list")
        if result_list is None:
            result_list = body.get("macro_result_list", {}).get("track_list", [])
        if not isinstance(result_list, list):
            raise MusixmatchError("Musixmatch search response did not contain track results.", kind=ProviderErrorKind.INVALID_RESPONSE)
        tracks: list[MusixmatchTrack] = []
        for item in result_list:
            if not isinstance(item, dict):
                continue
            raw_track = item.get("track", item)
            if not isinstance(raw_track, dict):
                continue
            parsed = _parse_track(raw_track)
            if parsed is not None:
                tracks.append(parsed)
        return tracks

    def _search_website(
        self,
        track: TrackLookupContext,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[MusixmatchTrack]:
        artist = next(iter(track.artists), "")
        title = (track.title or "").strip()
        if not artist or not title:
            return []
        path = f"/lyrics/{_slug_component(artist)}/{_slug_component(title)}"
        response = self._request_page(path, cancel_event=cancel_event, allow_not_found=True)
        if response is None:
            return []
        page = _parse_website_page(response)
        if page is None:
            return []
        remote_track, lyrics = page
        if lyrics is not None:
            self._website_lyrics[remote_track.provider_track_id] = lyrics
        return [remote_track]

    def get_lyrics(
        self,
        remote_track: MusixmatchTrack,
        *,
        cancel_event: threading.Event | None = None,
    ) -> MusixmatchLyrics | None:
        self._check_cancelled(cancel_event)
        website_lyrics = self._website_lyrics.get(remote_track.provider_track_id)
        if website_lyrics is not None:
            return website_lyrics
        common_params: dict[str, object] = {"track_id": remote_track.provider_track_id}
        if self.mode == "official":
            common_params["apikey"] = self.api_key
            subtitle_payload = self._request_json(
                "track.subtitle.get",
                {**common_params, "subtitle_format": "lrc"},
                cancel_event=cancel_event,
                allow_not_found=True,
            )
            self._check_cancelled(cancel_event)
            lyrics_payload = self._request_json(
                "track.lyrics.get",
                common_params,
                cancel_event=cancel_event,
                allow_not_found=True,
            )
        else:
            token = self._get_user_token(cancel_event=cancel_event)
            common_params.update({"app_id": MUSIXMATCH_APP_ID, "usertoken": token})
            subtitle_payload = self._request_json(
                "track.subtitle.get",
                {**common_params, "subtitle_format": "lrc"},
                cancel_event=cancel_event,
                allow_not_found=True,
            )
            self._check_cancelled(cancel_event)
            lyrics_payload = self._request_json(
                "track.lyrics.get",
                common_params,
                cancel_event=cancel_event,
                allow_not_found=True,
            )

        subtitle = _nested_body(_message_body(subtitle_payload), "subtitle")
        lyrics = _nested_body(_message_body(lyrics_payload), "lyrics")
        synced = _clean_synced_lyrics(
            _first_string(subtitle, "subtitle_body", "richsync_body")
            if isinstance(subtitle, dict)
            else None
        )
        plain = _clean_plain_lyrics(_first_string(lyrics, "lyrics_body") if isinstance(lyrics, dict) else None)
        instrumental = bool(
            remote_track.instrumental
            or (isinstance(lyrics, dict) and _coerce_bool(lyrics.get("instrumental")))
        )
        if not synced and not plain:
            return None
        return MusixmatchLyrics(plain_lyrics=plain, synced_lyrics=synced, instrumental=instrumental)

    def _get_user_token(self, *, cancel_event: threading.Event | None = None) -> str:
        with self._token_lock:
            if self._token:
                return self._token
            self._check_cancelled(cancel_event)
            payload = self._request_json(
                "token.get",
                {"app_id": MUSIXMATCH_APP_ID, "user_language": "en"},
                cancel_event=cancel_event,
            )
            token = _message_body(payload).get("user_token")
            if not isinstance(token, str) or not token.strip():
                raise MusixmatchError("Musixmatch did not return a user token.", kind=ProviderErrorKind.AUTH_REQUIRED)
            self._token = token.strip()
            return self._token

    def _request_json(
        self,
        method: str,
        params: dict[str, object],
        *,
        cancel_event: threading.Event | None,
        allow_not_found: bool = False,
    ) -> dict[str, object]:
        self._check_cancelled(cancel_event)
        try:
            response = self.session.get(
                urljoin(self.base_url, method),
                params=params,
                timeout=(5.0, 20.0),
                cookies={"AWSELB": "0", "AWSELBCORS": "0"} if self.mode == "desktop" else None,
            )
        except requests.exceptions.Timeout as exc:
            raise MusixmatchError("Musixmatch request timed out.", kind=ProviderErrorKind.TEMPORARY) from exc
        except requests.exceptions.RequestException as exc:
            raise MusixmatchError(f"Musixmatch request failed: {exc}", kind=ProviderErrorKind.TEMPORARY) from exc
        self._check_cancelled(cancel_event)
        if response.status_code >= 400:
            if allow_not_found and response.status_code == 404:
                return {"message": {"body": {}}}
            raise MusixmatchError(
                f"Musixmatch request failed with HTTP {response.status_code}.",
                status_code=int(response.status_code),
                retry_after_s=_retry_after_seconds(response),
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise MusixmatchError("Musixmatch returned invalid JSON.", kind=ProviderErrorKind.INVALID_RESPONSE) from exc
        if not isinstance(payload, dict):
            raise MusixmatchError("Musixmatch returned an invalid response object.", kind=ProviderErrorKind.INVALID_RESPONSE)
        header = payload.get("message", {}).get("header", {})
        status_code = header.get("status_code") if isinstance(header, dict) else None
        if status_code is not None and int(status_code) != 200:
            if allow_not_found and int(status_code) == 404:
                return {"message": {"body": {}}}
            raise MusixmatchError(
                str(header.get("hint") or f"Musixmatch returned status {status_code}"),
                status_code=int(status_code),
                retry_after_s=_retry_after_seconds(response),
            )
        return payload

    def _request_page(
        self,
        path: str,
        *,
        cancel_event: threading.Event | None,
        allow_not_found: bool = False,
    ) -> str | None:
        self._check_cancelled(cancel_event)
        try:
            response = self.session.get(
                urljoin(MUSIXMATCH_WEBSITE_BASE_URL, path),
                timeout=(5.0, 20.0),
                headers={"Accept": "text/html,application/xhtml+xml"},
            )
        except requests.exceptions.Timeout as exc:
            raise MusixmatchError("Musixmatch website request timed out.", kind=ProviderErrorKind.TEMPORARY) from exc
        except requests.exceptions.RequestException as exc:
            raise MusixmatchError(f"Musixmatch website request failed: {exc}", kind=ProviderErrorKind.TEMPORARY) from exc
        self._check_cancelled(cancel_event)
        if response.status_code == 404 and allow_not_found:
            return None
        if response.status_code >= 400:
            raise MusixmatchError(
                f"Musixmatch website request failed with HTTP {response.status_code}.",
                status_code=int(response.status_code),
                retry_after_s=_retry_after_seconds(response),
            )
        body = getattr(response, "text", None)
        if not isinstance(body, str):
            raise MusixmatchError("Musixmatch website returned no HTML body.", kind=ProviderErrorKind.INVALID_RESPONSE)
        return body

    def _default_base_url(self) -> str:
        return MUSIXMATCH_OFFICIAL_BASE_URL if self.mode == "official" else MUSIXMATCH_DESKTOP_BASE_URL

    @staticmethod
    def _check_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise MusixmatchError("Musixmatch lookup cancelled.", kind=ProviderErrorKind.CANCELLED)


class MusixmatchProvider:
    provider_id = MUSIXMATCH_PROVIDER_ID
    display_name = "Musixmatch"

    def __init__(
        self,
        client: MusixmatchClient,
        *,
        notify=None,
    ) -> None:
        self._client = client
        self._notify = notify or (lambda _message: None)

    def capabilities(self) -> LyricsProviderCapabilities:
        return LyricsProviderCapabilities(
            plain=True,
            synced=True,
            search=True,
            isrc_lookup=False,
            authentication_required=self._client.mode == "official",
        )

    def lookup(
        self,
        track: TrackLookupContext,
        *,
        requested_mode: DownloadMode,
        cancel_event: threading.Event | None = None,
    ) -> LyricsProviderResult | None:
        del requested_mode
        started_at = time.perf_counter()
        self._check_cancelled(cancel_event)
        candidates = self._client.search(track, cancel_event=cancel_event)
        ranked = []
        for candidate in candidates:
            score = score_track_match(
                track,
                TrackMatchMetadata(
                    title=candidate.title,
                    artists=(candidate.artist,) if candidate.artist else (),
                    album=candidate.album,
                    duration_seconds=candidate.duration_seconds,
                    isrc=candidate.isrc,
                    instrumental=candidate.instrumental,
                ),
            )
            if score.quality is not MatchQuality.REJECT:
                ranked.append((score, candidate))
        ranked.sort(key=lambda item: (-item[0].score, item[1].provider_track_id))
        if not ranked:
            self._log(track, "search", 0, None, None, "no_match", started_at)
            return None

        selected_score, selected = ranked[0]
        self._notify(f"Fetching Musixmatch lyrics for {track.title or track.file_path}...")
        lyrics = self._client.get_lyrics(selected, cancel_event=cancel_event)
        if lyrics is None:
            self._log(track, "search", len(ranked), selected.provider_track_id, selected_score.score, "no_lyrics", started_at)
            return None
        diagnostics = build_lookup_diagnostics(
            provider=self.provider_id,
            track_id=track.track_id,
            lookup_method=selected_score.method,
            isrc_lookup="not_supported",
            candidate_count=len(candidates),
            selected_remote_id=selected.provider_track_id,
            score=selected_score.score,
            reason="match",
            result_type=lyrics_result_type(lyrics.plain_lyrics, lyrics.synced_lyrics),
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        )
        diagnostics.update(
            {
                "remote_share_url": selected.share_url,
                "transport": self._client.mode,
            }
        )
        log_lookup_diagnostics(logger, diagnostics)
        return LyricsProviderResult(
            provider=self.provider_id,
            provider_track_id=selected.provider_track_id,
            plain_lyrics=lyrics.plain_lyrics,
            synced_lyrics=lyrics.synced_lyrics,
            instrumental=lyrics.instrumental,
            match_score=float(selected_score.score),
            match_method=selected_score.method,
            remote_title=selected.title,
            remote_artist=selected.artist,
            remote_album=selected.album,
            remote_duration_seconds=selected.duration_seconds,
            remote_isrc=selected.isrc,
            diagnostics=diagnostics,
        )

    def _log(
        self,
        track: TrackLookupContext,
        method: str,
        candidates: int,
        remote_id: str | None,
        score: float | None,
        reason: str,
        started_at: float,
    ) -> None:
        log_lookup_diagnostics(
            logger,
            build_lookup_diagnostics(
                provider=self.provider_id,
                track_id=track.track_id,
                lookup_method=method,
                isrc_lookup="not_supported",
                candidate_count=candidates,
                selected_remote_id=remote_id,
                score=score,
                reason=reason,
                result_type="no_match",
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
            ),
        )

    @staticmethod
    def _check_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise MusixmatchError("Musixmatch lookup cancelled.", kind=ProviderErrorKind.CANCELLED)


def _message_body(payload: dict[str, object]) -> dict[str, object]:
    message = payload.get("message")
    body = message.get("body") if isinstance(message, dict) else None
    return body if isinstance(body, dict) else {}


def _slug_component(value: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", str(value or ""), flags=re.UNICODE)
    cleaned = re.sub(r"[\s_]+", "-", cleaned.strip())
    cleaned = re.sub(r"-+", "-", cleaned)
    return quote(cleaned, safe="-")


def _parse_website_page(html: str) -> tuple[MusixmatchTrack, MusixmatchLyrics | None] | None:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if match is None:
        return None
    try:
        payload = json.loads(unescape(match.group(1)))
    except (TypeError, ValueError):
        return None
    try:
        page_data = payload["props"]["pageProps"]["data"]["trackInfo"]["data"]
        raw_track = page_data["track"]
    except (KeyError, TypeError):
        return None
    if not isinstance(raw_track, dict):
        return None
    parsed_track = MusixmatchTrack(
        provider_track_id=str(raw_track.get("id") or raw_track.get("commonTrackId") or "").strip(),
        title=_optional_string(raw_track.get("name")),
        artist=_optional_string(raw_track.get("artistName")),
        album=_optional_string(raw_track.get("albumName")),
        duration_seconds=_as_float(raw_track.get("duration", raw_track.get("trackLength"))),
        isrc=_optional_string(raw_track.get("isrc")),
        instrumental=_coerce_bool(raw_track.get("isInstrumental")),
        has_lyrics=_coerce_bool(raw_track.get("hasLyrics")),
        has_subtitles=_coerce_bool(raw_track.get("hasSync")),
        share_url=None,
    )
    if not parsed_track.provider_track_id:
        return None
    raw_lyrics = page_data.get("lyrics")
    lyrics_body = raw_lyrics.get("body") if isinstance(raw_lyrics, dict) else None
    lyrics = MusixmatchLyrics(
        plain_lyrics=_clean_plain_lyrics(lyrics_body if isinstance(lyrics_body, str) else None),
        synced_lyrics=None,
        instrumental=parsed_track.instrumental,
    )
    if not lyrics.plain_lyrics:
        lyrics = None
    return parsed_track, lyrics


def _nested_body(body: dict[str, object], key: str) -> object:
    value = body.get(key)
    return value if isinstance(value, dict) else {}


def _parse_track(raw: dict[str, object]) -> MusixmatchTrack | None:
    provider_track_id = str(raw.get("track_id") or raw.get("id") or "").strip()
    if not provider_track_id:
        return None
    duration = raw.get("track_length", raw.get("duration"))
    try:
        duration_seconds = float(duration) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration_seconds = None
    return MusixmatchTrack(
        provider_track_id=provider_track_id,
        title=_optional_string(raw.get("track_name", raw.get("title"))),
        artist=_optional_string(raw.get("artist_name", raw.get("artist"))),
        album=_optional_string(raw.get("album_name", raw.get("album"))),
        duration_seconds=duration_seconds,
        isrc=_optional_string(raw.get("track_isrc", raw.get("isrc"))),
        instrumental=_coerce_bool(raw.get("instrumental")),
        has_lyrics=_coerce_bool(raw.get("has_lyrics")),
        has_subtitles=_coerce_bool(raw.get("has_subtitles")),
        share_url=_optional_string(raw.get("track_share_url", raw.get("share_url"))),
    )


def _first_string(value: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _clean_plain_lyrics(value: str | None) -> str | None:
    if not value:
        return None
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    lines = [line for line in lines if not line.strip().startswith("******* This Lyrics is NOT")]
    cleaned = "\n".join(lines).strip()
    return cleaned or None


def _clean_synced_lyrics(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.startswith("[") and _TIMESTAMP_RE.search(candidate):
        return candidate
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, list):
        return None
    lines: list[str] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        text = str(item.get("x") or item.get("text") or "").strip()
        timestamp = item.get("ts", item.get("time"))
        try:
            seconds = float(timestamp)
        except (TypeError, ValueError):
            continue
        minutes = int(seconds // 60)
        remainder = seconds - minutes * 60
        lines.append(f"[{minutes:02d}:{remainder:05.2f}]{text}".rstrip())
    result = "\n".join(lines).strip()
    return result if any(_TIMESTAMP_RE.search(line) for line in lines) else None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _as_float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _retry_after_seconds(response: Any) -> float | None:
    try:
        value = response.headers.get("Retry-After")
        return max(0.0, float(value)) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _error_kind_for_status(status_code: int | None) -> ProviderErrorKind:
    if status_code == 401:
        return ProviderErrorKind.AUTH_EXPIRED
    if status_code == 403:
        return ProviderErrorKind.AUTH_REQUIRED
    if status_code == 404:
        return ProviderErrorKind.NOT_FOUND
    if status_code == 429:
        return ProviderErrorKind.RATE_LIMITED
    if status_code is not None and status_code >= 500:
        return ProviderErrorKind.TEMPORARY
    return ProviderErrorKind.TEMPORARY
