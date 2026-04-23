"""Lightweight LRCLIB API client — replaces the lrclibapi package."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _get_app_version() -> str:
    try:
        from ui.services.update_service import current_app_version
        return current_app_version()
    except Exception:
        return "0.0.0"

BASE_URL = "https://lrclib.net/api"
_DEFAULT_TIMEOUT_S = 10.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LrcLibError(Exception):
    """Base error for all LRCLIB API failures."""

    def __init__(self, status_code: int, reason: str, message: str = "") -> None:
        self.status_code = status_code
        self.reason = reason
        self.message = message
        super().__init__(f"{status_code} {reason}" + (f": {message}" if message else ""))


class NotFoundError(LrcLibError):
    pass


class RateLimitError(LrcLibError):
    pass


class ServerError(LrcLibError):
    pass


class IncorrectPublishTokenError(LrcLibError):
    pass


def _raise_for_status(response: requests.Response) -> None:
    if response.ok:
        return
    code = response.status_code
    reason = response.reason or ""
    try:
        body = response.json()
        message = body.get("message", "")
    except Exception:
        message = response.text[:200] if response.text else ""

    if code == 404:
        raise NotFoundError(code, reason, message)
    if code == 429:
        raise RateLimitError(code, reason, message)
    if code == 400:
        raise IncorrectPublishTokenError(code, reason, message)
    if 500 <= code < 600:
        raise ServerError(code, reason, message)
    raise LrcLibError(code, reason, message)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Lyrics:
    id: int
    name: str
    track_name: str
    artist_name: str
    album_name: str
    duration: int
    instrumental: bool
    plain_lyrics: str | None = None
    synced_lyrics: str | None = None
    lang: str | None = None
    isrc: str | None = None
    spotify_id: str | None = None
    release_date: str | None = None


@dataclass(frozen=True)
class SearchResult:
    id: int
    name: str
    track_name: str
    artist_name: str
    album_name: str
    duration: int
    instrumental: bool
    plain_lyrics: str | None = None
    synced_lyrics: str | None = None


def _lyrics_from_dict(d: dict[str, Any]) -> Lyrics:
    return Lyrics(
        id=d.get("id", 0),
        name=d.get("name", ""),
        track_name=d.get("trackName", ""),
        artist_name=d.get("artistName", ""),
        album_name=d.get("albumName", ""),
        duration=d.get("duration", 0),
        instrumental=d.get("instrumental", False),
        plain_lyrics=d.get("plainLyrics"),
        synced_lyrics=d.get("syncedLyrics"),
        lang=d.get("lang"),
        isrc=d.get("isrc"),
        spotify_id=d.get("spotifyId"),
        release_date=d.get("releaseDate"),
    )


def _search_result_from_dict(d: dict[str, Any]) -> SearchResult:
    return SearchResult(
        id=d.get("id", 0),
        name=d.get("name", ""),
        track_name=d.get("trackName", ""),
        artist_name=d.get("artistName", ""),
        album_name=d.get("albumName", ""),
        duration=d.get("duration", 0),
        instrumental=d.get("instrumental", False),
        plain_lyrics=d.get("plainLyrics"),
        synced_lyrics=d.get("syncedLyrics"),
    )


# ---------------------------------------------------------------------------
# Challenge solver
# ---------------------------------------------------------------------------

def _is_nonce_valid(prefix: str, nonce: int, target: bytes) -> bool:
    digest = hashlib.sha256(f"{prefix}{nonce}".encode()).digest()
    return digest < target


def _find_nonce(
    prefix: str,
    target: bytes,
    result: list[int | None],
    start: int,
    step: int,
) -> None:
    nonce = start
    while result[0] is None:
        if _is_nonce_valid(prefix, nonce, target):
            result[0] = nonce
            return
        nonce += step


def solve_challenge(prefix: str, target_hex: str) -> str:
    target = bytes.fromhex(target_hex)
    num_threads = os.cpu_count() or 1
    result: list[int | None] = [None]
    threads = [
        threading.Thread(target=_find_nonce, args=(prefix, target, result, i, num_threads), daemon=True)
        for i in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return str(result[0])


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class LrcLibAPI:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = (base_url or BASE_URL).rstrip("/")
        self._timeout = timeout_s
        self._session = session or requests.Session()
        version = _get_app_version()
        self._session.headers.setdefault(
            "User-Agent",
            f"PyLrcGet v{version} (https://github.com/saitatter/pylrcget)",
        )

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self._timeout)
        url = f"{self._base_url}{endpoint}"
        response = self._session.request(method, url, **kwargs)
        _raise_for_status(response)
        return response

    # --- GET /api/get  &  /api/get-cached ---
    def get_lyrics(
        self,
        track_name: str,
        artist_name: str,
        album_name: str,
        duration: int,
        *,
        cached: bool = False,
    ) -> Lyrics:
        endpoint = "/get-cached" if cached else "/get"
        params: dict[str, Any] = {
            "track_name": track_name,
            "artist_name": artist_name,
            "album_name": album_name,
            "duration": duration,
        }
        response = self._request("GET", endpoint, params=params)
        return _lyrics_from_dict(response.json())

    # --- GET /api/get/{id} ---
    def get_lyrics_by_id(self, lrclib_id: int | str) -> Lyrics:
        response = self._request("GET", f"/get/{lrclib_id}")
        return _lyrics_from_dict(response.json())

    # --- GET /api/search ---
    def search_lyrics(
        self,
        *,
        query: str | None = None,
        track_name: str | None = None,
        artist_name: str | None = None,
        album_name: str | None = None,
    ) -> list[SearchResult]:
        if not query and not track_name:
            raise ValueError("Either query or track_name is required")
        params = {k: v for k, v in {
            "q": query,
            "track_name": track_name,
            "artist_name": artist_name,
            "album_name": album_name,
        }.items() if v is not None}
        try:
            response = self._request("GET", "/search", params=params)
        except NotFoundError:
            return []
        return [_search_result_from_dict(item) for item in response.json()]

    # --- POST /api/request-challenge ---
    def request_challenge(self) -> tuple[str, str]:
        """Returns (prefix, target_hex)."""
        response = self._request("POST", "/request-challenge")
        data = response.json()
        return data["prefix"], data["target"]

    # --- Obtain publish token (challenge + solve) ---
    def obtain_publish_token(self) -> str:
        prefix, target_hex = self.request_challenge()
        nonce = solve_challenge(prefix, target_hex)
        return f"{prefix}:{nonce}"

    # --- POST /api/publish ---
    def publish_lyrics(
        self,
        *,
        track_name: str,
        artist_name: str,
        album_name: str,
        duration: int,
        plain_lyrics: str | None = None,
        synced_lyrics: str | None = None,
        publish_token: str | None = None,
    ) -> None:
        if not publish_token:
            publish_token = self.obtain_publish_token()
        data = {
            "trackName": track_name,
            "artistName": artist_name,
            "albumName": album_name,
            "duration": duration,
            "plainLyrics": plain_lyrics,
            "syncedLyrics": synced_lyrics,
        }
        self._request(
            "POST", "/publish",
            headers={"X-Publish-Token": publish_token},
            json=data,
        )
