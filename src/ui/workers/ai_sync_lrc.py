"""Pure LRC formatting and plain-layout preservation helpers."""
from __future__ import annotations

import re


def _format_ts(seconds: float) -> str:
    """Format seconds as mm:ss.xx for LRC."""
    seconds = max(seconds, 0)
    total_cs = round(seconds * 100)
    minutes = total_cs // 6000
    secs = (total_cs % 6000) // 100
    centiseconds = total_cs % 100
    return f"{minutes:02d}:{secs:02d}.{centiseconds:02d}"


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
    return bool(
        re.fullmatch(
            r"[\[\(]\s*(music|music playing|instrumental)\s*[\]\)]",
            normalized,
        )
    )


def _build_lrc_from_segments(segments: list[dict]) -> str:
    """Build LRC text from line-level timestamps."""
    lines: list[str] = []
    for segment in segments:
        start = segment.get("start", 0.0)
        text = segment.get("text", "").strip()
        if not text or _is_non_lyric_line(text):
            continue
        lines.append(f"[{_format_ts(start)}] {text}")
    return "\n".join(lines)


def _build_lrc_from_plain_lines_and_segments(
    plain_lines: list[str],
    segments: list[dict],
) -> str:
    """Infer timestamps while preserving the original plain-text layout."""
    original_lines = [str(line) for line in plain_lines]
    non_empty_entries = [
        (index, line.strip())
        for index, line in enumerate(original_lines)
        if line.strip()
    ]
    if not non_empty_entries:
        return ""

    starts: list[float] = []
    for segment in segments:
        start = segment.get("start")
        if isinstance(start, (int, float)):
            starts.append(float(start))

    if not starts:
        starts = [0.0]

    count = len(non_empty_entries)
    if len(starts) >= count:
        max_index = len(starts) - 1
        mapped_starts = [
            starts[round(i * max_index / max(1, count - 1))]
            for i in range(count)
        ]
    else:
        mapped_starts = list(starts)
        while len(mapped_starts) < count:
            mapped_starts.append(mapped_starts[-1] + 2.5)

    return _build_lrc_from_plain_layout(
        original_lines,
        non_empty_entries,
        mapped_starts,
    )


def _build_lrc_from_plain_layout(
    original_lines: list[str],
    non_empty_entries: list[tuple[int, str]],
    non_empty_starts: list[float],
) -> str:
    """Build LRC preserving blank lines and original line order."""
    if not original_lines or not non_empty_entries:
        return ""

    line_count = len(original_lines)
    starts: list[float | None] = [None] * line_count
    texts = [line.strip() for line in original_lines]

    for (original_index, text), start in zip(non_empty_entries, non_empty_starts):
        if 0 <= original_index < line_count:
            starts[original_index] = float(start)
            texts[original_index] = text

    index = 0
    while index < line_count:
        if starts[index] is not None:
            index += 1
            continue

        run_start = index
        while index < line_count and starts[index] is None:
            index += 1
        run_end = index - 1
        run_length = run_end - run_start + 1

        previous = starts[run_start - 1] if run_start > 0 else None
        following = starts[index] if index < line_count else None
        if previous is not None and following is not None:
            step = max(0.0, (following - previous) / (run_length + 1))
            for offset in range(run_length):
                starts[run_start + offset] = previous + step * (offset + 1)
        elif previous is not None:
            for offset in range(run_length):
                starts[run_start + offset] = previous + 0.01 * (offset + 1)
        elif following is not None:
            for offset in range(run_length - 1, -1, -1):
                starts[run_start + offset] = max(
                    0.0,
                    following - 0.01 * (run_length - offset),
                )
        else:
            for offset in range(run_length):
                starts[run_start + offset] = 0.0

    output: list[str] = []
    last_start = 0.0
    for start, text in zip(starts, texts):
        timestamp = max(last_start, float(start or 0.0))
        last_start = timestamp
        if text:
            output.append(f"[{_format_ts(timestamp)}] {text}")
        else:
            output.append(f"[{_format_ts(timestamp)}]")
    return "\n".join(output)


__all__ = [
    "_build_lrc_from_plain_layout",
    "_build_lrc_from_plain_lines_and_segments",
    "_build_lrc_from_segments",
    "_format_ts",
    "_is_non_lyric_line",
]
