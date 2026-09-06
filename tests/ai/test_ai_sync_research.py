from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_research import (
    LYRICS_ALIGNMENT_MULTILINGUAL,
    SOFA_RESEARCH,
    evaluate_research_candidate,
)


def test_multilingual_candidate_is_research_only_and_vocal_aware() -> None:
    assert LYRICS_ALIGNMENT_MULTILINGUAL.production_default is False
    assert LYRICS_ALIGNMENT_MULTILINGUAL.requires_vocal_stem is True
    assert "ro" not in LYRICS_ALIGNMENT_MULTILINGUAL.languages


def test_sofa_manifest_keeps_legacy_runtime_and_model_gates_visible() -> None:
    assert SOFA_RESEARCH.production_default is False
    assert SOFA_RESEARCH.runtime == "isolated-py3.8"
    assert SOFA_RESEARCH.inference_modes == ("pytorch", "onnx-cpu", "onnx-gpu")
    assert SOFA_RESEARCH.requires_g2p is True
    assert SOFA_RESEARCH.model_license == "unknown"
    assert "checkpoint.ckpt" in SOFA_RESEARCH.model_artifacts


def test_research_gate_requires_coverage() -> None:
    result = evaluate_research_candidate(
        {"coverage": 0.94, "p95_seconds": 1.0, "catastrophic_count": 0},
        legacy_p95_seconds=10.0,
        legacy_coverage=0.99,
        legacy_catastrophic_count=5,
    )

    assert result.decision == "drop"
    assert "coverage" in result.reason


def test_research_gate_keeps_clear_p95_win_experimental() -> None:
    result = evaluate_research_candidate(
        {"coverage": 0.98, "p95_seconds": 6.0, "catastrophic_count": 4},
        legacy_p95_seconds=10.0,
        legacy_coverage=0.99,
        legacy_catastrophic_count=5,
    )

    assert result.decision == "keep experimental"


def test_research_gate_drops_neutral_result() -> None:
    result = evaluate_research_candidate(
        {"coverage": 0.98, "p95_seconds": 9.9, "catastrophic_count": 5},
        legacy_p95_seconds=10.0,
        legacy_coverage=0.99,
        legacy_catastrophic_count=5,
    )

    assert result.decision == "drop"
