from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

from .contracts import LyricsProviderResult, TrackLookupContext

_ISRC_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}")
_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


class MatchQuality(str, Enum):
    EXACT_ID = "EXACT_ID"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class TrackMatchMetadata:
    """Provider-neutral metadata describing a remote catalogue track."""

    title: str | None = None
    artists: tuple[str, ...] = ()
    album: str | None = None
    album_artist: str | None = None
    duration_seconds: float | None = None
    track_number: int | None = None
    isrc: str | None = None
    instrumental: bool = False


@dataclass(frozen=True, slots=True)
class TrackMatchScore:
    score: float
    quality: MatchQuality
    method: str
    diagnostics: dict[str, object] = field(default_factory=dict)


def normalize_isrc(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"\s+", "", str(value).strip().upper()).replace("-", "")
    return compact if _ISRC_RE.fullmatch(compact) else None


def normalize_match_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    words = _WORD_RE.findall(normalized)
    return " ".join(words)


def provider_result_metadata(result: LyricsProviderResult) -> TrackMatchMetadata:
    remote_artist = (result.remote_artist or "").strip()
    return TrackMatchMetadata(
        title=result.remote_title,
        artists=(remote_artist,) if remote_artist else (),
        album=result.remote_album,
        duration_seconds=result.remote_duration_seconds,
        isrc=result.remote_isrc,
        instrumental=result.instrumental,
    )


def score_track_match(local: TrackLookupContext, remote: TrackMatchMetadata) -> TrackMatchScore:
    local_title = normalize_match_text(local.title)
    remote_title = normalize_match_text(remote.title)
    title_similarity = _text_similarity(local_title, remote_title)

    local_artists = tuple(normalize_match_text(value) for value in local.artists if normalize_match_text(value))
    remote_artists = tuple(normalize_match_text(value) for value in remote.artists if normalize_match_text(value))
    artist_similarity = _best_artist_similarity(local_artists, remote_artists)
    primary_artist_exact = bool(local_artists and remote_artists and local_artists[0] in remote_artists)

    local_album = normalize_match_text(local.album)
    remote_album = normalize_match_text(remote.album)
    album_similarity = _text_similarity(local_album, remote_album) if local_album else 0.0

    local_isrc = normalize_isrc(local.isrc)
    remote_isrc = normalize_isrc(remote.isrc)
    isrc_exact = bool(local_isrc and remote_isrc and local_isrc == remote_isrc)
    metadata_plausible = (
        (not local_title or title_similarity >= 0.5)
        and (not local_artists or artist_similarity >= 0.5)
    )

    if isrc_exact and metadata_plausible:
        return TrackMatchScore(
            score=100.0,
            quality=MatchQuality.EXACT_ID,
            method="exact isrc",
            diagnostics={
                "isrc_exact": True,
                "title_similarity": round(title_similarity, 4),
                "artist_similarity": round(artist_similarity, 4),
                "album_similarity": round(album_similarity, 4),
            },
        )

    score = 0.0
    components: dict[str, object] = {
        "isrc_exact": isrc_exact,
        "title_similarity": round(title_similarity, 4),
        "artist_similarity": round(artist_similarity, 4),
        "album_similarity": round(album_similarity, 4),
    }

    title_points = _field_points(title_similarity, exact=35, strong=20, strong_threshold=0.75)
    artist_points = _field_points(artist_similarity, exact=30, strong=15, strong_threshold=0.75)
    if primary_artist_exact:
        artist_points = 30
    elif artist_similarity >= 0.999:
        artist_points = 29
    album_points = _field_points(album_similarity, exact=15, strong=8, strong_threshold=0.75) if local_album else 0
    score += title_points + artist_points + album_points
    components.update(
        title_points=title_points,
        artist_points=artist_points,
        album_points=album_points,
    )

    duration_points = _duration_points(local.duration_seconds, remote.duration_seconds)
    score += duration_points
    components["duration_points"] = duration_points

    track_number_points = 0
    if local.track_number is not None and remote.track_number is not None:
        track_number_points = 3 if int(local.track_number) == int(remote.track_number) else 0
    score += track_number_points
    components["track_number_points"] = track_number_points

    version_penalty = _version_penalty(local.title, remote.title)
    if version_penalty:
        score -= version_penalty
    components["version_penalty"] = version_penalty

    instrumental_penalty = 35 if bool(local.instrumental) != bool(remote.instrumental) else 0
    if instrumental_penalty:
        score -= instrumental_penalty
    components["instrumental_penalty"] = instrumental_penalty

    if isrc_exact:
        score += 10
        components["isrc_conflict"] = True

    score = max(0.0, min(100.0, score))
    quality = _quality_for_score(score)
    method = "metadata" if quality is not MatchQuality.REJECT else "rejected metadata mismatch"
    return TrackMatchScore(score=score, quality=quality, method=method, diagnostics=components)


def _field_points(similarity: float, *, exact: int, strong: int, strong_threshold: float) -> int:
    if similarity >= 0.999:
        return exact
    if similarity >= strong_threshold:
        return round(strong + (exact - strong) * (similarity - strong_threshold) / (1 - strong_threshold))
    if similarity >= 0.5:
        return round(strong * similarity)
    return 0


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _best_artist_similarity(local: tuple[str, ...], remote: tuple[str, ...]) -> float:
    if not local or not remote:
        return 0.0
    return max(_text_similarity(left, right) for left in local for right in remote)


def _duration_points(local: float | None, remote: float | None) -> int:
    if local is None or remote is None or local <= 0 or remote <= 0:
        return 0
    difference = abs(float(local) - float(remote))
    if difference <= 1:
        return 20
    if difference <= 2:
        return 15
    if difference <= 5:
        return 8
    return 0


def _version_flags(value: str | None) -> set[str]:
    words = set(normalize_match_text(value).split())
    flags: set[str] = set()
    if "live" in words:
        flags.add("live")
    if words & {"remaster", "remastered"}:
        flags.add("remaster")
    if "acoustic" in words:
        flags.add("acoustic")
    if "karaoke" in words:
        flags.add("karaoke")
    if "instrumental" in words:
        flags.add("instrumental")
    if "demo" in words:
        flags.add("demo")
    if "radio" in words and "edit" in words:
        flags.add("radio edit")
    return flags


def _version_penalty(local_title: str | None, remote_title: str | None) -> int:
    penalties = {"live": 30, "remaster": 15, "acoustic": 25, "karaoke": 50, "instrumental": 35}
    local_flags = _version_flags(local_title)
    remote_flags = _version_flags(remote_title)
    return sum(penalty for flag, penalty in penalties.items() if (flag in local_flags) != (flag in remote_flags))


def _quality_for_score(score: float) -> MatchQuality:
    if score >= 80:
        return MatchQuality.HIGH
    if score >= 60:
        return MatchQuality.MEDIUM
    if score >= 35:
        return MatchQuality.LOW
    return MatchQuality.REJECT
