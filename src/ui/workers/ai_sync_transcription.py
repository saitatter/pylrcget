"""Audio transcription, deduplication and per-chunk alignment helpers."""
from __future__ import annotations

import logging
import re
from collections import Counter
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def _compat_segment_alignment_quality(
    segments: list[dict],
    plain_lines: list[str],
    duration_s: float,
) -> float:
    import sys

    worker = sys.modules.get("ui.workers.ai_sync_worker")
    if worker is not None:
        candidate = getattr(worker, "_segment_alignment_quality", None)
        if candidate is not None and candidate is not _segment_alignment_quality:
            return candidate(segments, plain_lines, duration_s)
    return _segment_alignment_quality(segments, plain_lines, duration_s)


def _approximate_word_timestamps_from_segments(segments: list[dict]) -> list[dict]:
    """Recover coarse word timings when forced alignment drops part of the ASR tail."""
    recovered: list[dict] = []
    for index, segment in enumerate(segments):
        text_words = str(segment.get("text", "")).split()
        if not text_words:
            continue
        try:
            start = float(segment.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        try:
            end = float(segment.get("end", start))
        except (TypeError, ValueError):
            end = start
        if end <= start:
            next_start = None
            if index + 1 < len(segments):
                try:
                    next_start = float(segments[index + 1].get("start"))
                except (TypeError, ValueError):
                    next_start = None
            end = max(start + 0.25 * len(text_words), next_start or start)
        step = (end - start) / max(1, len(text_words))
        words = [
            {
                "word": word,
                "start": start + step * word_index,
                "end": start + step * (word_index + 1),
            }
            for word_index, word in enumerate(text_words)
        ]
        recovered.append({**segment, "words": words})
    return recovered


def _transcribe_tail_window(
    model_obj: object,
    audio: object,
    *,
    tail_start: float,
    language: str | None,
) -> list[dict]:
    """Transcribe a missed tail without relying on WhisperX's VAD segmentation."""
    model = getattr(model_obj, "model", None)
    transcribe = getattr(model, "transcribe", None)
    if not callable(transcribe):
        return []
    try:
        audio_slice = audio[int(max(0.0, tail_start) * 16000):]
        result, _info = transcribe(audio_slice, language=language, beam_size=5)
    except (RuntimeError, TypeError, ValueError):
        return []

    recovered: list[dict] = []
    for segment in result:
        try:
            start = float(segment.start) + tail_start
            end = float(segment.end) + tail_start
        except (AttributeError, TypeError, ValueError):
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        if text:
            recovered.append({"start": start, "end": end, "text": text})
    return recovered


def _transcribe_fixed_windows(
    model_obj: object,
    audio: object,
    *,
    duration_s: float,
    language: str | None,
    window_s: float = 60.0,
    step_s: float = 45.0,
) -> list[dict]:
    """Transcribe overlapping fixed windows to bypass unreliable music VAD."""
    model = getattr(model_obj, "model", None)
    transcribe = getattr(model, "transcribe", None)
    if not callable(transcribe):
        return []

    raw_segments: list[dict] = []
    start = 0.0
    while start < duration_s:
        end = min(duration_s, start + window_s)
        try:
            audio_slice = audio[int(start * 16000):int(end * 16000)]
            result, _info = transcribe(
                audio_slice,
                language=language,
                beam_size=5,
                condition_on_previous_text=False,
            )
        except (RuntimeError, TypeError, ValueError):
            start += step_s
            continue
        for segment in result:
            try:
                segment_start = float(segment.start) + start
                segment_end = min(float(segment.end) + start, duration_s)
            except (AttributeError, TypeError, ValueError):
                continue
            text = str(getattr(segment, "text", "") or "").strip()
            if text and segment_start < duration_s and segment_end > segment_start:
                raw_segments.append(
                    {"start": segment_start, "end": segment_end, "text": text}
                )
        start += step_s

    raw_segments.sort(key=lambda segment: (segment["start"], segment["end"]))
    return _deduplicate_transcribed_segments(raw_segments, overlap_window_s=step_s)


def _deduplicate_transcribed_segments(
    raw_segments: list[dict],
    *,
    overlap_window_s: float,
) -> list[dict]:
    """Remove near-identical overlapping ASR segments while preserving distinct lines."""
    deduplicated: list[dict] = []
    for segment in raw_segments:
        duplicate = False
        normalized = " ".join(segment["text"].lower().split())
        for previous in reversed(deduplicated):
            if segment["start"] - previous["end"] > overlap_window_s:
                break
            overlap = min(segment["end"], previous["end"]) - max(
                segment["start"], previous["start"]
            )
            if overlap <= 0:
                continue
            previous_text = " ".join(previous["text"].lower().split())
            similarity = SequenceMatcher(None, normalized, previous_text).ratio()
            if similarity >= 0.62:
                duplicate = True
                if segment["end"] - segment["start"] > previous["end"] - previous["start"]:
                    deduplicated[-1] = segment
                break
        if not duplicate:
            deduplicated.append(segment)
    return deduplicated


def _align_segments_per_chunks(
    whisperx_module: object,
    segments: list[dict],
    align_model: object,
    metadata: object,
    audio: object,
    device: str,
    *,
    chunk_s: float = 60.0,
) -> list[dict]:
    """Align fixed-window ASR batches independently to avoid global tail loss."""
    if not segments:
        return []

    batches: dict[int, list[dict]] = {}
    for segment in segments:
        try:
            start = max(0.0, float(segment.get("start", 0.0)))
        except (TypeError, ValueError):
            start = 0.0
        batch_index = int(start // chunk_s)
        batches.setdefault(batch_index, []).append(segment)

    aligned_segments: list[dict] = []
    for batch_index in sorted(batches):
        batch = batches[batch_index]
        try:
            result = whisperx_module.align(batch, align_model, metadata, audio, device)
            aligned_batch = result.get("segments", []) if isinstance(result, dict) else []
        except Exception as exc:
            logger.warning(
                "Per-chunk forced alignment failed for chunk %d; using coarse timings: %s",
                batch_index,
                exc,
            )
            aligned_batch = []
        has_word_timestamps = any(
            bool(segment.get("words"))
            for segment in aligned_batch
            if isinstance(segment, dict)
        )
        if aligned_batch and has_word_timestamps:
            aligned_segments.extend(aligned_batch)
        else:
            aligned_segments.extend(_approximate_word_timestamps_from_segments(batch))

    aligned_segments.sort(
        key=lambda segment: (
            float(segment.get("start", 0.0)),
            float(segment.get("end", segment.get("start", 0.0))),
        )
    )
    return aligned_segments


def _should_use_per_chunk_alignment(
    raw_segments: list[dict],
    globally_aligned_segments: list[dict],
    *,
    min_tail_loss_s: float = 12.0,
) -> bool:
    """Use per-chunk alignment only when global alignment loses meaningful tail."""
    raw_tail = _segment_tail_seconds(raw_segments)
    aligned_tail = _segment_tail_seconds(globally_aligned_segments)
    return raw_tail - aligned_tail >= min_tail_loss_s


def _normalized_transcribe_language(language: str | None) -> str | None:
    code = str(language or "").strip().lower()
    if not code or code == "auto":
        return None
    return code


def _segment_word_starts(segments: list[dict]) -> list[float]:
    starts: list[float] = []
    for seg in segments:
        for w in seg.get("words", []):
            start = w.get("start")
            if start is None:
                continue
            token = str(w.get("word", "")).strip()
            if not token:
                continue
            try:
                starts.append(float(start))
            except (TypeError, ValueError):
                continue
    return starts


def _segment_tail_seconds(segments: list[dict]) -> float:
    word_starts = _segment_word_starts(segments)
    if word_starts:
        return max(word_starts)
    seg_ends: list[float] = []
    for seg in segments:
        end = seg.get("end")
        if end is None:
            continue
        try:
            seg_ends.append(float(end))
        except (TypeError, ValueError):
            continue
    return max(seg_ends) if seg_ends else 0.0


def _segment_reliable_tail_seconds(
    segments: list[dict],
    *,
    neighborhood_s: float = 4.0,
    min_neighbors: int = 2,
) -> float:
    """
    Estimate a robust tail position, ignoring isolated outlier words.

    Some ASR runs produce a single late token near song end while the actual
    lyrical content stopped much earlier. That late outlier can hide poor
    coverage and prevent relaxed-VAD retry.
    """
    starts = sorted(_segment_word_starts(segments))
    if not starts:
        return _segment_tail_seconds(segments)
    if len(starts) <= 3:
        return starts[-1]

    reliable: list[float] = []
    for i, base in enumerate(starts):
        neighbors = 0
        for j, other in enumerate(starts):
            if i == j:
                continue
            if abs(other - base) <= neighborhood_s:
                neighbors += 1
        if neighbors >= min_neighbors:
            reliable.append(base)

    if reliable:
        return max(reliable)
    return starts[-1]


def _should_retry_with_relaxed_vad(
    audio_samples: list[float] | tuple[float, ...] | object,
    segments: list[dict],
    plain_lines: list[str],
    *,
    min_duration_s: float = 120.0,
    min_plain_lines: int = 8,
    min_coverage_ratio: float = 0.83,
    min_tail_gap_s: float = 25.0,
) -> bool:
    """
    Decide when default VAD likely truncated lyrical coverage and a relaxed-VAD
    second pass is worth the extra runtime.
    """
    try:
        duration_s = float(len(audio_samples)) / 16000.0
    except Exception:
        return False
    if duration_s < min_duration_s:
        return False
    non_empty_plain = sum(1 for line in plain_lines if str(line).strip())
    if non_empty_plain < min_plain_lines:
        return False

    tail_s = _segment_tail_seconds(segments)
    if tail_s <= 0.0:
        return True

    reliable_tail_s = _segment_reliable_tail_seconds(segments)
    if reliable_tail_s <= 0.0:
        reliable_tail_s = tail_s

    coverage_ratio = reliable_tail_s / max(duration_s, 1.0)
    tail_gap = duration_s - reliable_tail_s
    return coverage_ratio < min_coverage_ratio and tail_gap >= min_tail_gap_s


def _segment_alignment_quality(
    segments: list[dict],
    plain_lines: list[str],
    duration_s: float,
) -> float:
    """
    Estimate alignment quality without ground truth.

    Quality proxy components:
    - line_match: average best lexical match per line (0..1)
    - vocab_ratio: fraction of ASR words that exist in plain-lyrics vocabulary (0..1)
    - coverage: reliable_tail_seconds / duration_seconds (0..1)
    """
    from .ai_sync_alignment import (
        _build_plain_vocabulary,
        _compute_line_to_words_score,
        _normalize_word,
    )

    words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []):
            token = str(w.get("word", "")).strip()
            if not token or "start" not in w:
                continue
            words.append(w)
    if not words:
        return -1e9

    clean_lines = [str(line).strip() for line in plain_lines if str(line).strip()]
    if not clean_lines:
        return -1e9

    max_candidates = 180
    step = max(1, len(words) // max_candidates)
    candidate_indices = list(range(0, len(words), step))
    if candidate_indices[-1] != len(words) - 1:
        candidate_indices.append(len(words) - 1)

    line_scores: list[float] = []
    for line in clean_lines:
        line_words = line.split()
        if not line_words:
            continue
        best = 0.0
        for idx in candidate_indices:
            score = _compute_line_to_words_score(line_words, words, idx)
            if score > best:
                best = score
        line_scores.append(best)

    line_match = sum(line_scores) / len(line_scores) if line_scores else 0.0
    vocab = _build_plain_vocabulary(plain_lines)
    in_vocab = 0
    for w in words:
        tok = _normalize_word(str(w.get("word", "")).strip())
        if tok and tok in vocab:
            in_vocab += 1
    vocab_ratio = in_vocab / max(1, len(words))
    coverage = _segment_reliable_tail_seconds(segments) / max(duration_s, 1.0)
    return line_match * 2.0 + vocab_ratio * 3.0 + coverage * 0.5


def _should_use_relaxed_vad_result(
    default_segments: list[dict],
    relaxed_segments: list[dict],
    plain_lines: list[str],
    duration_s: float,
    *,
    min_tail_gain_s: float = 12.0,
    min_quality_gain: float = 0.01,
) -> bool:
    """
    Decide whether relaxed-VAD result is better than default VAD result.
    """
    default_tail = _segment_tail_seconds(default_segments)
    relaxed_tail = _segment_tail_seconds(relaxed_segments)
    if relaxed_tail > default_tail + min_tail_gain_s:
        return True

    default_quality = _compat_segment_alignment_quality(default_segments, plain_lines, duration_s)
    relaxed_quality = _compat_segment_alignment_quality(relaxed_segments, plain_lines, duration_s)
    return relaxed_quality > default_quality + min_quality_gain


def _select_best_relaxed_segments(
    default_segments: list[dict],
    relaxed_candidates: list[list[dict]],
    plain_lines: list[str],
    duration_s: float,
) -> list[dict] | None:
    """
    Choose the best relaxed-VAD candidate over the default pass, or None to keep default.
    """
    best_segments = None
    best_quality = None
    for candidate in relaxed_candidates:
        if not _should_use_relaxed_vad_result(default_segments, candidate, plain_lines, duration_s):
            continue
        quality = _compat_segment_alignment_quality(candidate, plain_lines, duration_s)
        if best_quality is None or quality > best_quality:
            best_segments = candidate
            best_quality = quality
    return best_segments


def _should_retry_with_short_windows(
    segments: list[dict],
    *,
    min_segment_duration_s: float = 18.0,
    max_word_density: float = 1.5,
    min_segment_words: int = 12,
) -> bool:
    """Detect a long, low-density ASR segment likely compressing repeated lyrics."""
    for segment in segments:
        try:
            duration_s = float(segment.get("end", 0.0)) - float(segment.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        word_count = sum(
            1
            for word in segment.get("words", [])
            if isinstance(word, dict) and str(word.get("word", "")).strip()
        )
        if (
            duration_s >= min_segment_duration_s
            and word_count >= min_segment_words
            and word_count / max(duration_s, 0.1) <= max_word_density
        ):
            return True
    return False


def _find_targeted_retry_window(
    segments: list[dict],
    plain_lines: list[str],
    *,
    min_gap_s: float = 15.0,
    max_gap_s: float = 25.0,
    context_s: float = 10.0,
) -> tuple[float, float] | None:
    """Find a medium ASR gap near repeated lyrics for a local retry."""
    normalized_lines = [
        re.sub(r"[^a-z0-9 ]", "", line.casefold()).strip()
        for line in plain_lines
        if line.strip()
    ]
    if not any(count >= 2 for count in Counter(normalized_lines).values()):
        return None

    starts = sorted(
        float(word["start"])
        for segment in segments
        for word in segment.get("words", [])
        if isinstance(word, dict) and word.get("start") is not None
    )
    if len(starts) < 2:
        return None
    for previous, current in zip(starts, starts[1:]):
        gap = current - previous
        if min_gap_s <= gap <= max_gap_s:
            return (max(0.0, previous - context_s), current + context_s)
    return None


__all__ = [
    "_approximate_word_timestamps_from_segments",
    "_transcribe_tail_window",
    "_transcribe_fixed_windows",
    "_deduplicate_transcribed_segments",
    "_align_segments_per_chunks",
    "_should_use_per_chunk_alignment",
    "_normalized_transcribe_language",
    "_segment_word_starts",
    "_segment_tail_seconds",
    "_segment_reliable_tail_seconds",
    "_should_retry_with_relaxed_vad",
    "_segment_alignment_quality",
    "_should_use_relaxed_vad_result",
    "_select_best_relaxed_segments",
    "_should_retry_with_short_windows",
    "_find_targeted_retry_window",
]
