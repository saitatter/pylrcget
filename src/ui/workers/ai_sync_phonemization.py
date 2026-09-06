"""Language-aware phonemization contracts and bounded word caching."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(slots=True, frozen=True)
class PhonemizedText:
    language: str
    text: str
    words: tuple[str, ...]
    phonemes: tuple[str, ...]
    phonemizer_version: str


class Phonemizer(Protocol):
    version: str

    def supports_language(self, language: str) -> bool:
        ...

    def phonemize(self, text: str, language: str) -> PhonemizedText:
        ...


class EnglishG2PPhonemizer:
    """Lazy g2p-en adapter with a normalized word cache."""

    version = "g2p-en-arpabet-v1"
    _WORD_RE = re.compile(r"'?[a-z]+(?:'[a-z]*)?")

    def __init__(
        self,
        *,
        g2p_factory: Callable[[], Any] | None = None,
        max_words: int = 8192,
    ) -> None:
        self._g2p_factory = g2p_factory
        self._g2p: Any | None = None
        self._cache: dict[str, str | None] = {}
        self._cache_order: list[str] = []
        self._max_words = max(1, int(max_words))
        self._lock = threading.Lock()

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    def supports_language(self, language: str) -> bool:
        return str(language or "").strip().lower() == "en"

    def phonemize_word(self, word: str) -> str:
        normalized = _normalize_word(word)
        with self._lock:
            if normalized in self._cache:
                value = self._cache[normalized]
                if value is None:
                    raise ValueError(f"Could not phonemize English word {normalized!r}.")
                return value
        self.warm()
        phonemes = [
            token.rstrip("012")
            for token in self._g2p(normalized.strip("'"))
            if re.fullmatch(r"[A-Z]+[012]?", token)
        ]
        value = " ".join(phonemes) or None
        with self._lock:
            self._cache[normalized] = value
            if normalized in self._cache_order:
                self._cache_order.remove(normalized)
            self._cache_order.append(normalized)
            while len(self._cache_order) > self._max_words:
                oldest = self._cache_order.pop(0)
                self._cache.pop(oldest, None)
        if value is None:
            raise ValueError(f"Could not phonemize English word {normalized!r}.")
        return value

    def warm(self) -> None:
        if self._g2p is None:
            self._g2p = self._build_g2p()

    def phonemize(self, text: str, language: str) -> PhonemizedText:
        if not self.supports_language(language):
            raise ValueError("English G2P only supports language 'en'.")
        words = tuple(self._WORD_RE.findall(str(text or "").lower().replace("’", "'")))
        phonemes = tuple(
            token
            for word in words
            for token in (*self.phonemize_word(word).split(), ">")
        )
        return PhonemizedText(
            language="en",
            text=str(text or ""),
            words=words,
            phonemes=(">", *phonemes),
            phonemizer_version=self.version,
        )

    def _build_g2p(self) -> Any:
        if self._g2p_factory is not None:
            return self._g2p_factory()
        try:
            import g2p_en
        except ImportError as exc:
            raise RuntimeError("English lyrics alignment requires the optional g2p-en package.") from exc
        return g2p_en.G2p()


def _normalize_word(word: str) -> str:
    return str(word or "").strip().lower().replace("’", "'")


__all__ = ["EnglishG2PPhonemizer", "PhonemizedText", "Phonemizer"]
