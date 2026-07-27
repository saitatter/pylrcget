from __future__ import annotations

from dataclasses import dataclass


def _normalize_autofix_line(text: str) -> str:
    cleaned = (text or "").strip()
    # Strip trailing commas and dots (except ellipsis)
    while cleaned.endswith(",") or (cleaned.endswith(".") and not cleaned.endswith("...")):
        cleaned = cleaned[:-1].rstrip()
    if not cleaned:
        return ""

    chars = list(cleaned)
    for index, char in enumerate(chars):
        if char.isalpha():
            chars[index] = char.upper()
            break
    return "".join(chars)


@dataclass(frozen=True)
class LyricsValidationProblem:
    line: int
    message: str
    severity: str = "error"
    fixable: bool = False


def _validate_line_text(content: str, line_no: int, is_synced: bool = False) -> list[LyricsValidationProblem]:
    problems: list[LyricsValidationProblem] = []
    if not content:
        return problems

    if not is_synced and content.startswith("["):
        problems.append(
            LyricsValidationProblem(
                line=line_no,
                message="Line cannot start with an opening square bracket.",
            )
        )
        return problems

    if (content.endswith(".") and not content.endswith("...")) or content.endswith(","):
        problems.append(
            LyricsValidationProblem(
                line=line_no,
                message="Line should not end with punctuation such as comma or dot.",
                fixable=True,
            )
        )

    first_alpha_lower = False
    for char in content:
        if char.isalpha():
            if char.islower():
                first_alpha_lower = True
            break
    if first_alpha_lower:
        problems.append(
            LyricsValidationProblem(
                line=line_no,
                message="Line should start with an uppercase letter.",
                fixable=True,
            )
        )

    return problems


def validate_plain_lyrics(text: str) -> list[LyricsValidationProblem]:
    lines = (text or "").splitlines()
    trimmed = [line.strip() for line in lines]
    problems: list[LyricsValidationProblem] = []

    if len(trimmed) == 1 and trimmed[0] == "[au: instrumental]":
        return problems

    for index, content in enumerate(trimmed):
        line_no = index + 1
        if content:
            problems.extend(_validate_line_text(content, line_no, is_synced=False))
            continue

        if (index == 0 and len(trimmed) > 1) or (index > 0 and not trimmed[index - 1]):
            problems.append(
                LyricsValidationProblem(
                    line=line_no,
                    message="Unnecessary empty line.",
                    fixable=True,
                )
            )

    return problems


def autofix_plain_lyrics(text: str) -> str:
    lines = [(line or "").strip() for line in (text or "").splitlines()]
    fixed: list[str] = []
    previous_empty = False
    for line in lines:
        is_empty = not line
        if is_empty and (not fixed or previous_empty):
            continue
        fixed.append("" if is_empty else _normalize_autofix_line(line))
        previous_empty = is_empty
    while fixed and not fixed[-1]:
        fixed.pop()
    return "\n".join(fixed)


def validate_synced_lyrics(pairs: list[tuple[int, str]]) -> list[LyricsValidationProblem]:
    problems: list[LyricsValidationProblem] = []
    last_non_empty_line: tuple[int, int, str] | None = None
    previous_empty_line: int | None = None
    previous_ms: int | None = None
    timestamp_lines: dict[int, list[int]] = {}

    for index, (ms, text) in enumerate(pairs):
        line_no = index + 1
        current_ms = int(ms)
        content = (text or "").strip()
        timestamp_lines.setdefault(current_ms, []).append(line_no)

        if previous_ms is not None and current_ms < previous_ms:
            problems.append(
                LyricsValidationProblem(
                    line=line_no,
                    message="Timestamps must be monotonically increasing.",
                    fixable=True,
                )
            )
        previous_ms = current_ms

        if content:
            problems.extend(_validate_line_text(content, line_no, is_synced=True))
            last_non_empty_line = (line_no, current_ms, content)
            previous_empty_line = None
        else:
            if previous_empty_line is not None:
                problems.append(
                    LyricsValidationProblem(
                        line=line_no,
                        message="Unnecessary empty line.",
                        fixable=True,
                    )
                )
            previous_empty_line = line_no

    if len(pairs) > 1 and last_non_empty_line is not None:
        line_no, _ms, _content = last_non_empty_line
        if line_no == len(pairs):
            problems.append(
                LyricsValidationProblem(
                    line=line_no,
                    message="Expect a synchronized empty line to mark the end of lyrics.",
                    fixable=True,
                )
            )

    for duplicate_lines in timestamp_lines.values():
        if len(duplicate_lines) < 2:
            continue
        for line_no in duplicate_lines:
            problems.append(
                LyricsValidationProblem(
                    line=line_no,
                    message="Duplicate timestamp; each synced line needs a unique timestamp.",
                    fixable=True,
                )
            )

    return problems


def autofix_synced_lyrics(pairs: list[tuple[int, str]]) -> list[tuple[int, str]]:
    fixed: list[tuple[int, str]] = []
    previous_ms: int | None = None
    for ms, text in sorted(((int(ms), text or "") for ms, text in pairs), key=lambda item: item[0]):
        stripped = _normalize_autofix_line(text)
        if not stripped and fixed and not fixed[-1][1].strip():
            continue
        fixed_ms = ms if previous_ms is None else max(ms, previous_ms + 50)
        fixed.append((fixed_ms, stripped))
        previous_ms = fixed_ms

    while fixed and not fixed[-1][1].strip():
        fixed.pop()

    if len(fixed) > 1 and fixed[-1][1].strip():
        fixed.append((fixed[-1][0] + 5000, ""))

    return fixed
