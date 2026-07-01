"""
AI-powered lyrics synchronization worker.

Pipeline (runtime):
1. WhisperX transcription + forced alignment -> word timestamps
2. Candidate filtering / guidance (confidence, vocabulary, anchors)
3. Viterbi DP line-to-word alignment
4. Tail rescue heuristics for repeated/ambiguous endings
5. LRC rendering while preserving plain-text layout

Core metric terms used by the algorithm:
- emission score: lexical similarity between one lyric line and a local ASR window (0..1)
- line_peak_emission: max emission over all candidate word starts for that line
- coverage_ratio: reliable_tail_seconds / audio_duration_seconds
- quality score (proxy): line_match * 2.0 + vocab_ratio + coverage * 0.5

Benchmark metrics (outside runtime, in tools) are interpreted as:
- mean_abs_s: average absolute timestamp error per matched line
- p95_abs_s: 95th percentile absolute timestamp error
- rtf: runtime_seconds / audio_duration_seconds

Requires optional dependencies: torch, torchaudio, soundfile, whisperx.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from bisect import bisect_left
from pathlib import Path

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except Exception:
    _rapidfuzz_fuzz = None

_INFERENCE_CACHE_LOCK = threading.Lock()
_WHISPERX_MODEL_CACHE: dict[tuple[str, str, str, str | None, tuple[tuple[str, float], ...]], object] = {}
_ALIGN_MODEL_CACHE: dict[tuple[str, str], tuple[object, object]] = {}


def _clear_inference_caches() -> None:
    """Clear cached WhisperX/align models (used by tests)."""
    with _INFERENCE_CACHE_LOCK:
        _WHISPERX_MODEL_CACHE.clear()
        _ALIGN_MODEL_CACHE.clear()


def _canonical_vad_options(vad_options: dict | None) -> tuple[tuple[str, float], ...]:
    if not vad_options:
        return ()
    normalized: list[tuple[str, float]] = []
    for key in sorted(vad_options):
        try:
            normalized.append((str(key), float(vad_options[key])))
        except (TypeError, ValueError):
            continue
    return tuple(normalized)


def _get_cached_whisperx_model(
    whisperx_module: object,
    model_name: str,
    *,
    device: str,
    compute_type: str,
    vad_method: str | None = None,
    vad_options: dict | None = None,
) -> object:
    """
    Return WhisperX model from in-process cache to avoid repeated load_model cost.
    """
    key = (
        str(model_name or "base"),
        str(device),
        str(compute_type),
        str(vad_method) if vad_method else None,
        _canonical_vad_options(vad_options),
    )
    with _INFERENCE_CACHE_LOCK:
        cached = _WHISPERX_MODEL_CACHE.get(key)
        if cached is not None:
            return cached
    kwargs = {
        "device": device,
        "compute_type": compute_type,
    }
    if vad_method:
        kwargs["vad_method"] = vad_method
    if vad_options:
        kwargs["vad_options"] = vad_options
    model = whisperx_module.load_model(model_name, **kwargs)
    with _INFERENCE_CACHE_LOCK:
        _WHISPERX_MODEL_CACHE[key] = model
    return model


def _get_cached_align_model(
    whisperx_module: object,
    *,
    language_code: str,
    device: str,
) -> tuple[object, object]:
    """
    Return align model/metadata from in-process cache by (language, device).
    """
    normalized_lang = str(language_code or "en").strip().lower() or "en"
    if normalized_lang == "auto":
        normalized_lang = "en"
    key = (normalized_lang, str(device))
    with _INFERENCE_CACHE_LOCK:
        cached = _ALIGN_MODEL_CACHE.get(key)
        if cached is not None:
            return cached
    align_model, metadata = whisperx_module.load_align_model(language_code=normalized_lang, device=device)
    with _INFERENCE_CACHE_LOCK:
        _ALIGN_MODEL_CACHE[key] = (align_model, metadata)
    return align_model, metadata


def get_missing_ai_dependencies() -> list[str]:
    deps = [
        ("torch", "torch"),
        ("torchaudio", "torchaudio"),
        ("soundfile", "soundfile"),
        ("whisperx", "whisperx"),
    ]
    missing: list[str] = []
    for module, package in deps:
        if not _module_available(module):
            missing.append(package)
    return missing


def _module_available(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def _check_ai_sync_available() -> tuple[bool, str]:
    """Check whether the required AI sync dependencies are installed."""
    missing = get_missing_ai_dependencies()
    if missing:
        return False, (
            f"Missing AI dependencies: {', '.join(missing)}.\n\n"
            "If you run PyLrcGet from source, install them in that environment:\n"
            "  pip install .[ai]\n\n"
            "If you use the packaged .exe, install these packages in the app's bundled Python "
            "(installing into system Python is not enough)."
        )
    return True, ""


def is_ai_sync_available() -> bool:
    ok, _ = _check_ai_sync_available()
    return ok


def _format_ts(seconds: float) -> str:
    """Format seconds as mm:ss.xx for LRC."""
    if seconds < 0:
        seconds = 0
    total_cs = int(round(seconds * 100))
    m = total_cs // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{m:02d}:{s:02d}.{cs:02d}"


def _build_lrc_from_segments(segments: list[dict]) -> str:
    """Build LRC text from WhisperX segments (line-level timestamps)."""
    lines: list[str] = []
    for seg in segments:
        start = seg.get("start", 0.0)
        text = seg.get("text", "").strip()
        if not text or _is_non_lyric_line(text):
            continue
        ts = _format_ts(start)
        lines.append(f"[{ts}] {text}")
    return "\n".join(lines)


def _is_non_lyric_line(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return True
    if normalized in {
        "music",
        "music playing",
        "[music]",
        "[music playing]",
        "(music)",
        "(music playing)",
        "instrumental",
        "[instrumental]",
        "(instrumental)",
    }:
        return True
    if re.fullmatch(r"[\[\(]\s*(music|music playing|instrumental)\s*[\]\)]", normalized):
        return True
    return False


def _build_lrc_from_plain_lines_and_segments(
    plain_lines: list[str],
    segments: list[dict],
) -> str:
    """
    Build synced LRC by preserving plain lines verbatim and inferring timestamps
    from available segment timings.
    """
    original_lines = [str(line) for line in plain_lines]
    non_empty_entries = [(idx, line.strip()) for idx, line in enumerate(original_lines) if line.strip()]
    if not non_empty_entries:
        return ""

    starts: list[float] = []
    for seg in segments:
        start = seg.get("start")
        if isinstance(start, (int, float)):
            starts.append(float(start))

    if not starts:
        starts = [0.0]

    non_empty_count = len(non_empty_entries)
    if len(starts) >= non_empty_count:
        # Downsample segment starts to line count while preserving order.
        max_idx = len(starts) - 1
        mapped_starts = [starts[round(i * max_idx / max(1, non_empty_count - 1))] for i in range(non_empty_count)]
    else:
        # Not enough timestamps: extend with a gentle cadence.
        mapped_starts = list(starts)
        step = 2.5
        while len(mapped_starts) < non_empty_count:
            mapped_starts.append(mapped_starts[-1] + step)

    return _build_lrc_from_plain_layout(original_lines, non_empty_entries, mapped_starts)


def _build_lrc_from_plain_layout(
    original_lines: list[str],
    non_empty_entries: list[tuple[int, str]],
    non_empty_starts: list[float],
) -> str:
    """Build LRC preserving original plain-text layout, including blank lines."""
    if not original_lines or not non_empty_entries:
        return ""

    line_count = len(original_lines)
    starts: list[float | None] = [None] * line_count
    texts = [line.strip() for line in original_lines]

    for (orig_idx, text), start in zip(non_empty_entries, non_empty_starts):
        if 0 <= orig_idx < line_count:
            starts[orig_idx] = float(start)
            texts[orig_idx] = text

    idx = 0
    while idx < line_count:
        if starts[idx] is not None:
            idx += 1
            continue

        run_start = idx
        while idx < line_count and starts[idx] is None:
            idx += 1
        run_end = idx - 1
        run_len = run_end - run_start + 1

        prev_start = starts[run_start - 1] if run_start > 0 else None
        next_start = starts[idx] if idx < line_count else None

        if prev_start is not None and next_start is not None:
            step = max(0.0, (next_start - prev_start) / (run_len + 1))
            for k in range(run_len):
                starts[run_start + k] = prev_start + step * (k + 1)
        elif prev_start is not None:
            for k in range(run_len):
                starts[run_start + k] = prev_start + 0.01 * (k + 1)
        elif next_start is not None:
            for k in range(run_len - 1, -1, -1):
                starts[run_start + k] = max(0.0, next_start - 0.01 * (run_len - k))
        else:
            for k in range(run_len):
                starts[run_start + k] = 0.0

    out: list[str] = []
    last_start = 0.0
    for start, text in zip(starts, texts):
        ts = max(last_start, float(start or 0.0))
        last_start = ts
        if text:
            out.append(f"[{_format_ts(ts)}] {text}")
        else:
            out.append(f"[{_format_ts(ts)}]")
    return "\n".join(out)


def _postprocess_lrc_tuples(lrc_tuples: list[tuple[float,str]], *, max_shift: float = 6.0, median_cutoff: float = 20.0) -> list[tuple[float,str]]:
    """Post-process (smooth) list of (start_seconds, text) tuples.

    Strategy:
    - Ensure monotonic increasing starts
    - Compute a robust median of inter-line diffs (excluding huge outliers)
    - Clamp large deviations: if a line is offset from expected by > max_shift, snap it to expected
    - Spread blocks of identical timestamps evenly using median spacing
    """
    if not lrc_tuples:
        return lrc_tuples

    # Work on a copy
    vals = [(float(s), t) for s, t in lrc_tuples]
    # Sort by start to be safe
    vals.sort(key=lambda x: x[0])
    starts = [s for s, _ in vals]
    texts = [t for _, t in vals]

    # Compute diffs and median excluding tiny/huge values
    diffs = []
    for i in range(1, len(starts)):
        d = starts[i] - starts[i-1]
        if 0.05 <= d <= median_cutoff:
            diffs.append(d)
    import statistics
    median_diff = statistics.median(diffs) if diffs else 3.0
    # clamp reasonable bounds
    if median_diff < 0.1:
        median_diff = 0.5

    # Enforce monotonic and clamp large jumps
    new_starts = [starts[0]]
    for i in range(1, len(starts)):
        prev = new_starts[-1]
        cur = starts[i]
        expected = prev + median_diff
        # if current is too far ahead, clamp to expected
        if cur - expected > max_shift:
            cur = expected
        # if current is behind previous (non-monotonic), nudge forward
        if cur <= prev + 0.001:
            cur = prev + max(0.01, median_diff * 0.05)
        new_starts.append(cur)

    # Now detect blocks having identical timestamps (or near-equal) and spread them
    final_starts = new_starts.copy()
    i = 0
    n = len(final_starts)
    while i < n:
        # find run of nearly-equal starts
        j = i + 1
        while j < n and abs(final_starts[j] - final_starts[j-1]) < 0.02:
            j += 1
        run_len = j - i
        if run_len > 1:
            # spread across median_diff spacing starting at final_starts[i]
            base = final_starts[i]
            for k in range(run_len):
                final_starts[i + k] = base + k * (median_diff * 0.9)
        i = j

    # Pair back with texts
    smoothed = [(s, t) for s, t in zip(final_starts, texts)]
    return smoothed


def _normalize_word(word: str) -> str:
    """Normalize word for comparison (lowercase only, no destructive stripping)."""
    return word.lower()


def _words_match(w1: str, w2: str, threshold: float = 0.85) -> tuple[bool, float]:
    """
    Match two words using edit distance.
    
    Returns: (matched: bool, score: float 0.0-1.0)
    - score >= 0.85: good match
    - score >= 0.70: partial match
    - score < 0.70: no match
    """
    norm_w1 = _normalize_word(w1)
    norm_w2 = _normalize_word(w2)

    if norm_w1 == norm_w2:
        return True, 1.0

    if _rapidfuzz_fuzz is not None:
        ratio = float(_rapidfuzz_fuzz.ratio(norm_w1, norm_w2)) / 100.0
    else:
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, norm_w1, norm_w2).ratio()
    return ratio >= threshold, ratio


def _compute_line_to_words_score(line_words: list[str], words: list[dict], start_idx: int, window_size: int = 20) -> float:
    """
    Compute how well a plain text line matches a window of ASR words.
    
    Uses sequence matching to find best alignment within window.
    Returns: score 0.0-1.0 (1.0 = perfect match)
    """
    if start_idx >= len(words):
        return 0.0
    
    window_end = min(len(words), start_idx + window_size)
    window_words = [w.get("word", "").strip().lower() for w in words[start_idx:window_end]]
    
    if not window_words or not line_words:
        return 0.0
    
    line_words_norm = [w.lower() for w in line_words[:10]]
    
    best_match_ratio = 0.0
    
    # Try all starting positions in window
    for i in range(len(window_words)):
        window_slice = window_words[i:i+len(line_words_norm)]
        if not window_slice:
            continue
        
        # Count how many line words are in this window slice
        matched = 0
        for lw in line_words_norm:
            for ww in window_slice:
                _, sim = _words_match(ww, lw, threshold=0.70)
                if sim >= 0.70:
                    matched += 1
                    break
        
        match_ratio = matched / len(line_words_norm) if line_words_norm else 0.0
        
        # Prefer matches that start earlier in the window (more stable)
        # But penalize matches that skip too many words at start
        skip_penalty = i * 0.02
        adjusted_ratio = match_ratio - skip_penalty
        
        if adjusted_ratio > best_match_ratio:
            best_match_ratio = adjusted_ratio
    
    return max(0.0, best_match_ratio)


def _extract_word_confidence(word: dict) -> float | None:
    """Extract normalized confidence score [0, 1] from a Whisper/WhisperX word dict."""
    for key in ("score", "confidence", "probability", "prob"):
        val = word.get(key)
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if 0.0 <= fval <= 1.0:
            return fval
    return None


def _is_speech_like_token(token: str) -> bool:
    normalized = _normalize_word(str(token or "").strip())
    if not normalized:
        return False
    alpha_count = sum(1 for ch in normalized if ch.isalpha())
    return alpha_count >= 2


def _build_plain_vocabulary(plain_lines: list[str]) -> set[str]:
    vocab: set[str] = set()
    for line in plain_lines:
        for tok in str(line).split():
            norm = _normalize_word(tok).strip()
            if len(norm) >= 3:
                vocab.add(norm)
    return vocab


def _build_speech_candidate_mask(
    words: list[dict],
    plain_lines: list[str],
    *,
    min_confidence_in_vocab: float = 0.30,
    min_confidence_out_vocab: float = 0.78,
    density_window_s: float = 1.8,
    min_neighbors: int = 2,
    tail_grace_s: float = 1.2,
    tail_reentry_min_confidence: float = 0.65,
    tail_reentry_min_unique_tokens: int = 3,
) -> list[bool]:
    """
    Build a hard mask for Viterbi candidate words.

    Decision layers:
    1. lexical/token gate: keep only speech-like tokens
    2. confidence gate:
       - in-vocab token: keep when confidence >= min_confidence_in_vocab
       - out-of-vocab token: keep when confidence >= min_confidence_out_vocab
    3. density gate: keep only tokens in speech-dense neighborhoods
    4. tail cutoff: suppress sparse tokens after last reliable dense region
    5. tail re-entry exception: restore late in-vocab phrase when there is
       at least one strong late anchor token and enough unique late vocab tokens

    Example:
    - dense region ends around 160s, isolated tokens appear at 228s
    - if those 228s tokens contain a real in-vocab phrase (e.g. "you don't know")
      and one anchor token has high confidence, they are re-enabled.
    """
    mask: list[bool] = []
    token_norms: list[str] = []
    confidences: list[float | None] = []
    in_vocab_flags: list[bool] = []
    plain_vocab = _build_plain_vocabulary(plain_lines)

    for w in words:
        token = str(w.get("word", ""))
        token_norm = _normalize_word(token).strip()
        token_norms.append(token_norm)
        if not _is_speech_like_token(token):
            confidences.append(None)
            in_vocab_flags.append(False)
            mask.append(False)
            continue

        in_vocab = token_norm in plain_vocab if token_norm else False
        conf = _extract_word_confidence(w)
        confidences.append(conf)
        in_vocab_flags.append(in_vocab)
        if conf is None:
            mask.append(in_vocab)
            continue
        if in_vocab:
            mask.append(conf >= min_confidence_in_vocab)
        else:
            mask.append(conf >= min_confidence_out_vocab)

    # Safety fallback: if mask is too restrictive, disable gating.
    eligible = sum(1 for v in mask if v)
    if len(words) >= 40 and eligible < max(8, len(words) // 25):
        return [True] * len(words)

    # Keep candidates only in speech-dense neighborhoods and suppress tail
    # candidates after the last reliable speech-like region.
    starts: list[float | None] = []
    for w in words:
        start = w.get("start")
        try:
            starts.append(float(start))
        except (TypeError, ValueError):
            starts.append(None)

    timed_count = sum(1 for s in starts if s is not None)
    if timed_count >= 12:
        dense_mask = [False] * len(words)
        for idx, base_start in enumerate(starts):
            if not mask[idx] or base_start is None:
                continue
            neighbors = 0
            for j, other_start in enumerate(starts):
                if not mask[j] or other_start is None:
                    continue
                if abs(other_start - base_start) <= density_window_s:
                    neighbors += 1
            if neighbors >= min_neighbors:
                dense_mask[idx] = True

        dense_count = sum(1 for v in dense_mask if v)
        if dense_count >= max(4, len(words) // 40):
            mask = dense_mask

        reliable_tail = max(
            (starts[i] for i, keep in enumerate(mask) if keep and starts[i] is not None),
            default=None,
        )
        if reliable_tail is not None:
            cutoff = reliable_tail + tail_grace_s
            late_indices: list[int] = []
            for i, start in enumerate(starts):
                if start is not None and start > cutoff:
                    late_indices.append(i)
                    mask[i] = False

            # Keep a true lyrical "tail re-entry" phrase if it is present in plain
            # vocabulary and has at least one strong late anchor token.
            if late_indices:
                late_vocab_tokens = {
                    token_norms[i]
                    for i in late_indices
                    if token_norms[i] and in_vocab_flags[i]
                }
                strong_late_anchor = any(
                    in_vocab_flags[i]
                    and confidences[i] is not None
                    and float(confidences[i]) >= tail_reentry_min_confidence
                    for i in late_indices
                )
                if strong_late_anchor and len(late_vocab_tokens) >= tail_reentry_min_unique_tokens:
                    for i in late_indices:
                        if in_vocab_flags[i] and _is_speech_like_token(str(words[i].get("word", ""))):
                            mask[i] = True

    return mask


def _find_confidence_anchors(
    line_words_list: list[list[str]],
    words: list[dict],
    *,
    min_confidence: float = 0.90,
    min_token_len: int = 4,
    max_token_occurrences: int = 1,
) -> dict[int, int]:
    """
    Build sparse anchor points: line_idx -> word_idx.

    Anchors are based on words that are:
    - high confidence in ASR output
    - rare in lyrics/ASR (to avoid chorus ambiguity)
    - monotonic in timeline
    """
    asr_positions: dict[str, list[int]] = {}
    for idx, w in enumerate(words):
        token = _normalize_word(str(w.get("word", "")).strip())
        if len(token) < min_token_len:
            continue
        conf = _extract_word_confidence(w)
        if conf is None or conf < min_confidence:
            continue
        asr_positions.setdefault(token, []).append(idx)

    if not asr_positions:
        return {}

    line_token_counts: dict[str, int] = {}
    for line_words in line_words_list:
        for token in {_normalize_word(t) for t in line_words if len(_normalize_word(t)) >= min_token_len}:
            line_token_counts[token] = line_token_counts.get(token, 0) + 1

    anchors: dict[int, int] = {}
    prev_anchor_idx = -1

    for line_idx, line_words in enumerate(line_words_list):
        candidates = {
            _normalize_word(t)
            for t in line_words
            if len(_normalize_word(t)) >= min_token_len
        }
        if not candidates:
            continue

        ranked = sorted(
            candidates,
            key=lambda t: (
                line_token_counts.get(t, 999),          # prefer lyrics-rare tokens
                len(asr_positions.get(t, [])),          # then ASR-rare tokens
                -len(t),                                # then longer tokens
            ),
        )

        chosen_idx: int | None = None
        for token in ranked:
            positions = asr_positions.get(token, [])
            if line_token_counts.get(token, 0) != 1:
                continue
            if not positions or len(positions) > max_token_occurrences:
                continue
            next_pos = next((p for p in positions if p > prev_anchor_idx), None)
            if next_pos is not None:
                chosen_idx = next_pos
                break

        if chosen_idx is None:
            continue

        anchors[line_idx] = chosen_idx
        prev_anchor_idx = chosen_idx

    return anchors


def _anchor_bonus(line_idx: int, word_idx: int, anchors: dict[int, int]) -> float:
    """Confidence-anchor shaping for Viterbi state score."""
    anchor_idx = anchors.get(line_idx)
    if anchor_idx is None:
        return 0.0

    distance = abs(word_idx - anchor_idx)
    if distance <= 2:
        return 1.0
    if distance <= 8:
        return 0.3
    if distance <= 20:
        return -0.2
    return -(0.8 + (distance - 20) * 0.01)


def _normalize_line_text(line: str) -> str:
    return " ".join(_normalize_word(tok) for tok in line.split() if tok.strip())


def _expected_word_position(line_idx: int, num_lines: int, num_words: int) -> float:
    """Linear expected word index for a given lyric line index."""
    if num_words <= 1:
        return 0.0
    return (line_idx / max(1, num_lines - 1)) * (num_words - 1)


def _expected_time_position(line_idx: int, num_lines: int, horizon_seconds: float) -> float:
    """Linear expected timeline position (seconds) for a given lyric line index."""
    return (line_idx / max(1, num_lines - 1)) * max(0.0, horizon_seconds)


def _is_late_line(line_idx: int, num_lines: int, late_start_ratio: float) -> bool:
    """Return True when a line index belongs to the configured tail region."""
    late_start = int((num_lines - 1) * late_start_ratio)
    return line_idx >= late_start


def _build_same_phrase_rewind_targets(
    plain_lines: list[str],
    emissions: list[list[float]],
    *,
    score_threshold: float = 0.45,
    min_cluster_gap: int = 26,
) -> dict[int, int]:
    """
    Build expected cluster targets for duplicated lines.

    For each duplicated phrase, we detect temporal clusters of strong matches in ASR word space
    and map each line occurrence to the corresponding cluster order.
    """
    phrase_to_lines: dict[str, list[int]] = {}
    for idx, line in enumerate(plain_lines):
        key = _normalize_line_text(line)
        if key:
            phrase_to_lines.setdefault(key, []).append(idx)

    targets: dict[int, int] = {}

    for indices in phrase_to_lines.values():
        if len(indices) <= 1:
            continue

        # Use the strongest emission row among repeated occurrences.
        rep_idx = max(indices, key=lambda i: max(emissions[i]) if emissions[i] else 0.0)
        row = emissions[rep_idx]
        candidates = [(wi, score) for wi, score in enumerate(row) if score >= score_threshold]
        if not candidates:
            # Fallback: pick top local peaks so repeated clusters are still detected
            # when absolute emission scores are weak.
            local_peaks: list[tuple[int, float]] = []
            for wi, score in enumerate(row):
                left = row[wi - 1] if wi > 0 else -1.0
                right = row[wi + 1] if wi + 1 < len(row) else -1.0
                if score >= left and score >= right:
                    local_peaks.append((wi, score))
            local_peaks.sort(key=lambda x: x[1], reverse=True)
            keep = max(8, len(indices) * 3)
            candidates = sorted(local_peaks[:keep], key=lambda x: x[0])
        if not candidates:
            continue

        # Cluster nearby candidate word indices.
        clusters: list[list[tuple[int, float]]] = [[candidates[0]]]
        for wi, score in candidates[1:]:
            if wi - clusters[-1][-1][0] <= min_cluster_gap:
                clusters[-1].append((wi, score))
            else:
                clusters.append([(wi, score)])

        # Use the highest-scoring point from each cluster as representative.
        cluster_centers: list[int] = []
        for cluster in clusters:
            best_wi, _ = max(cluster, key=lambda x: x[1])
            cluster_centers.append(best_wi)

        cluster_centers.sort()
        if not cluster_centers:
            continue

        # If we detected fewer ASR clusters than repeated lyric occurrences,
        # spread synthetic tail clusters up to the end of word space.
        # This prevents late repeated lines from collapsing onto a mid-song cluster
        # when ASR wording drifts and emissions miss the true final occurrence.
        if len(cluster_centers) < len(indices):
            missing = len(indices) - len(cluster_centers)
            last_center = cluster_centers[-1]
            tail_end = len(row) - 1
            if tail_end > last_center:
                synthetic: list[int] = []
                for k in range(1, missing + 1):
                    frac = k / max(1, missing)
                    candidate = int(round(last_center + (tail_end - last_center) * frac))
                    if candidate <= last_center:
                        candidate = last_center + k
                    if candidate > tail_end:
                        candidate = tail_end
                    synthetic.append(candidate)
                for candidate in synthetic:
                    if candidate > cluster_centers[-1]:
                        cluster_centers.append(candidate)

        # Map k-th repeated line to k-th cluster (clamped if fewer clusters than repeats).
        for occ_idx, line_idx in enumerate(indices):
            target_idx = cluster_centers[min(occ_idx, len(cluster_centers) - 1)]
            targets[line_idx] = target_idx

    return targets


def _same_phrase_rewind_penalty(
    line_idx: int,
    word_idx: int,
    rewind_targets: dict[int, int],
    *,
    rewind_slack: int = 18,
) -> float:
    """
    Penalize mapping duplicated phrases to significantly earlier clusters (rewind).
    """
    target = rewind_targets.get(line_idx)
    if target is None:
        return 0.0
    if word_idx >= target - rewind_slack:
        return 0.0

    rewind_distance = (target - rewind_slack) - word_idx
    return -(2.0 + rewind_distance * 0.055)


def _same_phrase_rewind_transition_penalty(
    line_idx: int,
    prev_word_idx: int,
    word_idx: int,
    rewind_targets: dict[int, int],
    *,
    rewind_slack: int = 18,
) -> float:
    """
    Extra penalty when consecutive lines stay in an early repeated cluster.

    This is transition-level (depends on prev->current), complementary to state penalty.
    """
    target = rewind_targets.get(line_idx)
    if target is None:
        return 0.0

    threshold = target - rewind_slack
    if word_idx >= threshold:
        return 0.0

    # We only penalize "same-cluster drift" when both prev/current are still too early.
    if prev_word_idx >= threshold:
        return 0.0

    lag = threshold - word_idx
    jump = max(0, word_idx - prev_word_idx)

    # If jump is tiny while still lagging behind expected cluster, likely rewind collapse.
    jump_penalty = max(0.0, (7.0 - jump) * 0.16)
    lag_penalty = lag * 0.02
    return -(0.7 + jump_penalty + lag_penalty)


def _late_line_expected_position_bonus(
    line_idx: int,
    word_idx: int,
    *,
    num_lines: int,
    num_words: int,
    line_peak_emission: float,
    late_start_ratio: float = 0.55,
    weak_peak_threshold: float = 0.58,
    expected_window_words: int = 26,
) -> float:
    """
    Apply a weak position prior for late lines whose lexical emission is uncertain.

    This reduces collapse onto early repeated clusters when ASR wording diverges
    near track tail and multiple candidates get similarly weak emission scores.

    Example:
    - line_idx is in final 45% of song
    - lexical peak is weak (< weak_peak_threshold)
    - candidates close to expected timeline get a small positive bonus,
      far-away candidates get a mild penalty.
    """
    if num_lines < 8 or num_words <= 1:
        return 0.0
    if line_peak_emission >= weak_peak_threshold:
        return 0.0

    if not _is_late_line(line_idx, num_lines, late_start_ratio):
        return 0.0

    expected = _expected_word_position(line_idx, num_lines, num_words)
    distance = abs(word_idx - expected)
    weakness = (weak_peak_threshold - max(0.0, line_peak_emission)) / weak_peak_threshold
    strength = 0.9 + weakness * 1.2

    if distance <= expected_window_words:
        # Positive bump near expected late-line position.
        proximity = 1.0 - (distance / max(1, expected_window_words))
        return strength * 1.4 * proximity

    # Mild penalty for far-away candidates, enough to break ties.
    return -(distance - expected_window_words) * 0.016 * strength


def _late_line_candidate_start_floor(
    line_idx: int,
    *,
    num_lines: int,
    num_words: int,
    line_peak_emission: float,
    late_start_ratio: float = 0.62,
    weak_peak_threshold: float = 0.52,
    expected_back_window: int = 38,
) -> int | None:
    """
    Optional lower bound for candidate word index on weak late lines.

    When emission is weak and repetitive, this prevents DP from searching too far
    in early/mid clusters for clearly late lines.
    """
    if num_lines < 10 or num_words <= 1:
        return None
    if line_peak_emission >= weak_peak_threshold:
        return None

    if not _is_late_line(line_idx, num_lines, late_start_ratio):
        return None

    expected = _expected_word_position(line_idx, num_lines, num_words)
    floor = int(max(0, expected - expected_back_window))
    return floor


def _tail_rescue_alignment_indices(
    aligned_indices: list[int],
    line_peak_emissions: list[float],
    *,
    num_words: int,
    word_starts: list[float] | None = None,
    tail_start_ratio: float = 0.70,
    weak_peak_threshold: float = 0.52,
    collapse_gap_words: int = 24,
    collapse_gap_seconds: float = 18.0,
) -> list[int]:
    """
    Rescue tail alignments when weak late lines collapse onto early/mid clusters.

    We keep Viterbi output unless we detect a clear collapse pattern in the tail:
    many weak lines are substantially behind their expected timeline position.

    Trigger intuition:
    - find weak tail lines (low line_peak_emission)
    - compare aligned positions with linear expected positions
    - if enough lines lag by a large margin, lift tail to a minimum floor
      while preserving monotonic progression

    Example:
    - expected tail near 220s, aligned cluster around 122s
    - rescue pushes late lines forward to prevent repeated-phrase rewind collapse.
    """
    if not aligned_indices or len(aligned_indices) != len(line_peak_emissions):
        return aligned_indices
    num_lines = len(aligned_indices)
    if num_lines < 12 or num_words <= 1:
        return aligned_indices

    tail_start = int((num_lines - 1) * tail_start_ratio)
    if tail_start >= num_lines - 2:
        return aligned_indices

    weak_tail = [li for li in range(tail_start, num_lines) if line_peak_emissions[li] < weak_peak_threshold]
    if len(weak_tail) < max(3, (num_lines - tail_start) // 2):
        return aligned_indices

    starts = word_starts if word_starts and len(word_starts) == num_words else None
    if starts:
        # Time-based collapse detection (more robust than word-index on sparse tails).
        horizon_t = max(starts) if starts else 0.0
        lagging_t = 0
        for li in weak_tail:
            expected_t = _expected_time_position(li, num_lines, horizon_t)
            cur_idx = min(max(0, aligned_indices[li]), num_words - 1)
            cur_t = starts[cur_idx]
            if cur_t + collapse_gap_seconds < expected_t:
                lagging_t += 1
        if lagging_t >= max(3, int(len(weak_tail) * 0.55)):
            rescued = list(aligned_indices)
            prev = rescued[max(0, tail_start - 1)] if tail_start > 0 else 0
            for li in range(tail_start, num_lines):
                expected_t = _expected_time_position(li, num_lines, horizon_t)
                floor_t = max(0.0, expected_t - 14.0)
                floor_idx = bisect_left(starts, floor_t)
                floor_idx = min(max(0, floor_idx), num_words - 1)
                cur = rescued[li]
                very_late = li >= int((num_lines - 1) * 0.84)
                if cur < floor_idx and (line_peak_emissions[li] < weak_peak_threshold or very_late):
                    cur = floor_idx
                cur = max(cur, prev + 1)
                cur = min(cur, num_words - 1)
                rescued[li] = cur
                prev = rescued[li]
            return rescued

    expected_positions: dict[int, int] = {}
    lagging = 0
    for li in weak_tail:
        expected = int(round(_expected_word_position(li, num_lines, num_words)))
        expected_positions[li] = expected
        if aligned_indices[li] + collapse_gap_words < expected:
            lagging += 1

    if lagging < max(3, int(len(weak_tail) * 0.55)):
        return aligned_indices

    rescued = list(aligned_indices)
    prev = rescued[max(0, tail_start - 1)] if tail_start > 0 else 0
    for li in range(tail_start, num_lines):
        expected = int(round(_expected_word_position(li, num_lines, num_words)))
        floor = max(prev + 1, expected - 10)
        ceil = min(num_words - 1, expected + 16)
        cur = rescued[li]
        if line_peak_emissions[li] < weak_peak_threshold and cur < floor:
            cur = floor
        cur = min(max(cur, prev + 1), ceil)
        rescued[li] = cur
        prev = rescued[li]

    return rescued


def _tail_rescue_rewind_target_lag_indices(
    aligned_indices: list[int],
    rewind_targets: dict[int, int],
    line_peak_emissions: list[float],
    *,
    num_words: int,
    tail_start_ratio: float = 0.66,
    min_lag_words: int = 26,
    min_tail_hits: int = 3,
    strong_peak_threshold: float = 0.72,
) -> list[int]:
    """
    Rescue late repeated lines that are confidently matched to earlier clusters.

    Unlike `_tail_rescue_alignment_indices` (which focuses on weak-emission collapse),
    this pass targets "confident but wrong" tail lines by comparing aligned indices
    against repeated-phrase rewind targets.
    """
    if not aligned_indices or len(aligned_indices) != len(line_peak_emissions):
        return aligned_indices
    if not rewind_targets:
        return aligned_indices

    num_lines = len(aligned_indices)
    if num_lines < 10 or num_words <= 1:
        return aligned_indices

    tail_start = int((num_lines - 1) * tail_start_ratio)
    if tail_start >= num_lines - 2:
        return aligned_indices

    lagged_tail_lines: list[int] = []
    for li in range(tail_start, num_lines):
        target = rewind_targets.get(li)
        if target is None:
            continue
        cur = aligned_indices[li]
        lag = target - cur
        if lag >= min_lag_words and line_peak_emissions[li] >= strong_peak_threshold:
            lagged_tail_lines.append(li)

    if len(lagged_tail_lines) < min_tail_hits:
        return aligned_indices

    rescued = list(aligned_indices)
    prev = rescued[max(0, tail_start - 1)] if tail_start > 0 else 0
    very_late_start = int((num_lines - 1) * 0.84)
    for li in range(tail_start, num_lines):
        cur = rescued[li]
        target = rewind_targets.get(li)
        if target is not None:
            lag = target - cur
            very_late = li >= very_late_start
            if lag >= min_lag_words and (
                line_peak_emissions[li] >= strong_peak_threshold or very_late
            ):
                floor = max(prev + 1, min(num_words - 1, target - 8))
                if cur < floor:
                    cur = floor
        cur = max(cur, prev + 1)
        cur = min(cur, num_words - 1)
        rescued[li] = cur
        prev = rescued[li]

    return rescued


def _prepare_manual_line_anchors(
    plain_lines: list[str],
    words: list[dict],
    manual_anchors: list[dict] | None,
) -> dict[int, int]:
    """
    Convert manual line/time anchors into Viterbi line_idx -> word_idx targets.
    """
    if not manual_anchors or not words:
        return {}

    word_starts: list[float] = []
    for w in words:
        start = w.get("start")
        try:
            word_starts.append(float(start))
        except (TypeError, ValueError):
            word_starts.append(0.0)

    if not word_starts:
        return {}

    targets: dict[int, int] = {}
    max_line = len(plain_lines) - 1
    max_word = len(words) - 1

    for anchor in manual_anchors:
        if not isinstance(anchor, dict):
            continue

        line_idx_raw = anchor.get("line_index")
        time_ms_raw = anchor.get("time_ms")
        try:
            line_idx = int(line_idx_raw)
            time_s = float(time_ms_raw) / 1000.0
        except (TypeError, ValueError):
            continue

        if line_idx < 0 or line_idx > max_line:
            continue

        insert_pos = bisect_left(word_starts, max(0.0, time_s))
        if insert_pos <= 0:
            word_idx = 0
        elif insert_pos >= len(word_starts):
            word_idx = max_word
        else:
            prev_idx = insert_pos - 1
            next_idx = insert_pos
            if abs(word_starts[next_idx] - time_s) < abs(word_starts[prev_idx] - time_s):
                word_idx = next_idx
            else:
                word_idx = prev_idx

        targets[line_idx] = word_idx

    return targets


def _manual_anchor_bonus(
    line_idx: int,
    word_idx: int,
    manual_targets: dict[int, int],
) -> float:
    """
    Stronger shaping around user-provided line/time anchors.
    """
    target_idx = manual_targets.get(line_idx)
    if target_idx is None:
        return 0.0

    distance = abs(word_idx - target_idx)
    if distance <= 1:
        return 3.0
    if distance <= 4:
        return 1.5
    if distance <= 10:
        return 0.4
    if distance <= 30:
        return -0.6
    return -(1.6 + (distance - 30) * 0.03)


def _build_guided_word_ranges(
    num_lines: int,
    num_words: int,
    manual_targets: dict[int, int],
    *,
    half_window: int = 90,
    min_width: int = 24,
) -> dict[int, tuple[int, int]]:
    """
    Build per-line candidate ranges in ASR word space, guided by manual anchors.

    Returns line_idx -> (start_inclusive, end_exclusive).
    """
    if num_lines <= 0 or num_words <= 0 or not manual_targets:
        return {}

    anchors = sorted(
        (li, max(0, min(num_words - 1, wi)))
        for li, wi in manual_targets.items()
        if 0 <= li < num_lines
    )
    if not anchors:
        return {}

    expected: list[float] = [0.0] * num_lines

    # Interpolate between anchored points.
    for idx, (l0, w0) in enumerate(anchors):
        if idx == len(anchors) - 1:
            continue
        l1, w1 = anchors[idx + 1]
        span = max(1, l1 - l0)
        for li in range(l0, l1 + 1):
            t = (li - l0) / span
            expected[li] = w0 + (w1 - w0) * t

    first_l, first_w = anchors[0]
    if len(anchors) > 1:
        next_l, next_w = anchors[1]
        denom = max(1, next_l - first_l)
        pre_slope = (next_w - first_w) / denom
    else:
        pre_slope = 0.0
    for li in range(0, first_l):
        expected[li] = first_w - (first_l - li) * pre_slope

    last_l, last_w = anchors[-1]
    if len(anchors) > 1:
        prev_l, prev_w = anchors[-2]
        denom = max(1, last_l - prev_l)
        post_slope = (last_w - prev_w) / denom
    else:
        post_slope = 0.0
    for li in range(last_l, num_lines):
        expected[li] = last_w + (li - last_l) * post_slope

    ranges: dict[int, tuple[int, int]] = {}
    for li in range(num_lines):
        center = max(0, min(num_words - 1, int(round(expected[li]))))
        start = max(0, center - half_window)
        end = min(num_words, center + half_window + 1)
        if end - start < min_width:
            pad = (min_width - (end - start) + 1) // 2
            start = max(0, start - pad)
            end = min(num_words, end + pad)
            if end - start < min_width:
                if start == 0:
                    end = min(num_words, start + min_width)
                else:
                    start = max(0, end - min_width)
        ranges[li] = (start, end)

    return ranges


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

    Retry condition:
    - track long enough (min_duration_s)
    - enough lyric lines (min_plain_lines)
    - reliable coverage ratio below threshold:
      reliable_tail_seconds / duration_seconds < min_coverage_ratio
    - uncovered tail gap is large enough (min_tail_gap_s)

    Example:
    - duration=240s, reliable_tail=170s -> coverage_ratio=0.708
    - 240-170=70s tail gap
    => retry=True for defaults (0.708 < 0.83 and 70 >= 25).
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

    Final score:
        quality = line_match * 2.0 + vocab_ratio * 3.0 + coverage * 0.5

    The vocab_ratio weight is deliberately high: an over-aggressive VAD onset inflates
    line_match (more ASR words -> more chances to match a line) while diluting the words
    with out-of-vocabulary instrumental noise, which shows up as a drop in vocab_ratio.
    Weighting vocab_ratio strongly lets the selector reject an over-detecting onset (real
    noise) while still accepting an aggressive onset that recovers genuine lyrics (whose
    words stay in-vocabulary, keeping vocab_ratio stable).

    Example:
    - line_match=0.62, vocab_ratio=0.58, coverage=0.80
    - quality=0.62*2 + 0.58*3 + 0.80*0.5 = 3.38
    Higher is better (used only for comparing two candidate ASR outputs).
    """
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

    # Limit candidate starts to keep scoring cheap for long tracks.
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

    Prefer relaxed result when:
    1) it substantially extends tail coverage (tail gain > min_tail_gain_s), OR
    2) it materially improves the quality proxy
       (relaxed_quality > default_quality + min_quality_gain).

    Example:
    - default_tail=160s, relaxed_tail=165s -> gain 5s (not enough by tail)
    - default_quality=1.91, relaxed_quality=1.95, min_quality_gain=0.01
    => choose relaxed (quality gain 0.04).
    """
    default_tail = _segment_tail_seconds(default_segments)
    relaxed_tail = _segment_tail_seconds(relaxed_segments)
    if relaxed_tail > default_tail + min_tail_gain_s:
        return True

    default_quality = _segment_alignment_quality(default_segments, plain_lines, duration_s)
    relaxed_quality = _segment_alignment_quality(relaxed_segments, plain_lines, duration_s)
    return relaxed_quality > default_quality + min_quality_gain


def _select_best_relaxed_segments(
    default_segments: list[dict],
    relaxed_candidates: list[list[dict]],
    plain_lines: list[str],
    duration_s: float,
) -> list[dict] | None:
    """
    Choose the best relaxed-VAD candidate over the default pass, or None to keep default.

    Each candidate must first clear `_should_use_relaxed_vad_result` (i.e. it is
    genuinely better than the default pass). Among the candidates that pass, the one
    with the highest `_segment_alignment_quality` proxy is returned.

    This lets the pipeline run several VAD onsets (softly-sung sections need an
    aggressive onset, but that onset over-detects on other tracks) and keep whichever
    recovers the most real lyrical coverage without regressing.
    """
    best_segments = None
    best_quality = None
    for candidate in relaxed_candidates:
        if not _should_use_relaxed_vad_result(default_segments, candidate, plain_lines, duration_s):
            continue
        quality = _segment_alignment_quality(candidate, plain_lines, duration_s)
        if best_quality is None or quality > best_quality:
            best_segments = candidate
            best_quality = quality
    return best_segments


def _align_lyrics_to_segments_viterbi(
    plain_lines: list[str],
    segments: list[dict],
    *,
    manual_anchors: list[dict] | None = None,
) -> str:
    """
    Align lyrics using Viterbi DP (dynamic programming).
    
    This finds the globally optimal monotonic path (line_idx -> word_idx),
    instead of local greedy choices.

    Scoring components per transition:
    - emission: lexical similarity for current line/candidate word
    - transition_cost: penalizes excessive jumps or non-progression
    - position_cost: soft global timeline prior (prevents repeated-phrase rewind)
    - anchor/rewind/manual/tail shaping bonuses: targeted heuristics for ambiguity

    Method overview:
    1. Build emissions matrix [num_lines x num_words]
    2. Build constraints (speech mask, anchors, guided ranges)
    3. Run Viterbi forward DP
    4. Backtrack best path
    5. Apply tail rescue when late weak lines collapsed too early
    6. Render final timestamps with original plain-text layout
    """
    if not segments:
        return ""

    # Collect all words with timestamps
    words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []):
            if "start" in w and w.get("word", "").strip():
                words.append(w)

    if not words:
        return _build_lrc_from_plain_lines_and_segments(plain_lines, segments)

    original_lines = [str(line) for line in plain_lines]
    non_empty_entries = [(idx, line.strip()) for idx, line in enumerate(original_lines) if line.strip()]
    plain_lines = [text for _, text in non_empty_entries]
    if not plain_lines:
        return ""

    # Build word array
    line_words_list = [l.split() for l in plain_lines]

    num_lines = len(plain_lines)
    num_words = len(words)
    if num_words <= 0:
        return _build_lrc_from_plain_lines_and_segments(plain_lines, segments)

    # Precompute emissions once (critical perf fix).
    emissions: list[list[float]] = []
    for line_words in line_words_list:
        row = [_compute_line_to_words_score(line_words, words, word_idx) for word_idx in range(num_words)]
        emissions.append(row)
    line_peak_emissions: list[float] = [max(row) if row else 0.0 for row in emissions]

    # Build sparse confidence anchors globally.
    anchors = _find_confidence_anchors(line_words_list, words)
    rewind_targets = _build_same_phrase_rewind_targets(plain_lines, emissions)
    manual_targets = _prepare_manual_line_anchors(plain_lines, words, manual_anchors)
    guided_ranges = _build_guided_word_ranges(num_lines, num_words, manual_targets)
    speech_candidate_mask = _build_speech_candidate_mask(words, plain_lines)

    # Initialize DP
    viterbi = {}
    backptr = {}

    # Start: try to match first line near beginning.
    start0, end0 = guided_ranges.get(0, (0, min(120, num_words)))
    for word_idx in range(start0, min(end0, num_words)):
        if not speech_candidate_mask[word_idx]:
            continue
        score = (
            emissions[0][word_idx]
            + _anchor_bonus(0, word_idx, anchors)
            + _same_phrase_rewind_penalty(0, word_idx, rewind_targets)
            + _manual_anchor_bonus(0, word_idx, manual_targets)
        )
        viterbi[(0, word_idx)] = score
        backptr[(0, word_idx)] = -1

    # Forward pass: fill DP table
    for line_idx in range(1, num_lines):
        candidate_start, candidate_end = guided_ranges.get(line_idx, (0, num_words))
        late_floor = _late_line_candidate_start_floor(
            line_idx,
            num_lines=num_lines,
            num_words=num_words,
            line_peak_emission=line_peak_emissions[line_idx],
        )
        if late_floor is not None:
            candidate_start = max(candidate_start, late_floor)
        if candidate_start >= candidate_end:
            continue

        for word_idx in range(candidate_start, candidate_end):
            if not speech_candidate_mask[word_idx]:
                continue
            best_prev_score = -1e18
            best_prev_idx = -1

            # Try all previous word indices
            search_start = max(0, word_idx - 140)  # look back max 140 words
            search_end = word_idx

            for prev_idx in range(search_start, search_end):
                if (line_idx - 1, prev_idx) not in viterbi:
                    continue

                prev_score = viterbi[(line_idx - 1, prev_idx)]

                # Transition cost: penalize big jumps or backwards movement.
                word_distance = word_idx - prev_idx
                if word_distance < 0:
                    transition_cost = -10  # Big penalty for going backwards
                elif word_distance == 0:
                    transition_cost = -1   # Small penalty for staying
                elif word_distance <= 20:
                    transition_cost = 0    # Normal progression
                else:
                    transition_cost = -(word_distance - 20) * 0.05  # Gradual penalty for big jumps

                # Global position prior: avoid collapsing early duplicate lines
                # onto a later repeated section with similar text.
                expected_pos = _expected_word_position(line_idx, num_lines, num_words)
                position_cost = -abs(word_idx - expected_pos) * 0.08

                emission = emissions[line_idx][word_idx]
                anchor_shape = _anchor_bonus(line_idx, word_idx, anchors)
                rewind_shape = _same_phrase_rewind_penalty(line_idx, word_idx, rewind_targets)
                manual_anchor_shape = _manual_anchor_bonus(line_idx, word_idx, manual_targets)
                rewind_transition_shape = _same_phrase_rewind_transition_penalty(
                    line_idx,
                    prev_idx,
                    word_idx,
                    rewind_targets,
                )
                late_position_shape = _late_line_expected_position_bonus(
                    line_idx,
                    word_idx,
                    num_lines=num_lines,
                    num_words=num_words,
                    line_peak_emission=line_peak_emissions[line_idx],
                )

                total_score = (
                    prev_score
                    + emission
                    + transition_cost
                    + position_cost
                    + anchor_shape
                    + rewind_shape
                    + manual_anchor_shape
                    + rewind_transition_shape
                    + late_position_shape
                )

                if total_score > best_prev_score:
                    best_prev_score = total_score
                    best_prev_idx = prev_idx

            if best_prev_idx >= 0:
                viterbi[(line_idx, word_idx)] = best_prev_score
                backptr[(line_idx, word_idx)] = best_prev_idx

    # Backtrack: find best path
    alignment = {}  # line_idx -> word_idx

    # Find best final state
    best_final_score = -1e18
    best_final_word = -1
    final_start, final_end = guided_ranges.get(num_lines - 1, (max(0, num_words - 200), num_words))
    late_final_floor = _late_line_candidate_start_floor(
        num_lines - 1,
        num_lines=num_lines,
        num_words=num_words,
        line_peak_emission=line_peak_emissions[num_lines - 1],
    )
    if late_final_floor is not None:
        final_start = max(final_start, late_final_floor)

    for word_idx in range(final_start, final_end):
        if not speech_candidate_mask[word_idx]:
            continue
        if (num_lines - 1, word_idx) in viterbi:
            score = viterbi[(num_lines - 1, word_idx)]
            if score > best_final_score:
                best_final_score = score
                best_final_word = word_idx

    if best_final_word < 0:
        # Fallback to greedy
        return _align_lyrics_to_segments(plain_lines, segments)

    # Backtrack
    line_idx = num_lines - 1
    word_idx = best_final_word
    while line_idx >= 0:
        alignment[line_idx] = word_idx
        if line_idx == 0:
            break
        word_idx = backptr.get((line_idx, word_idx), -1)
        if word_idx < 0:
            break
        line_idx -= 1

    # Build LRC from alignment
    aligned_indices: list[int] = []
    fallback_idx = len(words) - 1
    for line_idx in range(num_lines):
        word_idx = alignment.get(line_idx)
        if word_idx is None or word_idx < 0 or word_idx >= len(words):
            word_idx = fallback_idx
        aligned_indices.append(int(word_idx))

    aligned_indices = _tail_rescue_alignment_indices(
        aligned_indices,
        line_peak_emissions,
        num_words=num_words,
        word_starts=[float(w.get("start", 0.0)) for w in words],
    )
    aligned_indices = _tail_rescue_rewind_target_lag_indices(
        aligned_indices,
        rewind_targets,
        line_peak_emissions,
        num_words=num_words,
    )

    aligned_starts: list[float] = []
    for word_idx in aligned_indices:
        start = words[word_idx].get("start", 0.0) if 0 <= word_idx < len(words) else 0.0
        aligned_starts.append(float(start))

    return _build_lrc_from_plain_layout(original_lines, non_empty_entries, aligned_starts)


def _align_lyrics_to_segments(
    plain_lines: list[str],
    segments: list[dict],
    *,
    enable_fuzzy: bool = False,
    fuzzy_threshold: int = 60,
    fuzzy_window_words: int = 12,
) -> str:
    """
    Align provided plain lyrics lines to word timestamps.

    Two modes:
    - Greedy (original): compare first few words with windowed words
    - Fuzzy (optional): use rapidfuzz to score a sliding window of words and pick best match

    Returns LRC text.
    """
    if not segments:
        return ""

    # Collect all words with timestamps
    words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []):
            if "start" in w and w.get("word", "").strip():
                words.append(w)

    if not words:
        # Fall back to segment-level timestamps but preserve plain text lines.
        return _build_lrc_from_plain_lines_and_segments(plain_lines, segments)

    # Try to import rapidfuzz if fuzzy matching requested
    fuzz = None
    if enable_fuzzy:
        try:
            from rapidfuzz import fuzz as _fuzz
            fuzz = _fuzz
        except Exception:
            fuzz = None

    original_lines = [str(line) for line in plain_lines]
    non_empty_entries = [(idx, line.strip()) for idx, line in enumerate(original_lines) if line.strip()]
    clean_lines = [text for _, text in non_empty_entries]
    if not clean_lines:
        return ""

    aligned_starts: list[float] = []
    word_idx = 0

    for line in clean_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        line_words = line_stripped.split()
        if not line_words:
            continue

        # Define search window end
        search_end = min(
            len(words),
            word_idx + len(words) // max(1, len(clean_lines)) + len(line_words) * 3,
        )

        # If fuzzy available, search by sliding window and use partial_ratio
        if fuzz is not None:
            best_idx = None
            best_score = -1
            # window size heuristic
            base_window = max(fuzzy_window_words, len(line_words) * 2)
            for i in range(word_idx, search_end):
                window_end = min(len(words), i + base_window)
                if window_end <= i:
                    continue
                wtext = " ".join(w.get("word", "") for w in words[i:window_end])
                try:
                    score = fuzz.partial_ratio(line_stripped, wtext)
                except Exception:
                    score = 0
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_score >= fuzzy_threshold and best_idx is not None:
                start = words[best_idx].get("start", 0.0)
                aligned_starts.append(float(start))
                word_idx = min(best_idx + len(line_words), len(words))
                continue
            # else fall through to greedy

        # Greedy fallback (original behavior)
        best_idx = word_idx
        best_score = -1
        for i in range(word_idx, search_end):
            score = 0
            for j, lw in enumerate(line_words[:5]):  # compare first 5 words
                if i + j < len(words):
                    wt = words[i + j].get("word", "").strip()
                    
                    # Use normalized comparison instead of destructive stripping
                    matched, similarity = _words_match(wt, lw)
                    if matched and similarity >= 0.85:
                        score += 2
                    elif similarity >= 0.70:
                        score += 1
            if score > best_score:
                best_score = score
                best_idx = i

        # Use the timestamp of the matched word
        if best_idx < len(words):
            start = words[best_idx].get("start", 0.0)
            aligned_starts.append(float(start))
            word_idx = min(best_idx + len(line_words), len(words))
        else:
            last_start = words[-1].get("start", 0.0) if words else 0.0
            aligned_starts.append(float(last_start))

    return _build_lrc_from_plain_layout(original_lines, non_empty_entries, aligned_starts)


class AiSyncWorker(QThread):
    """
    Worker thread for AI-powered lyrics synchronization.

    Takes an audio file path and optional plain lyrics,
    produces synced LRC lyrics using Demucs + WhisperX.
    """

    progress = Signal(str)  # status message
    completed = Signal(bool, str, str)  # ok, message, lrc_text
    _PROGRESS_MARKER = "__AI_SYNC_PROGRESS__"

    def __init__(
        self,
        audio_path: str,
        plain_lyrics: str = "",
        *,
        manual_anchors: list[dict] | None = None,
        whisper_model: str = "base",
        device: str = "auto",
        language: str = "auto",
        enable_fuzzy: bool = True,
        fuzzy_threshold: int = 60,
        fuzzy_window_words: int = 12,
        parent=None,
    ):
        super().__init__(parent)
        self.audio_path = audio_path
        self.plain_lyrics = (plain_lyrics or "").strip()
        self.manual_anchors = [a for a in (manual_anchors or []) if isinstance(a, dict)]
        self.whisper_model = whisper_model or "base"
        self._device = device
        self._language = str(language or "auto")
        self._enable_fuzzy = bool(enable_fuzzy)
        self._fuzzy_threshold = int(fuzzy_threshold)
        self._fuzzy_window_words = int(fuzzy_window_words)

    def _resolve_device(self) -> str:
        import torch
        if self._device and self._device != "auto":
            return self._device
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _emit_stage(self, current: int, total: int, message: str) -> None:
        self.progress.emit(f"{self._PROGRESS_MARKER}|{int(current)}|{int(total)}|{message}")

    def run(self):
        vocals_path = None
        try:
            ok, msg = _check_ai_sync_available()
            if not ok:
                self.completed.emit(False, msg, "")
                return

            import torch
            import whisperx

            device = self._resolve_device()
            total_steps = 8

            self._emit_stage(1, total_steps, f"Loading audio file ({Path(self.audio_path).name})…")
            if self.isInterruptionRequested():
                self.completed.emit(False, "Cancelled.", "")
                return

            self._emit_stage(2, total_steps, f"Loading ASR model ({self.whisper_model}, {device})…")
            compute_type = "float16" if device == "cuda" else "int8"
            model = _get_cached_whisperx_model(
                whisperx,
                self.whisper_model,
                device=device,
                compute_type=compute_type,
            )
            if self.isInterruptionRequested():
                self.completed.emit(False, "Cancelled.", "")
                return

            audio = whisperx.load_audio(self.audio_path)
            transcribe_language = _normalized_transcribe_language(self._language)
            language_label = transcribe_language or "auto-detect"

            def _transcribe_and_align(model_obj, *, pass_label: str):
                self._emit_stage(3, total_steps, f"Transcribing audio ({pass_label}, language: {language_label})…")
                if transcribe_language is None:
                    result_local = model_obj.transcribe(audio)
                else:
                    result_local = model_obj.transcribe(audio, language=transcribe_language)

                self._emit_stage(4, total_steps, f"Aligning detected words to audio ({pass_label})…")
                language = transcribe_language or result_local.get("language", "en")
                if language == "auto":
                    language = "en"

                # Try alignment on the specified device, fallback to CPU on error
                # (WhisperX alignment with Pyannote VAD can hang on Windows CUDA)
                alignment_device = device
                try:
                    align_model, metadata = _get_cached_align_model(
                        whisperx,
                        language_code=str(language),
                        device=alignment_device,
                    )
                    result_local = whisperx.align(result_local["segments"], align_model, metadata, audio, alignment_device)
                except Exception as e:
                    if alignment_device != "cpu":
                        logger.warning("Alignment on %s failed, retrying on CPU: %s", alignment_device, e)
                        try:
                            align_model, metadata = _get_cached_align_model(
                                whisperx,
                                language_code=str(language),
                                device="cpu",
                            )
                            result_local = whisperx.align(result_local["segments"], align_model, metadata, audio, "cpu")
                        except Exception as e2:
                            logger.warning("CPU alignment also failed, using raw segments: %s", e2)
                            # segments will remain without word-level timestamps
                    else:
                        logger.warning("CPU alignment failed, using raw segments: %s", e)
                return result_local.get("segments", [])

            segments = _transcribe_and_align(model, pass_label="base pass")

            plain_lines = self.plain_lyrics.splitlines() if self.plain_lyrics else []
            self._emit_stage(5, total_steps, "Checking speech coverage and selecting best pass…")
            if _should_retry_with_relaxed_vad(audio, segments, plain_lines):
                duration_s = float(len(audio)) / 16000.0 if hasattr(audio, "__len__") else 0.0
                # Escalating relaxed-VAD onsets. Softly-sung sections (e.g. quiet
                # acoustic choruses) are missed by the default VAD and even by a
                # single relaxed pass; a more aggressive onset recovers them but can
                # over-detect instrumental noise on other tracks. We run several
                # onsets and keep the candidate with the best alignment-quality proxy
                # (whose strongly weighted vocab_ratio term rejects a noise-diluted
                # over-detecting pass while still accepting an aggressive pass that
                # recovers genuine in-vocabulary lyrics). Guarded so we only ever
                # replace the default pass when a relaxed pass is genuinely better.
                relaxed_vad_configs = (
                    {"vad_onset": 0.15, "vad_offset": 0.05},
                    {"vad_onset": 0.10, "vad_offset": 0.03},
                    {"vad_onset": 0.02, "vad_offset": 0.01},
                )
                best_relaxed = None
                relaxed_candidates: list[list[dict]] = []
                for idx, vad_options in enumerate(relaxed_vad_configs, start=1):
                    self._emit_stage(
                        5,
                        total_steps,
                        f"Low coverage detected — running relaxed VAD retry "
                        f"({idx}/{len(relaxed_vad_configs)}, onset {vad_options['vad_onset']:.2f})…",
                    )
                    relaxed_model = _get_cached_whisperx_model(
                        whisperx,
                        self.whisper_model,
                        device=device,
                        compute_type=compute_type,
                        vad_method="pyannote",
                        vad_options=vad_options,
                    )
                    relaxed_candidates.append(
                        _transcribe_and_align(
                            relaxed_model,
                            pass_label=f"relaxed VAD pass (onset {vad_options['vad_onset']:.2f})",
                        )
                    )

                best_relaxed = _select_best_relaxed_segments(
                    segments, relaxed_candidates, plain_lines, duration_s
                )
                if best_relaxed is not None:
                    logger.info(
                        "Using relaxed VAD result (tail %.2fs -> %.2fs).",
                        _segment_tail_seconds(segments),
                        _segment_tail_seconds(best_relaxed),
                    )
                    segments = best_relaxed

            self._emit_stage(6, total_steps, "Building synced LRC output…")

            if plain_lines:
                # produce tuples first so we can post-process smoothing
                lrc_tuples = []
                if self.manual_anchors:
                    self._emit_stage(
                        7,
                        total_steps,
                        f"Aligning lyric lines (using {len(self.manual_anchors)} manual anchor hint(s))…",
                    )
                else:
                    self._emit_stage(7, total_steps, "Aligning lyric lines to word timestamps…")
                
                # Try Viterbi DP alignment (global optimization)
                # If it fails, fall back to greedy
                try:
                    raw = _align_lyrics_to_segments_viterbi(
                        plain_lines,
                        segments,
                        manual_anchors=self.manual_anchors,
                    )
                except Exception as e:
                    logger.warning("Viterbi alignment failed, falling back to greedy: %s", e)
                    raw = _align_lyrics_to_segments(
                        plain_lines,
                        segments,
                        enable_fuzzy=self._enable_fuzzy,
                        fuzzy_threshold=self._fuzzy_threshold,
                        fuzzy_window_words=self._fuzzy_window_words,
                    )
                
                # raw is LRC string; parse into tuples
                for ln in raw.splitlines():
                    ln = ln.strip()
                    if not ln or not ln.startswith("["):
                        continue
                    try:
                        end = ln.index("]")
                        ts = ln[1:end]
                        mm, rest = ts.split(":")
                        ss, cs = rest.split(".")
                        seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
                        text = ln[end+1:].strip()
                        lrc_tuples.append((seconds, text))
                    except Exception:
                        continue
                # Keep raw aligned timing; smoothing can over-compress long instrumental gaps.
                lrc = "\n".join(f"[{_format_ts(s)}] {t}" for s, t in lrc_tuples)
            else:
                self._emit_stage(7, total_steps, "No plain lyrics provided — using segment-level timestamps…")
                lrc = _build_lrc_from_segments(segments)

            self._emit_stage(8, total_steps, "Finalizing AI sync result…")

            if not lrc.strip():
                self.completed.emit(False, "Could not generate synced lyrics — no speech detected.", "")
                return

            self.completed.emit(True, "Lyrics synchronized successfully.", lrc)

        except Exception as exc:
            logger.error("AI sync failed: %s", exc, exc_info=True)
            self.completed.emit(False, f"AI sync failed: {exc}", "")
        finally:
            if vocals_path and os.path.isfile(vocals_path):
                try:
                    os.unlink(vocals_path)
                except OSError:
                    pass
