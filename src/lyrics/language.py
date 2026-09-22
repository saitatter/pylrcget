"""Conservative language detection for lyrics matching."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from math import ceil

from langdetect import DetectorFactory, LangDetectException, detect_langs

DetectorFactory.seed = 0

_TIMESTAMP_RE = re.compile(r"\[(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
_METADATA_TAG_RE = re.compile(r"^\s*\[[a-z]{2,8}:.*?\]\s*$", re.IGNORECASE)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_INSTRUMENTAL_MARKERS = {"instrumental", "[au: instrumental]", "[instrumental]"}
_MIN_CONFIDENCE = 0.80
_MIN_LETTERS = 80
_MIN_WORDS = 12
_MIN_CJK_LETTERS = 40
_MAX_DETECTION_CHARS = 2500


@dataclass(frozen=True, slots=True)
class LyricsLanguageDetection:
    language: str
    confidence: float


def detect_lyrics_language(
    plain_lyrics: str | None,
    synced_lyrics: str | None = None,
) -> LyricsLanguageDetection | None:
    """Detect a language only when there is enough stable lyric text.

    Plain and synced fields are checked independently to avoid counting the
    same lyrics twice. If they disagree, the result is treated as ambiguous.
    """
    detections = [
        detection
        for value in (plain_lyrics, synced_lyrics)
        if (detection := _detect_single_text(value)) is not None
    ]
    if not detections:
        return None
    languages = {detection.language for detection in detections}
    if len(languages) != 1:
        return None
    return max(detections, key=lambda detection: detection.confidence)


def infer_album_language(lyrics_samples: Iterable[str]) -> str | None:
    """Return an album language only with multi-track majority evidence."""
    detected = [
        detection.language
        for text in lyrics_samples
        if (detection := detect_lyrics_language(text)) is not None
    ]
    if len(detected) < 2:
        return None
    counts = Counter(detected)
    language, votes = counts.most_common(1)[0]
    required_votes = max(2, ceil(len(detected) * (2 / 3)))
    return language if votes >= required_votes else None


def infer_track_language(
    plain_lyrics: str | None,
    synced_lyrics: str | None,
    album_samples: Iterable[tuple[int, str]] = (),
    *,
    track_id: int | None = None,
) -> str | None:
    """Prefer this track's lyrics, otherwise use a strong album consensus."""
    detection = detect_lyrics_language(plain_lyrics, synced_lyrics)
    if detection is not None:
        return detection.language
    return infer_album_language(
        lyrics
        for sample_track_id, lyrics in album_samples
        if track_id is None or int(sample_track_id) != int(track_id)
    )


def _detect_single_text(value: str | None) -> LyricsLanguageDetection | None:
    text = _prepare_text(value)
    return _detect_prepared_text(text) if text else None


@lru_cache(maxsize=2048)
def _detect_prepared_text(text: str) -> LyricsLanguageDetection | None:
    text = text[:_MAX_DETECTION_CHARS]
    if not text:
        return None
    letters = sum(character.isalpha() for character in text)
    words = _WORD_RE.findall(text)
    has_cjk = any(_is_cjk(character) for character in text)
    if letters < (_MIN_CJK_LETTERS if has_cjk else _MIN_LETTERS):
        return None
    if not has_cjk and len(words) < _MIN_WORDS:
        return None
    try:
        results = detect_langs(text)
    except LangDetectException:
        return None
    if not results or results[0].prob < _MIN_CONFIDENCE:
        return None
    return LyricsLanguageDetection(results[0].lang.casefold(), float(results[0].prob))


def _prepare_text(value: str | None) -> str:
    text = str(value or "")
    text = _TIMESTAMP_RE.sub(" ", text)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _METADATA_TAG_RE.match(stripped):
            continue
        if stripped.casefold() in _INSTRUMENTAL_MARKERS:
            continue
        lines.append(stripped)
    return " ".join(lines)


def _is_cjk(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3040 <= codepoint <= 0x30FF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


__all__ = [
    "LyricsLanguageDetection",
    "detect_lyrics_language",
    "infer_album_language",
    "infer_track_language",
]
