"""Research backend manifests and promotion gates for AI sync experiments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(slots=True, frozen=True)
class ResearchBackendSpec:
    name: str
    repository: str
    code_license: str
    languages: tuple[str, ...]
    requires_vocal_stem: bool
    production_default: bool = False
    model_license: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "repository": self.repository,
            "code_license": self.code_license,
            "languages": list(self.languages),
            "requires_vocal_stem": self.requires_vocal_stem,
            "production_default": self.production_default,
            "model_license": self.model_license,
            "notes": self.notes,
        }


@dataclass(slots=True, frozen=True)
class ResearchRecommendation:
    decision: str
    reason: str
    coverage: float
    p95_seconds: float | None
    catastrophic_count: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "coverage": self.coverage,
            "p95_seconds": self.p95_seconds,
            "catastrophic_count": self.catastrophic_count,
        }


LYRICS_ALIGNMENT_MULTILINGUAL = ResearchBackendSpec(
    name="lyrics-alignment-multilingual",
    repository="https://github.com/jhuang448/LyricsAlignment-Multilingual",
    code_license="MIT",
    languages=("en", "fr", "de", "it", "es"),
    requires_vocal_stem=True,
    production_default=False,
    notes="Research candidate; evaluate raw mix and separated vocals independently.",
)


def evaluate_research_candidate(
    metrics: Mapping[str, float | int | None],
    *,
    legacy_p95_seconds: float,
    legacy_coverage: float,
    legacy_catastrophic_count: int,
) -> ResearchRecommendation:
    """Apply the plan's conservative production gate to one language result."""
    coverage = float(metrics.get("coverage") or 0.0)
    p95 = metrics.get("p95_seconds")
    p95_value = float(p95) if isinstance(p95, (int, float)) else None
    catastrophic = metrics.get("catastrophic_count")
    catastrophic_value = int(catastrophic) if isinstance(catastrophic, (int, float)) else None
    if coverage < 0.95:
        return ResearchRecommendation(
            "drop",
            "coverage is below the 95% production floor",
            coverage,
            p95_value,
            catastrophic_value,
        )
    if p95_value is None:
        return ResearchRecommendation(
            "keep experimental",
            "p95 evidence is missing",
            coverage,
            None,
            catastrophic_value,
        )
    p95_improvement = (
        (legacy_p95_seconds - p95_value) / legacy_p95_seconds
        if legacy_p95_seconds > 0
        else 0.0
    )
    catastrophic_improvement = (
        catastrophic_value is not None
        and catastrophic_value < legacy_catastrophic_count
    )
    if p95_improvement >= 0.30 or catastrophic_improvement:
        return ResearchRecommendation(
            "keep experimental",
            "passes the research benefit gate; production default still needs packaging and parity checks",
            coverage,
            p95_value,
            catastrophic_value,
        )
    return ResearchRecommendation(
        "drop",
        "does not materially beat the legacy p95 or catastrophic-error count",
        coverage,
        p95_value,
        catastrophic_value,
    )


__all__ = [
    "LYRICS_ALIGNMENT_MULTILINGUAL",
    "ResearchBackendSpec",
    "ResearchRecommendation",
    "evaluate_research_candidate",
]
