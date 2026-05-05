from __future__ import annotations

from core.lyrics_validator import (
    autofix_plain_lyrics,
    autofix_synced_lyrics,
    validate_plain_lyrics,
    validate_synced_lyrics,
)


def test_plain_validator_rejects_bracket_lines_and_extra_empty_lines():
    problems = validate_plain_lyrics("\n[00:01.00] Not plain\n\n\nText")

    assert [problem.line for problem in problems] == [1, 2, 4]
    assert problems[1].message == "Line cannot start with an opening square bracket."


def test_plain_validator_allows_instrumental_tag():
    assert validate_plain_lyrics("[au: instrumental]") == []


def test_plain_autofix_removes_unnecessary_empty_lines():
    assert autofix_plain_lyrics("\nFirst\n\n\nSecond\n") == "First\n\nSecond"


def test_synced_validator_checks_punctuation_order_and_end_marker():
    problems = validate_synced_lyrics([(3000, "Second."), (2000, "First")])

    assert [problem.line for problem in problems] == [1, 2, 2]
    assert "punctuation" in problems[0].message
    assert "monotonically" in problems[1].message
    assert "mark the end" in problems[2].message


def test_synced_autofix_sorts_strips_punctuation_and_adds_end_marker():
    assert autofix_synced_lyrics([(3000, "Second."), (2000, "First,")]) == [
        (2000, "First"),
        (3000, "Second"),
        (8000, ""),
    ]
