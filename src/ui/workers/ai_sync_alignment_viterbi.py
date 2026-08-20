"""Greedy and Viterbi lyric-to-word alignment algorithms."""
from __future__ import annotations

from .ai_sync_alignment_candidates import (
    _anchor_bonus, _build_guided_word_ranges, _build_same_phrase_rewind_targets,
    _build_speech_candidate_mask, _compute_line_to_words_score, _expected_word_position,
    _find_confidence_anchors, _late_line_candidate_start_floor,
    _late_line_expected_position_bonus, _manual_anchor_bonus, _prepare_manual_line_anchors,
    _same_phrase_rewind_penalty, _same_phrase_rewind_transition_penalty, _words_match,
)
from .ai_sync_alignment_tail import (
    _ensure_strictly_increasing_alignment_indices,
    _tail_rescue_alignment_indices, _tail_rescue_collapsed_cluster_indices,
    _tail_rescue_forward_jump_indices, _tail_rescue_rewind_target_lag_indices,
)
from .ai_sync_lrc import _build_lrc_from_plain_layout, _build_lrc_from_plain_lines_and_segments


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
    aligned_indices = _tail_rescue_forward_jump_indices(
        aligned_indices,
        word_starts=[float(w.get("start", 0.0)) for w in words],
        num_lines=num_lines,
    )
    aligned_indices = _tail_rescue_collapsed_cluster_indices(
        aligned_indices,
        word_starts=[float(w.get("start", 0.0)) for w in words],
        num_lines=num_lines,
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

__all__ = ['_align_lyrics_to_segments_viterbi', '_align_lyrics_to_segments']
