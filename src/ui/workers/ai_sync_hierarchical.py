"""Bounded candidate-region generation for hierarchical alignment experiments."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


@dataclass(slots=True, frozen=True)
class AcousticRegion:
    region_id: int
    start: float
    end: float
    score: float
    source: str = "acoustic"


@dataclass(slots=True, frozen=True)
class CandidateRegion:
    line_index: int
    region_id: int
    start: float
    end: float
    score: float
    source: str
    flags: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict[str, object]:
        return {
            "line_index": self.line_index,
            "region_id": self.region_id,
            "start": self.start,
            "end": self.end,
            "score": self.score,
            "source": self.source,
            "flags": sorted(self.flags),
        }


def build_candidate_regions(
    *,
    line_count: int,
    audio_duration_seconds: float,
    evidence_regions: Iterable[AcousticRegion] = (),
    line_confidence: Sequence[float] | None = None,
    max_candidates: int = 3,
) -> dict[int, list[CandidateRegion]]:
    """Create bounded line windows from coarse evidence.

    VAD/activity is treated as a hint.  Every line receives a fallback
    position window, so weak or missing acoustic evidence cannot delete lyric
    content before a downstream sequence selector sees it.
    """
    total_lines = max(0, int(line_count))
    duration = max(0.1, float(audio_duration_seconds))
    limit = max(1, min(5, int(max_candidates)))
    regions = [
        region
        for region in evidence_regions
        if region.end > region.start and region.start >= 0
    ]
    result: dict[int, list[CandidateRegion]] = {}
    for line_index in range(total_lines):
        expected = duration * (line_index + 0.5) / max(1, total_lines)
        confidence = (
            float(line_confidence[line_index])
            if line_confidence is not None and line_index < len(line_confidence)
            else 0.5
        )
        candidates: list[CandidateRegion] = []
        for region in regions:
            distance = abs((region.start + region.end) / 2.0 - expected)
            proximity = max(0.0, 1.0 - distance / duration)
            if distance <= max(duration / max(1, total_lines) * 2.5, 4.0):
                candidates.append(
                    CandidateRegion(
                        line_index=line_index,
                        region_id=region.region_id,
                        start=region.start,
                        end=region.end,
                        score=max(0.0, region.score) * 0.7 + proximity * 0.3,
                        source=region.source,
                        flags=frozenset({"EVIDENCE"}),
                    )
                )

        window = max(1.0, duration / max(1, total_lines) * 0.75)
        candidates.append(
            CandidateRegion(
                line_index=line_index,
                region_id=-1,
                start=max(0.0, expected - window),
                end=min(duration, expected + window),
                score=max(0.0, 0.45 + confidence * 0.35),
                source="relative-position",
                flags=frozenset({"FALLBACK"}),
            )
        )
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        line_limit = 1 if confidence >= 0.8 else limit
        result[line_index] = _deduplicate_regions(candidates)[:line_limit]
    return result


def _deduplicate_regions(candidates: list[CandidateRegion]) -> list[CandidateRegion]:
    seen: set[tuple[float, float]] = set()
    unique: list[CandidateRegion] = []
    for candidate in candidates:
        key = (round(candidate.start, 3), round(candidate.end, 3))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


__all__ = ["AcousticRegion", "CandidateRegion", "build_candidate_regions"]
