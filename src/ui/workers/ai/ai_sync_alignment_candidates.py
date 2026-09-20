"""Candidate scoring, gating and anchor construction for lyric alignment."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from difflib import SequenceMatcher
from functools import lru_cache

try:
    from rapidfuzz import fuzz as _RAPIDFUZZ_FUZZ
except ImportError:
    _RAPIDFUZZ_FUZZ = None

@lru_cache(maxsize=8192)
def _normalize_word(word: str) -> str:
    """Normalize word for comparison (lowercase only, no destructive stripping)."""
    return word.lower()


@lru_cache(maxsize=200_000)
def _words_match(w1: str, w2: str, threshold: float = 0.85) -> tuple[bool, float]:
    """Match two words using edit distance."""
    norm_w1 = _normalize_word(w1)
    norm_w2 = _normalize_word(w2)
    if norm_w1 == norm_w2:
        return True, 1.0
    if _RAPIDFUZZ_FUZZ is not None:
        ratio = float(_RAPIDFUZZ_FUZZ.ratio(norm_w1, norm_w2)) / 100.0
    else:
        ratio = SequenceMatcher(None, norm_w1, norm_w2).ratio()
    return ratio >= threshold, ratio

def _compute_line_to_words_score(
    line_words: list[str],
    words: list[dict],
    start_idx: int,
    window_size: int = 20,
) -> float:
    """Compute how well a plain text line matches a window of ASR words."""
    if start_idx >= len(words):
        return 0.0
    window_end = min(len(words), start_idx + window_size)
    window_words = [w.get("word", "").strip().lower() for w in words[start_idx:window_end]]
    if not window_words or not line_words:
        return 0.0
    line_words_norm = [w.lower() for w in line_words[:10]]
    best_match_ratio = 0.0
    for i in range(len(window_words)):
        window_slice = window_words[i:i + len(line_words_norm)]
        if not window_slice:
            continue
        matched = 0
        for lw in line_words_norm:
            for ww in window_slice:
                _, sim = _words_match(ww, lw, threshold=0.70)
                if sim >= 0.70:
                    matched += 1
                    break
        match_ratio = matched / len(line_words_norm) if line_words_norm else 0.0
        adjusted_ratio = match_ratio - i * 0.02
        best_match_ratio = max(best_match_ratio, adjusted_ratio)
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
    tail_reentry_max_gap_s: float = 35.0,
) -> list[bool]:
    """Build a hard mask for Viterbi candidate words."""
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
        elif in_vocab:
            mask.append(conf >= min_confidence_in_vocab)
        else:
            mask.append(conf >= min_confidence_out_vocab)

    eligible = sum(1 for v in mask if v)
    if len(words) >= 40 and eligible < max(8, len(words) // 25):
        return [True] * len(words)

    starts: list[float | None] = []
    for w in words:
        try:
            starts.append(float(w.get("start")))
        except (TypeError, ValueError):
            starts.append(None)

    timed_count = sum(1 for s in starts if s is not None)
    if timed_count >= 12:
        if len(words) * len(plain_lines) > 200_000:
            return mask
        dense_mask = [False] * len(words)
        timed_positions = [idx for idx, start in enumerate(starts) if start is not None]
        timed_values = [float(starts[idx]) for idx in timed_positions]
        eligible_prefix = [0]
        speech_prefix = [0]
        for idx in timed_positions:
            eligible_prefix.append(eligible_prefix[-1] + int(mask[idx]))
            speech_prefix.append(
                speech_prefix[-1]
                + int(_is_speech_like_token(str(words[idx].get("word", ""))))
            )
        for idx, base_start in enumerate(starts):
            if not mask[idx] or base_start is None:
                continue
            left = bisect_left(timed_values, base_start - density_window_s)
            right = bisect_right(timed_values, base_start + density_window_s)
            neighbors = (
                eligible_prefix[right] - eligible_prefix[left]
            )
            if neighbors >= min_neighbors:
                dense_mask[idx] = True

        for idx, base_start in enumerate(starts):
            if not in_vocab_flags[idx] or base_start is None:
                continue
            left = bisect_left(timed_values, base_start - density_window_s)
            right = bisect_right(timed_values, base_start + density_window_s)
            neighbors = (
                speech_prefix[right]
                - speech_prefix[left]
                - int(_is_speech_like_token(str(words[idx].get("word", ""))))
            )
            token_norm = token_norms[idx]
            has_lyric_match = any(
                token_norm in {
                    _normalize_word(token).strip()
                    for token in str(line).split()
                }
                and _compute_line_to_words_score(
                    str(line).split(), words, max(0, idx - 1), window_size=12
                ) >= 0.65
                for line in plain_lines
                if str(line).strip()
            )
            if neighbors >= min_neighbors and has_lyric_match:
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

            if late_indices:
                reentry_indices = [
                    i for i in late_indices
                    if starts[i] is not None
                    and starts[i] <= reliable_tail + tail_reentry_max_gap_s
                ]
                late_vocab_tokens = {
                    token_norms[i]
                    for i in reentry_indices
                    if token_norms[i] and in_vocab_flags[i]
                }
                strong_late_anchor = any(
                    in_vocab_flags[i]
                    and confidences[i] is not None
                    and float(confidences[i]) >= tail_reentry_min_confidence
                    for i in reentry_indices
                )
                if (
                    strong_late_anchor
                    and len(late_vocab_tokens) >= tail_reentry_min_unique_tokens
                ):
                    for i in reentry_indices:
                        if in_vocab_flags[i] and _is_speech_like_token(
                            str(words[i].get("word", ""))
                        ):
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
    """Build sparse, monotonic confidence anchors."""
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
        for token in {
            _normalize_word(t)
            for t in line_words
            if len(_normalize_word(t)) >= min_token_len
        }:
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
                line_token_counts.get(t, 999),
                len(asr_positions.get(t, [])),
                -len(t),
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
    """Build expected cluster targets for duplicated lines."""
    phrase_to_lines: dict[str, list[int]] = {}
    for idx, line in enumerate(plain_lines):
        key = _normalize_line_text(line)
        if key:
            phrase_to_lines.setdefault(key, []).append(idx)

    targets: dict[int, int] = {}
    for indices in phrase_to_lines.values():
        if len(indices) <= 1:
            continue
        rep_idx = max(indices, key=lambda i: max(emissions[i]) if emissions[i] else 0.0)
        row = emissions[rep_idx]
        candidates = [(wi, score) for wi, score in enumerate(row) if score >= score_threshold]
        if not candidates:
            local_peaks: list[tuple[int, float]] = []
            for wi, score in enumerate(row):
                left = row[wi - 1] if wi > 0 else -1.0
                right = row[wi + 1] if wi + 1 < len(row) else -1.0
                if score >= left and score >= right:
                    local_peaks.append((wi, score))
            local_peaks.sort(key=lambda x: x[1], reverse=True)
            candidates = sorted(local_peaks[:max(8, len(indices) * 3)], key=lambda x: x[0])
        if not candidates:
            continue

        clusters: list[list[tuple[int, float]]] = [[candidates[0]]]
        for wi, score in candidates[1:]:
            if wi - clusters[-1][-1][0] <= min_cluster_gap:
                clusters[-1].append((wi, score))
            else:
                clusters.append([(wi, score)])
        cluster_centers = [max(cluster, key=lambda x: x[1])[0] for cluster in clusters]
        cluster_centers.sort()

        if len(cluster_centers) < len(indices):
            missing = len(indices) - len(cluster_centers)
            last_center = cluster_centers[-1]
            tail_end = len(row) - 1
            if tail_end > last_center:
                for k in range(1, missing + 1):
                    frac = k / max(1, missing)
                    candidate = round(last_center + (tail_end - last_center) * frac)
                    if candidate <= last_center:
                        candidate = last_center + k
                    candidate = min(candidate, tail_end)
                    if candidate > cluster_centers[-1]:
                        cluster_centers.append(candidate)

        for occ_idx, line_idx in enumerate(indices):
            targets[line_idx] = cluster_centers[min(occ_idx, len(cluster_centers) - 1)]
    return targets

def _same_phrase_rewind_penalty(
    line_idx: int,
    word_idx: int,
    rewind_targets: dict[int, int],
    *,
    rewind_slack: int = 18,
) -> float:
    """Penalize mapping duplicated phrases to significantly earlier clusters."""
    target = rewind_targets.get(line_idx)
    if target is None or word_idx >= target - rewind_slack:
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
    """Extra transition penalty when repeated lines remain in an early cluster."""
    target = rewind_targets.get(line_idx)
    if target is None:
        return 0.0
    threshold = target - rewind_slack
    if word_idx >= threshold or prev_word_idx >= threshold:
        return 0.0
    lag = threshold - word_idx
    jump = max(0, word_idx - prev_word_idx)
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
    """Apply a weak position prior for uncertain late lines."""
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
        proximity = 1.0 - (distance / max(1, expected_window_words))
        return strength * 1.4 * proximity
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
    """Return an optional lower bound for weak late-line candidates."""
    if num_lines < 10 or num_words <= 1:
        return None
    if line_peak_emission >= weak_peak_threshold:
        return None
    if not _is_late_line(line_idx, num_lines, late_start_ratio):
        return None
    expected = _expected_word_position(line_idx, num_lines, num_words)
    return int(max(0, expected - expected_back_window))

def _prepare_manual_line_anchors(
    plain_lines: list[str],
    words: list[dict],
    manual_anchors: list[dict] | None,
) -> dict[int, int]:
    """Convert manual line/time anchors into line-index to word-index targets."""
    if not manual_anchors or not words:
        return {}
    word_starts: list[float] = []
    for w in words:
        try:
            word_starts.append(float(w.get("start")))
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
        try:
            line_idx = int(anchor.get("line_index"))
            time_s = float(anchor.get("time_ms")) / 1000.0
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
    """Stronger shaping around user-provided line/time anchors."""
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
    """Build per-line candidate ranges guided by manual anchors."""
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
        pre_slope = (next_w - first_w) / max(1, next_l - first_l)
    else:
        pre_slope = 0.0
    for li in range(first_l):
        expected[li] = first_w - (first_l - li) * pre_slope

    last_l, last_w = anchors[-1]
    if len(anchors) > 1:
        prev_l, prev_w = anchors[-2]
        post_slope = (last_w - prev_w) / max(1, last_l - prev_l)
    else:
        post_slope = 0.0
    for li in range(last_l, num_lines):
        expected[li] = last_w + (li - last_l) * post_slope

    ranges: dict[int, tuple[int, int]] = {}
    for li in range(num_lines):
        center = max(0, min(num_words - 1, round(expected[li])))
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

__all__ = ['_anchor_bonus', '_build_guided_word_ranges', '_build_plain_vocabulary', '_build_same_phrase_rewind_targets', '_build_speech_candidate_mask', '_compute_line_to_words_score', '_expected_time_position', '_expected_word_position', '_extract_word_confidence', '_find_confidence_anchors', '_is_late_line', '_is_speech_like_token', '_late_line_candidate_start_floor', '_late_line_expected_position_bonus', '_manual_anchor_bonus', '_normalize_line_text', '_normalize_word', '_prepare_manual_line_anchors', '_same_phrase_rewind_penalty', '_same_phrase_rewind_transition_penalty', '_words_match']
