from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_hierarchical import AcousticRegion, build_candidate_regions


def test_hierarchical_regions_always_keep_a_fallback_window() -> None:
    result = build_candidate_regions(line_count=3, audio_duration_seconds=30)

    assert set(result) == {0, 1, 2}
    assert all(candidates for candidates in result.values())
    assert all(candidate.source == "relative-position" for candidate in result[0])


def test_hierarchical_regions_keep_multiple_candidates_for_ambiguous_lines() -> None:
    result = build_candidate_regions(
        line_count=2,
        audio_duration_seconds=20,
        evidence_regions=[
            AcousticRegion(1, 1, 4, 0.95),
            AcousticRegion(2, 3, 7, 0.85),
        ],
        line_confidence=[0.4, 0.9],
        max_candidates=3,
    )

    assert len(result[0]) >= 2
    assert len(result[1]) == 1
    assert "EVIDENCE" in result[0][0].flags


def test_hierarchical_candidate_count_is_bounded() -> None:
    regions = [AcousticRegion(index, index, index + 1, 1.0) for index in range(20)]

    result = build_candidate_regions(
        line_count=2,
        audio_duration_seconds=20,
        evidence_regions=regions,
        max_candidates=99,
    )

    assert all(len(candidates) <= 5 for candidates in result.values())
