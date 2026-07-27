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


def test_plain_autofix_trims_and_capitalizes_first_letter_after_symbols():
    assert autofix_plain_lyrics("  'cause  \n  ¿debería  \n  hello  ") == "'Cause\n¿Debería\nHello"


def test_synced_validator_checks_punctuation_order_and_end_marker():
    problems = validate_synced_lyrics([(3000, "Second."), (2000, "First")])

    assert [problem.line for problem in problems] == [1, 2, 2]
    assert "punctuation" in problems[0].message
    assert "monotonically" in problems[1].message
    assert "mark the end" in problems[2].message


def test_synced_validator_rejects_duplicate_timestamps_on_all_matching_lines():
    problems = validate_synced_lyrics([(1200, "First"), (1200, "Second"), (3000, "")])

    duplicate_problems = [problem for problem in problems if "Duplicate timestamp" in problem.message]
    assert [problem.line for problem in duplicate_problems] == [1, 2]
    assert all(problem.fixable for problem in duplicate_problems)


def test_synced_autofix_sorts_strips_punctuation_and_adds_end_marker():
    assert autofix_synced_lyrics([(3000, "Second."), (2000, "First,")]) == [
        (2000, "First"),
        (3000, "Second"),
        (8000, ""),
    ]


def test_synced_autofix_trims_and_capitalizes_first_letter_after_symbols():
    assert autofix_synced_lyrics([(1000, "  'cause  "), (2000, "  ¿debería  "), (3000, "  hello  ")]) == [
        (1000, "'Cause"),
        (2000, "¿Debería"),
        (3000, "Hello"),
        (8000, ""),
    ]


def test_synced_autofix_separates_duplicate_timestamps():
    assert autofix_synced_lyrics([(1200, "First"), (1200, "Second"), (1210, "Third"), (5000, "")]) == [
        (1200, "First"),
        (1250, "Second"),
        (1300, "Third"),
        (6300, ""),
    ]


def test_validator_detects_lowercase_start():
    # plain validation
    problems_plain = validate_plain_lyrics("hello\nWorld")
    assert len(problems_plain) == 1
    assert problems_plain[0].line == 1
    assert "uppercase" in problems_plain[0].message
    assert problems_plain[0].fixable

    # synced validation
    problems_synced = validate_synced_lyrics([(1000, "hello"), (2000, "World")])
    # might have lowercase problem and end marker problem
    lowercase_problem = [p for p in problems_synced if "uppercase" in p.message]
    assert len(lowercase_problem) == 1
    assert lowercase_problem[0].line == 1
    assert lowercase_problem[0].fixable


def test_plain_validator_and_autofix_handles_punctuation():
    problems = validate_plain_lyrics("First line.\nsecond line,")
    # line 1: ends with dot
    # line 2: ends with comma AND starts with lowercase
    assert [p.line for p in problems] == [1, 2, 2]
    
    punctuation_problems = [p for p in problems if "punctuation" in p.message]
    assert len(punctuation_problems) == 2
    
    lowercase_problems = [p for p in problems if "uppercase" in p.message]
    assert len(lowercase_problems) == 1
    assert lowercase_problems[0].line == 2

    assert autofix_plain_lyrics("First line.\nsecond line,") == "First line\nSecond line"
