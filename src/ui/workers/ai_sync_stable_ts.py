"""Research-only stable-ts adapter for known-text alignment.

stable-ts is intentionally not a production dependency or router default.
This module keeps its import lazy so the application runtime remains usable
without the isolated research environment.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ai_sync_contracts import AlignmentRequest, AlignmentResult, AlignedLine

_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


@dataclass(slots=True, frozen=True)
class _TimedWord:
    text: str
    start: float
    end: float | None


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _word_tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _WORD_RE.finditer(str(text or ""))]


def _timed_words(result: object) -> list[_TimedWord]:
    segments = _field(result, "segments", ())
    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)):
        return []
    output: list[_TimedWord] = []
    for segment in segments:
        words = _field(segment, "words", ())
        if not isinstance(words, Sequence) or isinstance(words, (str, bytes)):
            continue
        for word in words:
            text = str(_field(word, "word", _field(word, "text", "")) or "").strip()
            start = _field(word, "start")
            if not text or not isinstance(start, (int, float)):
                continue
            end = _field(word, "end")
            output.append(
                _TimedWord(
                    text=text,
                    start=max(0.0, float(start)),
                    end=float(end) if isinstance(end, (int, float)) else None,
                )
            )
    return output


def _stable_ts_language(request: AlignmentRequest) -> str | None:
    language = request.requested_language
    if language:
        normalized = str(language).strip().casefold()
        return normalized or None
    configured = request.options.extras.get("stable_ts_language")
    if configured:
        normalized = str(configured).strip().casefold()
        return normalized or None
    return None


def _build_lines(
    lyrics: str,
    words: Sequence[_TimedWord],
    *,
    backend: str,
) -> tuple[list[AlignedLine], float]:
    expected_lines = [line.strip() for line in str(lyrics or "").splitlines() if _word_tokens(line)]
    if not expected_lines or not words:
        return [], 0.0

    lines: list[AlignedLine] = []
    cursor = 0
    matched_lines = 0
    for source_index, text in enumerate(str(lyrics or "").splitlines()):
        expected = _word_tokens(text)
        if not expected:
            continue
        matched: list[_TimedWord] = []
        search_cursor = cursor
        for token in expected:
            found = None
            for position in range(search_cursor, len(words)):
                if _word_tokens(words[position].text) == [token]:
                    found = position
                    break
            if found is None:
                matched = []
                break
            matched.append(words[found])
            search_cursor = found + 1
        if not matched:
            continue
        cursor = search_cursor
        start = matched[0].start
        end = matched[-1].end
        if end is not None and end < start:
            end = start
        if lines and start <= lines[-1].start:
            continue
        lines.append(
            AlignedLine(
                source_line_index=source_index,
                text=text.strip(),
                start=start,
                end=end,
                confidence=1.0,
                backend=backend,
                evidence={"word_count": len(matched)},
            )
        )
        matched_lines += 1
    return lines, matched_lines / len(expected_lines)


class StableTsResearchBackend:
    """Thin adapter around stable-ts, never selected by the production router."""

    name = "stable-ts-research"

    def __init__(
        self,
        model: object,
        *,
        align_function: Callable[..., object],
        align_words_function: Callable[..., object] | None = None,
        model_name: str = "unknown",
        device: str = "cpu",
    ) -> None:
        self.model = model
        self._align_function = align_function
        self._align_words_function = align_words_function
        self.model_name = str(model_name)
        self.device = str(device or "cpu")

    @classmethod
    def load(
        cls,
        model_name: str = "tiny.en",
        *,
        device: str = "cpu",
        download_root: Path | None = None,
    ) -> "StableTsResearchBackend":
        try:
            import stable_whisper
            from stable_whisper.alignment import align, align_words
        except ImportError as exc:
            raise RuntimeError(
                "stable-ts research backend requires the isolated stable-ts runtime."
            ) from exc
        kwargs: dict[str, object] = {"device": device}
        if download_root is not None:
            kwargs["download_root"] = str(download_root)
        model = stable_whisper.load_model(model_name, **kwargs)
        return cls(
            model,
            align_function=align,
            align_words_function=align_words,
            model_name=model_name,
            device=device,
        )

    def supports_language(self, language: str) -> bool:
        return bool(str(language or "").strip())

    def align(self, request: AlignmentRequest) -> AlignmentResult:
        started = time.perf_counter()
        mode = str(request.options.extras.get("stable_ts_mode", "full")).casefold()
        language = _stable_ts_language(request)
        if mode == "local":
            if self._align_words_function is None:
                raise RuntimeError("stable-ts local alignment API is unavailable.")
            segments = request.options.extras.get("stable_ts_segments")
            if not isinstance(segments, list):
                raise ValueError("stable-ts local mode requires stable_ts_segments.")
            aligned = self._align_words_function(
                self.model,
                request.audio_path,
                segments,
                language=language,
            )
        elif mode == "full":
            aligned = self._align_function(
                self.model,
                request.audio_path,
                request.plain_lyrics,
                language=language,
            )
        else:
            raise ValueError(f"Unsupported stable-ts research mode: {mode!r}.")

        timed_words = _timed_words(aligned)
        lines, coverage = _build_lines(
            request.plain_lyrics,
            timed_words,
            backend=self.name,
        )
        return AlignmentResult(
            lines=lines,
            language=language or "unknown",
            backend=self.name,
            coverage=coverage,
            confidence=coverage,
            structural_score=coverage,
            runtime_ms=(time.perf_counter() - started) * 1000,
            diagnostics={
                "research_only": True,
                "stable_ts_mode": mode,
                "stable_ts_model": self.model_name,
                "timed_words": len(timed_words),
            },
        )


__all__ = ["StableTsResearchBackend"]
