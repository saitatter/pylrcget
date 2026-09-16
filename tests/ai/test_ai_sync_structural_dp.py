from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_contracts import ManualAnchor
from ui.workers.ai_sync_structural_dp import LineCandidate, select_structural_candidates


def _candidate(line, start, score, *, flags=None):
    return LineCandidate(
        line_index=line,
        start=start,
        end=start + 1,
        acoustic_score=score,
        text_score=score,
        source_backend="fixture",
        region_id=line,
        flags=set(flags or ()),
    )


def test_structural_dp_prefers_monotonic_path_over_independent_local_maxima() -> None:
    result = select_structural_candidates(
        {
            0: [_candidate(0, 1.0, 0.9), _candidate(0, 5.0, 0.7)],
            1: [_candidate(1, 1.0, 1.0), _candidate(1, 6.0, 0.8)],
            2: [_candidate(2, 2.0, 0.95), _candidate(2, 9.0, 0.85)],
        },
        expected_line_count=3,
        audio_duration_seconds=12,
    )

    assert result is not None
    assert [candidate.start for candidate in result] == [1.0, 6.0, 9.0]


def test_structural_dp_returns_none_when_a_line_has_no_candidates() -> None:
    result = select_structural_candidates(
        {0: [_candidate(0, 1.0, 1.0)], 1: []},
        expected_line_count=2,
    )

    assert result is None


def test_structural_dp_bounds_candidate_layers() -> None:
    candidates = [_candidate(0, float(index + 1), 0.5) for index in range(20)]
    result = select_structural_candidates(
        {0: candidates, 1: [_candidate(1, 30.0, 1.0)]},
        expected_line_count=2,
        max_candidates_per_line=99,
    )

    assert result is not None
    assert len(result) == 2


def test_structural_dp_handles_empty_song() -> None:
    assert select_structural_candidates({}, expected_line_count=0) == []


def test_structural_dp_soft_manual_anchor_prefers_nearby_candidate() -> None:
    result = select_structural_candidates(
        {
            0: [_candidate(0, 1.0, 0.95), _candidate(0, 8.0, 0.7)],
            1: [_candidate(1, 10.0, 0.8)],
        },
        expected_line_count=2,
        audio_duration_seconds=12,
        manual_anchors=[ManualAnchor(line_index=0, time_ms=8000)],
    )

    assert result is not None
    assert result[0].start == 8.0


def test_structural_dp_hard_manual_anchor_can_reject_missing_window() -> None:
    result = select_structural_candidates(
        {0: [_candidate(0, 1.0, 1.0)]},
        expected_line_count=1,
        manual_anchors=[ManualAnchor(line_index=0, time_ms=8000)],
        hard_manual_anchors=True,
    )

    assert result is None
