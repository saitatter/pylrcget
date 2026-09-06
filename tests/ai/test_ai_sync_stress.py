from __future__ import annotations

import pytest

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_contracts import AlignedLine, AlignmentResult
from ui.workers.ai_sync_hierarchical import AcousticRegion, build_candidate_regions
from ui.workers.ai_sync_language import detect_text_language
from ui.workers.ai_sync_structural_dp import LineCandidate, select_structural_candidates
from ui.workers.ai_sync_validator import validate_alignment


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("The night is young\nAnd the road is open", "en"),
        ("Șoapta rămâne în aer\nMâine începe aici", "ro"),
        ("La nuit est longue\nEt la route est ouverte", "fr"),
        ("La noche está viva\nY el camino se abre", "es"),
    ],
)
def test_text_first_language_detection_handles_multilingual_known_lyrics(text, language) -> None:
    result = detect_text_language(text)

    assert result.language == language
    assert result.confidence >= 0.70


def test_structural_dp_stays_bounded_and_monotone_for_repeated_chorus_candidates() -> None:
    candidates = {}
    for line_index in range(60):
        expected = line_index * 4.0
        candidates[line_index] = [
            LineCandidate(
                line_index=line_index,
                start=expected + offset,
                end=expected + offset + 1.0,
                acoustic_score=0.9 - abs(offset) * 0.1,
                text_score=0.9,
                source_backend="stress-fixture",
                region_id=line_index,
            )
            for offset in (-1.5, 0.0, 1.5, 40.0, 80.0, 120.0, 160.0)
        ]

    selected = select_structural_candidates(
        candidates,
        expected_line_count=60,
        audio_duration_seconds=240.0,
        max_candidates_per_line=99,
    )

    assert selected is not None
    assert len(selected) == 60
    assert all(
        current.start > previous.start
        for previous, current in zip(selected, selected[1:])
    )
    assert all(abs(candidate.start - index * 4.0) <= 1.5 for index, candidate in enumerate(selected))


def test_hierarchical_regions_keep_fallbacks_when_repeated_evidence_is_sparse() -> None:
    evidence = [
        AcousticRegion(region_id=0, start=10.0, end=14.0, score=0.9),
        AcousticRegion(region_id=1, start=110.0, end=114.0, score=0.8),
    ]

    result = build_candidate_regions(
        line_count=80,
        audio_duration_seconds=320.0,
        evidence_regions=evidence,
        line_confidence=[0.2] * 80,
        max_candidates=99,
    )

    assert set(result) == set(range(80))
    assert all(1 <= len(candidates) <= 5 for candidates in result.values())
    assert all(any("FALLBACK" in candidate.flags for candidate in candidates) for candidates in result.values())


def test_validator_exposes_repeated_and_tail_collapse_flags() -> None:
    lines = [
        AlignedLine(index, f"line {index}", 5.0 + index * 0.01, None, 0.5, "stress")
        for index in range(8)
    ]
    lines.extend(
        [
            AlignedLine(8, "chorus", 5.05, None, 0.5, "stress"),
            AlignedLine(9, "tail", 220.0, None, 0.5, "stress"),
        ]
    )
    result = AlignmentResult(
        lines=lines,
        language="ro",
        backend="stress",
        coverage=1.0,
        confidence=0.5,
        structural_score=0.5,
        runtime_ms=1.0,
    )

    quality = validate_alignment(
        result,
        expected_line_count=10,
        audio_duration_seconds=180.0,
    )

    assert "REPEATED_TIMESTAMP_CLUSTER" in quality.flags
    assert "LARGE_FORWARD_JUMP" in quality.flags
    assert "TAIL_OUT_OF_RANGE" in quality.flags
