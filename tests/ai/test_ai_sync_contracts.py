from __future__ import annotations

import pytest

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_contracts import (
    AlignedLine,
    AlignmentOptions,
    AlignmentRequest,
    AlignmentResult,
    ManualAnchor,
    manual_anchors_from_mappings,
)


def test_alignment_request_round_trips_through_json_shape() -> None:
    request = AlignmentRequest(
        job_id="job-1",
        audio_path="C:/music/song.flac",
        plain_lyrics="one\ntwo",
        requested_language="en",
        manual_anchors=[ManualAnchor(line_index=1, time_ms=2400)],
        device="cpu",
        options=AlignmentOptions(
            whisper_model="small",
            enable_demucs_candidate=False,
            extras={"experiment": "baseline"},
        ),
    )

    restored = AlignmentRequest.from_mapping(request.to_dict())

    assert restored.to_dict() == request.to_dict()


def test_alignment_options_keep_unknown_experiment_flags() -> None:
    options = AlignmentOptions.from_mapping(
        {"whisper_model": "base", "new_flag": 98, "enable_fuzzy": False}
    )

    assert options.enable_fuzzy is False
    assert options.extras == {"new_flag": 98}
    assert options.to_dict()["new_flag"] == 98


def test_alignment_result_validates_and_serializes_to_lrc() -> None:
    result = AlignmentResult(
        lines=[
            AlignedLine(0, "One", 1.25, 2.0, 0.9, "fixture"),
            AlignedLine(1, "Two", 3.5, None, None, "fixture"),
        ],
        language="en",
        backend="fixture",
        coverage=1.0,
        confidence=0.9,
        structural_score=0.8,
        runtime_ms=12.5,
    )

    assert result.validation_errors() == []
    assert result.to_lrc() == "[00:01.25] One\n[00:03.50] Two"
    assert AlignmentResult.from_mapping(result.to_dict()).to_dict() == result.to_dict()


def test_alignment_result_rejects_nonmonotonic_lines_before_lrc_serialization() -> None:
    result = AlignmentResult(
        lines=[
            AlignedLine(0, "One", 2.0, None, None, "fixture"),
            AlignedLine(1, "Two", 1.0, None, None, "fixture"),
        ],
        language="en",
        backend="fixture",
        coverage=1.0,
        confidence=1.0,
        structural_score=1.0,
        runtime_ms=1.0,
    )

    assert result.validation_errors() == ["line 1 is not strictly after the previous line"]
    with pytest.raises(ValueError, match="invalid alignment result"):
        result.to_lrc()


def test_legacy_manual_anchor_conversion_ignores_invalid_values() -> None:
    anchors = manual_anchors_from_mappings(
        [
            {"line_index": 0, "time_ms": 1000},
            {"line_index": "bad", "time_ms": 2000},
            {"line_index": 2},
        ]
    )

    assert anchors == [ManualAnchor(line_index=0, time_ms=1000)]
