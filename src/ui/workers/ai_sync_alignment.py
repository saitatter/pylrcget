"""Lexical scoring, candidate gating and lyric-to-word alignment helpers."""
from __future__ import annotations

from bisect import bisect_left
from difflib import SequenceMatcher

from .ai_sync_lrc import (
    _build_lrc_from_plain_layout,
    _build_lrc_from_plain_lines_and_segments,
)


def _normalize_word(word: str) -> str:
    """Normalize word for comparison (lowercase only, no destructive stripping)."""
    return word.lower()


def _words_match(w1: str, w2: str, threshold: float = 0.85) -> tuple[bool, float]:
    """Match two words using edit distance."""
    norm_w1 = _normalize_word(w1)
    norm_w2 = _normalize_word(w2)
    if norm_w1 == norm_w2:
        return True, 1.0
    try:
        from rapidfuzz import fuzz
    except Exception:
        fuzz = None
    if fuzz is not None:
        ratio = float(fuzz.ratio(norm_w1, norm_w2)) / 100.0
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
        dense_mask = [False] * len(words)
        for idx, base_start in enumerate(starts):
            if not mask[idx] or base_start is None:
                continue
            neighbors = sum(
                1
                for j, other_start in enumerate(starts)
                if mask[j] and other_start is not None
                and abs(other_start - base_start) <= density_window_s
            )
            if neighbors >= min_neighbors:
                dense_mask[idx] = True

        for idx, base_start in enumerate(starts):
            if not in_vocab_flags[idx] or base_start is None:
                continue
            neighbors = sum(
                1
                for j, other_start in enumerate(starts)
                if j != idx
                and other_start is not None
                and _is_speech_like_token(str(words[j].get("word", "")))
                and abs(other_start - base_start) <= density_window_s
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
                    candidate = int(round(last_center + (tail_end - last_center) * frac))
                    if candidate <= last_center:
                        candidate = last_center + k
                    if candidate > tail_end:
                        candidate = tail_end
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
    """Rescue weak late lines that collapsed onto early or middle clusters."""
    if not aligned_indices or len(aligned_indices) != len(line_peak_emissions):
        return aligned_indices
    num_lines = len(aligned_indices)
    if num_lines < 12 or num_words <= 1:
        return aligned_indices
    tail_start = int((num_lines - 1) * tail_start_ratio)
    if tail_start >= num_lines - 2:
        return aligned_indices
    weak_tail = [
        li for li in range(tail_start, num_lines)
        if line_peak_emissions[li] < weak_peak_threshold
    ]
    if len(weak_tail) < max(3, (num_lines - tail_start) // 2):
        return aligned_indices

    starts = word_starts if word_starts and len(word_starts) == num_words else None
    if starts:
        horizon_t = max(starts) if starts else 0.0
        lagging_t = 0
        for li in weak_tail:
            expected_t = _expected_time_position(li, num_lines, horizon_t)
            cur_idx = min(max(0, aligned_indices[li]), num_words - 1)
            if starts[cur_idx] + collapse_gap_seconds < expected_t:
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
                if cur < floor_idx and (
                    line_peak_emissions[li] < weak_peak_threshold or very_late
                ):
                    cur = floor_idx
                cur = max(cur, prev + 1)
                cur = min(cur, num_words - 1)
                rescued[li] = cur
                prev = rescued[li]
            return rescued

    lagging = 0
    for li in weak_tail:
        expected = int(round(_expected_word_position(li, num_lines, num_words)))
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
        prev = cur
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
    """Rescue late repeated lines confidently matched to earlier clusters."""
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
        lag = target - aligned_indices[li]
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
        prev = cur
    return rescued


def _ensure_strictly_increasing_alignment_indices(
    aligned_indices: list[int],
    *,
    num_words: int,
) -> list[int]:
    """Prevent rescue heuristics from collapsing several lines onto one word."""
    if not aligned_indices or num_words <= 0:
        return aligned_indices
    normalized = [min(max(int(index), 0), num_words - 1) for index in aligned_indices]
    for index in range(len(normalized) - 2, -1, -1):
        normalized[index] = min(normalized[index], normalized[index + 1] - 1)
    for index in range(1, len(normalized)):
        normalized[index] = max(normalized[index], normalized[index - 1] + 1)
    if normalized[-1] >= num_words:
        offset = normalized[-1] - (num_words - 1)
        normalized = [max(0, index - offset) for index in normalized]
    return normalized


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
    for li in range(0, first_l):
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


def _align_lyrics_to_segments_viterbi(
    plain_lines: list[str],
    segments: list[dict],
    *,
    manual_anchors: list[dict] | None = None,
) -> str:
    """Align lyrics using monotonic Viterbi dynamic programming."""
    if not segments:
        return ""

    words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []):
            if "start" in w and w.get("word", "").strip():
                words.append(w)
    if not words:
        return _build_lrc_from_plain_lines_and_segments(plain_lines, segments)

    original_lines = [str(line) for line in plain_lines]
    non_empty_entries = [
        (idx, line.strip())
        for idx, line in enumerate(original_lines)
        if line.strip()
    ]
    plain_lines = [text for _, text in non_empty_entries]
    if not plain_lines:
        return ""

    line_words_list = [line.split() for line in plain_lines]
    num_lines = len(plain_lines)
    num_words = len(words)
    if num_words <= 0:
        return _build_lrc_from_plain_lines_and_segments(plain_lines, segments)

    emissions: list[list[float]] = []
    for line_words in line_words_list:
        emissions.append([
            _compute_line_to_words_score(line_words, words, word_idx)
            for word_idx in range(num_words)
        ])
    line_peak_emissions = [max(row) if row else 0.0 for row in emissions]
    anchors = _find_confidence_anchors(line_words_list, words)
    rewind_targets = _build_same_phrase_rewind_targets(plain_lines, emissions)
    manual_targets = _prepare_manual_line_anchors(plain_lines, words, manual_anchors)
    guided_ranges = _build_guided_word_ranges(num_lines, num_words, manual_targets)
    speech_candidate_mask = _build_speech_candidate_mask(words, plain_lines)

    viterbi: dict[tuple[int, int], float] = {}
    backptr: dict[tuple[int, int], int] = {}
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
            search_start = max(0, word_idx - 140)
            for prev_idx in range(search_start, word_idx):
                if (line_idx - 1, prev_idx) not in viterbi:
                    continue
                prev_score = viterbi[(line_idx - 1, prev_idx)]
                word_distance = word_idx - prev_idx
                if word_distance < 0:
                    transition_cost = -10
                elif word_distance == 0:
                    transition_cost = -1
                elif word_distance <= 20:
                    transition_cost = 0
                else:
                    transition_cost = -(word_distance - 20) * 0.05

                expected_pos = _expected_word_position(line_idx, num_lines, num_words)
                position_cost = -abs(word_idx - expected_pos) * 0.18
                total_score = (
                    prev_score
                    + emissions[line_idx][word_idx]
                    + transition_cost
                    + position_cost
                    + _anchor_bonus(line_idx, word_idx, anchors)
                    + _same_phrase_rewind_penalty(line_idx, word_idx, rewind_targets)
                    + _manual_anchor_bonus(line_idx, word_idx, manual_targets)
                    + _same_phrase_rewind_transition_penalty(
                        line_idx, prev_idx, word_idx, rewind_targets
                    )
                    + _late_line_expected_position_bonus(
                        line_idx,
                        word_idx,
                        num_lines=num_lines,
                        num_words=num_words,
                        line_peak_emission=line_peak_emissions[line_idx],
                    )
                )
                if total_score > best_prev_score:
                    best_prev_score = total_score
                    best_prev_idx = prev_idx
            if best_prev_idx >= 0:
                viterbi[(line_idx, word_idx)] = best_prev_score
                backptr[(line_idx, word_idx)] = best_prev_idx

    alignment: dict[int, int] = {}
    best_final_score = -1e18
    best_final_word = -1
    final_start, final_end = guided_ranges.get(
        num_lines - 1, (max(0, num_words - 200), num_words)
    )
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
        return _align_lyrics_to_segments(plain_lines, segments)

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

    aligned_indices: list[int] = []
    previous_idx = -1
    for line_idx in range(num_lines):
        word_idx = alignment.get(line_idx)
        if word_idx is None or word_idx <= previous_idx or word_idx >= len(words):
            candidate_indices = [
                idx
                for idx in range(previous_idx + 1, len(words))
                if speech_candidate_mask[idx]
            ]
            if not candidate_indices:
                candidate_indices = list(range(previous_idx + 1, len(words)))
            if candidate_indices:
                word_idx = max(candidate_indices, key=lambda idx: emissions[line_idx][idx])
            else:
                word_idx = min(max(previous_idx, 0), len(words) - 1)
        word_idx = min(max(int(word_idx), 0), len(words) - 1)
        aligned_indices.append(int(word_idx))
        previous_idx = word_idx

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
    aligned_indices = _ensure_strictly_increasing_alignment_indices(
        aligned_indices,
        num_words=num_words,
    )
    aligned_starts = [
        float(words[word_idx].get("start", 0.0))
        if 0 <= word_idx < len(words)
        else 0.0
        for word_idx in aligned_indices
    ]
    return _build_lrc_from_plain_layout(
        original_lines,
        non_empty_entries,
        aligned_starts,
    )


def _align_lyrics_to_segments(
    plain_lines: list[str],
    segments: list[dict],
    *,
    enable_fuzzy: bool = False,
    fuzzy_threshold: int = 60,
    fuzzy_window_words: int = 12,
) -> str:
    """Align plain lyric lines to word timestamps using greedy matching."""
    if not segments:
        return ""

    words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []):
            if "start" in w and w.get("word", "").strip():
                words.append(w)
    if not words:
        return _build_lrc_from_plain_lines_and_segments(plain_lines, segments)

    fuzz = None
    if enable_fuzzy:
        try:
            from rapidfuzz import fuzz as rapidfuzz_fuzz
            fuzz = rapidfuzz_fuzz
        except Exception:
            fuzz = None

    original_lines = [str(line) for line in plain_lines]
    non_empty_entries = [
        (idx, line.strip())
        for idx, line in enumerate(original_lines)
        if line.strip()
    ]
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
        search_end = min(
            len(words),
            word_idx + len(words) // max(1, len(clean_lines)) + len(line_words) * 3,
        )

        if fuzz is not None:
            best_idx = None
            best_score = -1
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
                aligned_starts.append(float(words[best_idx].get("start", 0.0)))
                word_idx = min(best_idx + len(line_words), len(words))
                continue

        best_idx = word_idx
        best_score = -1
        for i in range(word_idx, search_end):
            score = 0
            for j, lw in enumerate(line_words[:5]):
                if i + j < len(words):
                    wt = words[i + j].get("word", "").strip()
                    matched, similarity = _words_match(wt, lw)
                    if matched and similarity >= 0.85:
                        score += 2
                    elif similarity >= 0.70:
                        score += 1
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx < len(words):
            aligned_starts.append(float(words[best_idx].get("start", 0.0)))
            word_idx = min(best_idx + len(line_words), len(words))
        else:
            last_start = words[-1].get("start", 0.0) if words else 0.0
            aligned_starts.append(float(last_start))

    return _build_lrc_from_plain_layout(
        original_lines,
        non_empty_entries,
        aligned_starts,
    )


__all__ = [
    "_normalize_word",
    "_words_match",
    "_compute_line_to_words_score",
    "_extract_word_confidence",
    "_is_speech_like_token",
    "_build_plain_vocabulary",
    "_build_speech_candidate_mask",
    "_find_confidence_anchors",
    "_anchor_bonus",
    "_normalize_line_text",
    "_expected_word_position",
    "_expected_time_position",
    "_is_late_line",
    "_build_same_phrase_rewind_targets",
    "_same_phrase_rewind_penalty",
    "_same_phrase_rewind_transition_penalty",
    "_late_line_expected_position_bonus",
    "_late_line_candidate_start_floor",
    "_tail_rescue_alignment_indices",
    "_tail_rescue_rewind_target_lag_indices",
    "_ensure_strictly_increasing_alignment_indices",
    "_prepare_manual_line_anchors",
    "_manual_anchor_bonus",
    "_build_guided_word_ranges",
    "_align_lyrics_to_segments_viterbi",
    "_align_lyrics_to_segments",
]
