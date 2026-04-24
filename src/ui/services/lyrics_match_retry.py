from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re


_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RetrySearchQuery:
    label: str
    query: str = ""
    artist: str = ""
    title: str = ""
    album: str = ""


@dataclass(frozen=True)
class LyricsMatchCandidate:
    track_id: int
    track_label: str
    query_label: str
    score: int
    artist_name: str
    track_name: str
    album_name: str
    duration: int
    kind: str
    plain_lyrics: str
    synced_lyrics: str


def build_retry_search_queries(*, artist: str, title: str, album: str) -> list[RetrySearchQuery]:
    artist = (artist or "").strip()
    title = (title or "").strip()
    album = (album or "").strip()
    queries: list[RetrySearchQuery] = []

    if title and artist and album:
        queries.append(RetrySearchQuery("artist + title + album", artist=artist, title=title, album=album))
    if title and artist:
        queries.append(RetrySearchQuery("artist + title", artist=artist, title=title))
        queries.append(RetrySearchQuery("free text: artist title", query=f"{artist} {title}"))
    if title:
        queries.append(RetrySearchQuery("title only", title=title))
        queries.append(RetrySearchQuery("free text: title", query=title))

    unique: list[RetrySearchQuery] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in queries:
        key = (item.query.casefold(), item.artist.casefold(), item.title.casefold(), item.album.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def choose_best_candidate(
    *,
    track_id: int,
    track_label: str,
    artist: str,
    title: str,
    album: str,
    query_label: str,
    results: list,
) -> LyricsMatchCandidate | None:
    best: LyricsMatchCandidate | None = None
    for result in results:
        score = _score_result(
            artist=artist,
            title=title,
            album=album,
            result_artist=str(getattr(result, "artist_name", "") or ""),
            result_title=str(getattr(result, "track_name", "") or ""),
            result_album=str(getattr(result, "album_name", "") or ""),
        )
        kind = _result_kind(result)
        if kind not in {"Synced", "Plain"}:
            continue
        if kind == "Synced":
            score += 3
        candidate = LyricsMatchCandidate(
            track_id=int(track_id),
            track_label=track_label,
            query_label=query_label,
            score=min(100, score),
            artist_name=str(getattr(result, "artist_name", "") or ""),
            track_name=str(getattr(result, "track_name", "") or ""),
            album_name=str(getattr(result, "album_name", "") or ""),
            duration=int(getattr(result, "duration", 0) or 0),
            kind=kind,
            plain_lyrics=str(getattr(result, "plain_lyrics", "") or ""),
            synced_lyrics=str(getattr(result, "synced_lyrics", "") or ""),
        )
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def _score_result(
    *,
    artist: str,
    title: str,
    album: str,
    result_artist: str,
    result_title: str,
    result_album: str,
) -> int:
    title_score = _text_similarity(title, result_title)
    artist_score = _text_similarity(artist, result_artist)
    album_score = _text_similarity(album, result_album) if album.strip() else 0.0
    score = (title_score * 0.58) + (artist_score * 0.34) + (album_score * 0.08)
    return int(round(score * 100))


def _text_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_score = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    return max(token_score, sequence_score)


def _normalize_text(value: str) -> str:
    return " ".join(_WORD_RE.findall((value or "").casefold()))


def _result_kind(result) -> str:
    if getattr(result, "synced_lyrics", None):
        return "Synced"
    if getattr(result, "plain_lyrics", None):
        return "Plain"
    if getattr(result, "instrumental", False):
        return "Instrumental"
    return "None"
