"""Backend-independent quality checks for line-level alignment results."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from .ai_sync_contracts import AlignedLine, AlignmentResult, ManualAnchor


@dataclass(slots=True, frozen=True)
class AlignmentQuality:
    coverage: float
    monotonicity: float
    timeline_score: float
    repeat_score: float
    backend_confidence: float | None
    overall: float
    flags: frozenset[str] = field(default_factory=frozenset)
    minimum_spacing: float = 1.0
    audio_duration_consistency: float = 1.0
    first_timestamp_plausibility: float = 1.0
    last_timestamp_plausibility: float = 1.0
    skipped_lines: int = 0
    repeated_timestamps: int = 0
    large_forward_jumps: int = 0
    line_density: float = 1.0
    manual_anchor_agreement: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "coverage": self.coverage,
            "monotonicity": self.monotonicity,
            "timeline_score": self.timeline_score,
            "repeat_score": self.repeat_score,
            "backend_confidence": self.backend_confidence,
            "overall": self.overall,
            "flags": sorted(self.flags),
            "minimum_spacing": self.minimum_spacing,
            "audio_duration_consistency": self.audio_duration_consistency,
            "first_timestamp_plausibility": self.first_timestamp_plausibility,
            "last_timestamp_plausibility": self.last_timestamp_plausibility,
            "skipped_lines": self.skipped_lines,
            "repeated_timestamps": self.repeated_timestamps,
            "large_forward_jumps": self.large_forward_jumps,
            "line_density": self.line_density,
            "manual_anchor_agreement": self.manual_anchor_agreement,
        }


def validate_alignment(
    result: AlignmentResult,
    *,
    expected_line_count: int,
    audio_duration_seconds: float | None = None,
    manual_anchors: Iterable[ManualAnchor] = (),
    minimum_spacing_seconds: float = 0.05,
    large_gap_seconds: float = 20.0,
    anchor_tolerance_seconds: float = 3.0,
) -> AlignmentQuality:
    """Score alignment health without selecting or rewriting timestamps."""
    lines = list(result.lines)
    expected_count = max(0, int(expected_line_count))
    coverage = min(1.0, len(lines) / expected_count) if expected_count else result.coverage
    skipped_lines = max(0, expected_count - len({line.source_line_index for line in lines}))

    valid_lines = [line for line in lines if math.isfinite(line.start) and line.start >= 0]
    gaps = [
        current.start - previous.start
        for previous, current in zip(valid_lines, valid_lines[1:])
    ]
    monotonic_pairs = sum(gap > 0 for gap in gaps)
    monotonicity = monotonic_pairs / len(gaps) if gaps else 1.0
    repeated_timestamps = sum(abs(gap) < 0.01 for gap in gaps)
    minimum_spacing = (
        sum(gap >= minimum_spacing_seconds for gap in gaps) / len(gaps) if gaps else 1.0
    )
    large_forward_jumps = sum(gap > large_gap_seconds for gap in gaps)

    first_plausibility = _first_timestamp_score(valid_lines)
    last_plausibility = _last_timestamp_score(valid_lines, audio_duration_seconds)
    duration_consistency = _duration_consistency(valid_lines, audio_duration_seconds)
    density = _line_density_score(len(valid_lines), audio_duration_seconds)
    repeat_score = _repeat_order_score(lines)
    anchor_agreement = _manual_anchor_score(lines, manual_anchors, anchor_tolerance_seconds)
    backend_confidence = _backend_confidence(result, lines)

    timeline_score = (
        monotonicity * 0.30
        + minimum_spacing * 0.15
        + duration_consistency * 0.25
        + first_plausibility * 0.10
        + last_plausibility * 0.10
        + density * 0.10
    )
    structural_score = repeat_score
    overall = (
        coverage * 0.30
        + monotonicity * 0.15
        + timeline_score * 0.25
        + structural_score * 0.15
        + (backend_confidence if backend_confidence is not None else 0.5) * 0.10
        + (anchor_agreement if anchor_agreement is not None else 1.0) * 0.05
    )

    flags: set[str] = set()
    if coverage < 0.90:
        flags.add("LOW_COVERAGE")
    if monotonicity < 0.98:
        flags.add("NON_MONOTONIC")
    if repeated_timestamps:
        flags.add("REPEATED_TIMESTAMP_CLUSTER")
    if large_forward_jumps:
        flags.add("LARGE_FORWARD_JUMP")
    if duration_consistency < 0.75:
        flags.add("AUDIO_DURATION_MISMATCH")
    if first_plausibility < 0.75:
        flags.add("FIRST_TIMESTAMP_OUT_OF_RANGE")
    if last_plausibility < 0.75:
        flags.add("TAIL_OUT_OF_RANGE")
    if density < 0.50:
        flags.add("SPARSE_TIMELINE")
    if repeat_score < 0.75:
        flags.add("REPEATED_BLOCK_ORDERING")
    if anchor_agreement is not None and anchor_agreement < 0.75:
        flags.add("MANUAL_ANCHOR_MISMATCH")

    return AlignmentQuality(
        coverage=_clamp(coverage),
        monotonicity=_clamp(monotonicity),
        timeline_score=_clamp(timeline_score),
        repeat_score=_clamp(repeat_score),
        backend_confidence=backend_confidence,
        overall=_clamp(overall),
        flags=frozenset(flags),
        minimum_spacing=_clamp(minimum_spacing),
        audio_duration_consistency=_clamp(duration_consistency),
        first_timestamp_plausibility=_clamp(first_plausibility),
        last_timestamp_plausibility=_clamp(last_plausibility),
        skipped_lines=skipped_lines,
        repeated_timestamps=repeated_timestamps,
        large_forward_jumps=large_forward_jumps,
        line_density=_clamp(density),
        manual_anchor_agreement=anchor_agreement,
    )


def _first_timestamp_score(lines: list[AlignedLine]) -> float:
    if not lines:
        return 0.0
    return 1.0 if 0.0 <= lines[0].start <= 30.0 else 0.0


def _last_timestamp_score(lines: list[AlignedLine], duration_seconds: float | None) -> float:
    if not lines or duration_seconds is None or duration_seconds <= 0:
        return 1.0
    last = lines[-1].start
    return 1.0 if 0.0 <= last <= duration_seconds + 5.0 else 0.0


def _duration_consistency(lines: list[AlignedLine], duration_seconds: float | None) -> float:
    if not lines or duration_seconds is None or duration_seconds <= 0:
        return 1.0
    last = lines[-1].start
    if last <= duration_seconds:
        return 1.0
    overflow = last - duration_seconds
    return max(0.0, 1.0 - overflow / max(1.0, duration_seconds))


def _line_density_score(line_count: int, duration_seconds: float | None) -> float:
    if duration_seconds is None or duration_seconds <= 0:
        return 1.0
    density = line_count / duration_seconds
    # This is a warning signal, not a quality gate: songs can contain long
    # instrumental sections and very dense rap/speech sections.
    if 0.02 <= density <= 4.0:
        return 1.0
    if density < 0.02:
        return max(0.0, density / 0.02)
    return max(0.0, 1.0 - (density - 4.0) / 8.0)


def _repeat_order_score(lines: list[AlignedLine]) -> float:
    if len(lines) < 2:
        return 1.0
    increasing = sum(
        current.source_line_index > previous.source_line_index
        for previous, current in zip(lines, lines[1:])
    )
    return increasing / (len(lines) - 1)


def _backend_confidence(result: AlignmentResult, lines: list[AlignedLine]) -> float | None:
    values = [line.confidence for line in lines if line.confidence is not None]
    if values:
        return _clamp(sum(values) / len(values))
    if 0.0 <= result.confidence <= 1.0:
        return result.confidence
    return None


def _manual_anchor_score(
    lines: list[AlignedLine],
    anchors: Iterable[ManualAnchor],
    tolerance_seconds: float,
) -> float | None:
    anchor_list = list(anchors)
    if not anchor_list:
        return None
    by_index = {line.source_line_index: line for line in lines}
    scores: list[float] = []
    for anchor in anchor_list:
        line = by_index.get(anchor.line_index)
        if line is None:
            scores.append(0.0)
            continue
        error = abs(line.start - anchor.time_ms / 1000.0)
        scores.append(max(0.0, 1.0 - error / max(0.01, tolerance_seconds)))
    return sum(scores) / len(scores) if scores else None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = ["AlignmentQuality", "validate_alignment"]
