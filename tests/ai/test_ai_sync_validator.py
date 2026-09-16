from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_contracts import AlignedLine, AlignmentResult, ManualAnchor
from ui.workers.ai_sync_validator import validate_alignment


def _result(lines, confidence=0.9):
    return AlignmentResult(
        lines=lines,
        language="en",
        backend="fixture",
        coverage=1.0,
        confidence=confidence,
        structural_score=0.9,
        runtime_ms=10,
    )


def test_validator_accepts_monotonic_result_with_good_duration() -> None:
    quality = validate_alignment(
        _result(
            [
                AlignedLine(0, "one", 1.0, None, 0.9, "fixture"),
                AlignedLine(1, "two", 4.0, None, 0.8, "fixture"),
                AlignedLine(2, "three", 7.0, None, 0.9, "fixture"),
            ]
        ),
        expected_line_count=3,
        audio_duration_seconds=10,
    )

    assert quality.coverage == 1.0
    assert quality.monotonicity == 1.0
    assert quality.repeated_timestamps == 0
    assert quality.flags == frozenset()
    assert quality.overall > 0.8


def test_validator_flags_missing_lines_repeated_timestamps_and_large_jump() -> None:
    quality = validate_alignment(
        _result(
            [
                AlignedLine(0, "one", 1.0, None, None, "fixture"),
                AlignedLine(2, "three", 1.0, None, None, "fixture"),
                AlignedLine(3, "four", 25.0, None, None, "fixture"),
            ]
        ),
        expected_line_count=4,
        audio_duration_seconds=20,
    )

    assert quality.coverage == 0.75
    assert quality.skipped_lines == 1
    assert quality.repeated_timestamps == 1
    assert quality.large_forward_jumps == 1
    assert {"LOW_COVERAGE", "REPEATED_TIMESTAMP_CLUSTER", "LARGE_FORWARD_JUMP"} <= quality.flags


def test_validator_checks_manual_anchor_agreement() -> None:
    quality = validate_alignment(
        _result([AlignedLine(0, "one", 10.0, None, 1.0, "fixture")]),
        expected_line_count=1,
        audio_duration_seconds=12,
        manual_anchors=[ManualAnchor(line_index=0, time_ms=1000)],
    )

    assert quality.manual_anchor_agreement == 0.0
    assert "MANUAL_ANCHOR_MISMATCH" in quality.flags


def test_validator_exposes_json_safe_flags() -> None:
    quality = validate_alignment(_result([]), expected_line_count=1)

    payload = quality.to_dict()
    assert isinstance(payload["flags"], list)
    assert payload["coverage"] == 0.0
