from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import requests


@dataclass(frozen=True)
class LyricsResult:
    plain: Optional[str]
    synced: Optional[str]
    instrumental: bool
    source: str  # "get" | "search" | "none"


class LrcLibClient:
    def __init__(self, base_url: str = "https://lrclib.net", user_agent: str = "lrcget-pyside6/0.1"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def get_by_metadata(self, title: str, artist: str, album: str | None, duration_s: float | None) -> Optional[dict]:
        # LRCLIB: GET /api/get?track_name=&artist_name=&album_name=&duration=
        # duration is commonly in seconds in docs/tools; server accepts numeric. :contentReference[oaicite:1]{index=1}
        params = {
            "track_name": title,
            "artist_name": artist,
        }
        if album:
            params["album_name"] = album
        if duration_s and duration_s > 0:
            params["duration"] = int(round(duration_s))

        r = self.session.get(f"{self.base_url}/api/get", params=params, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def search(self, query: str, artist: str | None = None, duration_s: float | None = None, limit: int = 10) -> list[dict]:
        # GET /api/search?query=...&artist_name=...&duration=...&limit=...
        params = {"query": query, "limit": int(limit)}
        if artist:
            params["artist_name"] = artist
        if duration_s and duration_s > 0:
            params["duration"] = int(round(duration_s))
        r = self.session.get(f"{self.base_url}/api/search", params=params, timeout=15)
        r.raise_for_status()
        return r.json() if isinstance(r.json(), list) else []

    def fetch_best(self, title: str, artist: str, album: str | None, duration_s: float | None) -> LyricsResult:
        # 1) Try /api/get (best match by metadata)
        data = self.get_by_metadata(title=title, artist=artist, album=album, duration_s=duration_s)
        if data:
            plain = (data.get("plainLyrics") or "").strip() or None
            synced = (data.get("syncedLyrics") or "").strip() or None
            instrumental = bool(data.get("instrumental", False)) or (synced == "[au: instrumental]")
            return LyricsResult(plain=plain, synced=synced, instrumental=instrumental, source="get")

        # 2) Fallback to /api/search (query = "artist title")
        items = self.search(query=f"{artist} {title}", artist=artist, duration_s=duration_s, limit=10)
        if items:
            best = items[0]
            plain = (best.get("plainLyrics") or "").strip() or None
            synced = (best.get("syncedLyrics") or "").strip() or None
            instrumental = bool(best.get("instrumental", False)) or (synced == "[au: instrumental]")
            return LyricsResult(plain=plain, synced=synced, instrumental=instrumental, source="search")

        return LyricsResult(plain=None, synced=None, instrumental=False, source="none")
