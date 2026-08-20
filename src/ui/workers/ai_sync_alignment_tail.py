"""Tail-rescue heuristics for lyric alignment."""
from __future__ import annotations

from bisect import bisect_left, bisect_right

from .ai_sync_alignment_candidates import (
    _expected_time_position,
    _expected_word_position,
)


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

def _tail_rescue_forward_jump_indices(
    aligned_indices: list[int],
    *,
    word_starts: list[float],
    num_lines: int,
    jump_threshold_s: float = 28.0,
    expected_lag_s: float = 24.0,
    local_window_s: float = 18.0,
    min_local_words: int = 4,
) -> list[int]:
    """Keep a repeated chorus in its local cluster after a large forward jump."""
    if len(aligned_indices) < 12 or len(word_starts) <= 1:
        return aligned_indices
    if len(aligned_indices) != num_lines:
        return aligned_indices

    horizon_s = max(word_starts)
    for line_idx in range(1, num_lines):
        previous = aligned_indices[line_idx - 1]
        current = aligned_indices[line_idx]
        if not (0 <= previous < len(word_starts) and 0 <= current < len(word_starts)):
            continue
        previous_s = word_starts[previous]
        current_s = word_starts[current]
        expected_s = _expected_time_position(line_idx, num_lines, horizon_s)
        if current_s - previous_s < jump_threshold_s:
            continue
        if current_s - expected_s < expected_lag_s:
            continue

        local_start = max(0.0, expected_s - local_window_s)
        local_end = min(horizon_s, expected_s + local_window_s)
        local_words = [
            idx
            for idx, start in enumerate(word_starts)
            if local_start <= start <= local_end
        ]
        if len(local_words) < min_local_words:
            continue

        rescued = list(aligned_indices)
        rescue_start = max(0, line_idx - 2)
        previous_idx = rescued[rescue_start - 1] if rescue_start > 0 else -1
        for rescued_line in range(rescue_start, num_lines):
            target_s = _expected_time_position(rescued_line, num_lines, horizon_s)
            start_idx = bisect_left(word_starts, max(target_s - local_window_s, 0.0))
            end_idx = bisect_right(
                word_starts,
                min(horizon_s, target_s + local_window_s),
            )
            candidates = [
                idx
                for idx in range(max(start_idx, previous_idx + 1), end_idx)
            ]
            if not candidates:
                continue
            rescued[rescued_line] = min(
                candidates,
                key=lambda idx: abs(word_starts[idx] - target_s),
            )
            previous_idx = rescued[rescued_line]
        return rescued
    return aligned_indices

def _tail_rescue_collapsed_cluster_indices(
    aligned_indices: list[int],
    *,
    word_starts: list[float],
    num_lines: int,
    collapse_window_s: float = 3.0,
    forward_gap_s: float = 20.0,
    local_window_s: float = 12.0,
    min_local_words: int = 8,
) -> list[int]:
    """Recover a repeated lyric block collapsed before a large ASR coverage gap."""
    if len(aligned_indices) < 4 or len(word_starts) <= 1:
        return aligned_indices
    if len(aligned_indices) != num_lines:
        return aligned_indices

    for line_idx in range(2, num_lines - 1):
        first = aligned_indices[line_idx - 2]
        second = aligned_indices[line_idx - 1]
        current = aligned_indices[line_idx]
        if not all(0 <= idx < len(word_starts) for idx in (first, second, current)):
            continue
        if word_starts[second] - word_starts[first] > collapse_window_s:
            continue
        forward_gap = word_starts[current] - word_starts[second]
        if forward_gap < forward_gap_s:
            continue

        local_start = max(0.0, word_starts[second] - local_window_s)
        local_end = word_starts[second] + 1.0
        local_words = [
            idx
            for idx, start in enumerate(word_starts)
            if local_start <= start <= local_end
        ]
        if len(local_words) < min_local_words:
            continue

        rescue_start = line_idx - 2
        rescue_end = min(num_lines, line_idx + 1)
        span = local_words[-1] - local_words[0]
        rescued = list(aligned_indices)
        previous_idx = rescued[rescue_start - 1] if rescue_start > 0 else -1
        for rescued_line in range(rescue_start, rescue_end):
            ratio = (rescued_line - rescue_start) / max(rescue_end - rescue_start - 1, 1)
            target_idx = local_words[0] + round(span * ratio)
            candidates = [
                idx
                for idx in local_words
                if idx > previous_idx
            ]
            if not candidates:
                break
            selected = min(candidates, key=lambda idx: abs(idx - target_idx))
            rescued[rescued_line] = selected
            previous_idx = selected
        else:
            return rescued
    return aligned_indices

def _repair_repeated_prefix_timestamp_gaps(lrc_text: str) -> str:
    """Reposition repeated two-line prefixes collapsed before a long gap."""
    import re

    rows = []
    for line in lrc_text.splitlines():
        match = re.match(r"^\[(\d+):(\d+\.\d+)\](.*)$", line)
        if not match or not match.group(3).strip():
            continue
        minutes, seconds = match.group(1), match.group(2)
        rows.append(
            {
                "line": line,
                "time": int(minutes) * 60 + float(seconds),
                "text": " ".join(re.findall(r"[a-z0-9]+", match.group(3).casefold())),
            }
        )
    if len(rows) < 6:
        return lrc_text

    for index in range(2, len(rows) - 2):
        current = rows[index : index + 3]
        anchor_gap = current[2]["time"] - current[1]["time"]
        if anchor_gap < 15.0 or anchor_gap > 20.5:
            continue
        for previous_index in range(index - 3, -1, -1):
            previous = rows[previous_index : previous_index + 3]
            if [row["text"] for row in previous] != [row["text"] for row in current]:
                continue
            offsets = [
                previous[0]["time"] - previous[2]["time"],
                previous[1]["time"] - previous[2]["time"],
            ]
            repaired = [current[2]["time"] + offset for offset in offsets]
            if not (repaired[0] < repaired[1] < current[2]["time"]):
                continue
            if index > 0 and repaired[0] <= rows[index - 1]["time"]:
                continue
            for row, timestamp in zip(current[:2], repaired):
                minutes = int(timestamp // 60)
                seconds = timestamp - minutes * 60
                row["line"] = re.sub(
                    r"^\[\d+:\d+\.\d+\]",
                    f"[{minutes:02d}:{seconds:05.2f}]",
                    row["line"],
                )
                row["time"] = timestamp
            break

    replacements = {id(row): row["line"] for row in rows}
    output = []
    row_index = 0
    for line in lrc_text.splitlines():
        match = re.match(r"^\[(\d+):(\d+\.\d+)\](.*)$", line)
        if match and match.group(3).strip():
            output.append(replacements[id(rows[row_index])])
            row_index += 1
        else:
            output.append(line)
    return "\n".join(output)

def _tail_rescue_rewind_target_lag_indices(
    aligned_indices: list[int],
    rewind_targets: dict[int, int],
    line_peak_emissions: list[float],
    *,
    num_words: int,
    tail_start_ratio: float = 0.58,
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

__all__ = ['_tail_rescue_alignment_indices', '_tail_rescue_forward_jump_indices', '_tail_rescue_collapsed_cluster_indices', '_repair_repeated_prefix_timestamp_gaps', '_tail_rescue_rewind_target_lag_indices', '_ensure_strictly_increasing_alignment_indices']
