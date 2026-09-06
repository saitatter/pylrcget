"""Small, dependency-free language hints for known lyric text."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class LanguageDetection:
    language: str | None
    confidence: float
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "confidence": self.confidence,
            "source": self.source,
        }


_WORD_RE = re.compile(r"[\wÀ-ž']+", re.UNICODE)
_LATIN_LANGUAGES = {
    "en": {
        "a", "about", "all", "am", "an", "and", "are", "as", "at", "be", "been", "but",
        "by", "can", "come", "do", "for", "from", "get", "go", "have", "he", "her", "here",
        "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "just", "know",
        "let", "like", "me", "my", "no", "not", "now", "of", "oh", "on", "one", "only", "or",
        "our", "out", "over", "say", "see", "she", "so", "some", "that", "the", "their", "them",
        "there", "these", "they", "this", "to", "up", "us", "was", "we", "were", "what", "when",
        "where", "who", "will", "with", "you", "your",
    },
    "ro": {
        "a", "ai", "am", "are", "ce", "cu", "că", "din", "doar", "este", "în", "la", "mai",
        "mă", "nu", "o", "pe", "pentru", "să", "și", "sunt", "te", "un", "una", "unde", "voi",
    },
    "fr": {
        "au", "aux", "avec", "ce", "dans", "de", "des", "du", "elle", "en", "est", "et", "je",
        "la", "le", "les", "mais", "me", "ne", "nous", "pas", "pour", "que", "qui", "se", "sur",
        "toi", "tu", "un", "une", "vous",
    },
    "de": {
        "aber", "auch", "auf", "aus", "bei", "das", "dass", "der", "die", "ein", "eine", "es",
        "für", "ich", "im", "in", "ist", "mit", "nicht", "nur", "oder", "sie", "und", "von", "was",
        "wir", "zu",
    },
    "es": {
        "a", "al", "como", "con", "de", "del", "el", "ella", "en", "es", "esta", "que", "la",
        "las", "los", "me", "no", "nos", "para", "pero", "por", "se", "si", "sin", "soy", "su",
        "te", "tu", "un", "una", "y",
    },
    "it": {
        "a", "ad", "al", "anche", "che", "chi", "con", "da", "dei", "del", "di", "e", "è", "gli",
        "ha", "il", "in", "io", "la", "le", "lo", "ma", "mi", "nei", "non", "per", "se", "sono",
        "su", "te", "ti", "tra", "tu", "un", "una",
    },
}
_STRONG_MARKERS = {
    "ro": {"ă", "â", "î", "ș", "ţ", "ț"},
    "fr": {"à", "â", "ç", "é", "è", "ê", "ë", "î", "ï", "ù", "û", "ü", "œ"},
    "de": {"ä", "ö", "ü", "ß"},
    "es": {"¿", "¡", "ñ"},
    "it": {"ì", "ò", "à"},
}


def detect_text_language(text: str) -> LanguageDetection:
    """Return a high-confidence hint only when text evidence is sufficient.

    This intentionally refuses to identify romanized non-Latin lyrics from
    text alone.  The acoustic Whisper path remains authoritative for those
    cases and for mixed-language lyrics.
    """
    value = str(text or "").strip()
    if not value:
        return LanguageDetection(None, 0.0, "text")
    if any(_is_cjk(character) for character in value):
        return LanguageDetection("ja", 0.99, "text-script")
    if any("CYRILLIC" in unicodedata.name(character, "") for character in value):
        return LanguageDetection(None, 0.0, "text-ambiguous-script")

    words = [word.casefold() for word in _WORD_RE.findall(value)]
    if len(words) < 3:
        return LanguageDetection(None, 0.0, "text-low-confidence")
    word_set = set(words)
    scores: dict[str, float] = {}
    for language, vocabulary in _LATIN_LANGUAGES.items():
        overlap = len(word_set & vocabulary)
        scores[language] = overlap / max(1, len(word_set))
        marker_count = sum(value.casefold().count(marker) for marker in _STRONG_MARKERS.get(language, set()))
        scores[language] += min(0.35, marker_count * 0.08)

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_language, best_score = ordered[0]
    second_score = ordered[1][1]
    margin = best_score - second_score
    confidence = min(0.99, 0.55 + best_score * 1.25 + max(0.0, margin) * 0.75)
    if best_score < 0.18 or margin < 0.05 or confidence < 0.74:
        return LanguageDetection(None, confidence, "text-low-confidence")
    return LanguageDetection(best_language, confidence, "text")


def _is_cjk(character: str) -> bool:
    name = unicodedata.name(character, "")
    return any(marker in name for marker in ("CJK", "HIRAGANA", "KATAKANA"))


__all__ = ["LanguageDetection", "detect_text_language"]
