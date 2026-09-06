"""Bounded structural sequence selection for known-lyrics alignment."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .ai_sync_contracts import ManualAnchor


@dataclass(slots=True)
class LineCandidate:
    line_index: int
    start: float
    end: float | None
    acoustic_score: float
    text_score: float | None
    source_backend: str
    region_id: int | None
    flags: set[str] = field(default_factory=set)

    def score(self) -> float:
        acoustic = _normalize_score(self.acoustic_score)
        text = _normalize_score(self.text_score) if self.text_score is not None else 0.5
        return acoustic * 0.65 + text * 0.35 - len(self.flags) * 0.03

    def to_dict(self) -> dict[str, object]:
        return {
            "line_index": self.line_index,
            "start": self.start,
            "end": self.end,
            "acoustic_score": self.acoustic_score,
            "text_score": self.text_score,
            "source_backend": self.source_backend,
            "region_id": self.region_id,
            "flags": sorted(self.flags),
        }


def select_structural_candidates(
    candidates_by_line: Mapping[int, Sequence[LineCandidate]],
    *,
    expected_line_count: int,
    audio_duration_seconds: float | None = None,
    max_candidates_per_line: int = 5,
    manual_anchors: Iterable[ManualAnchor] = (),
    hard_manual_anchors: bool = False,
    manual_anchor_tolerance_seconds: float = 3.0,
) -> list[LineCandidate] | None:
    """Select a bounded monotone candidate path using structural evidence."""
    count = max(0, int(expected_line_count))
    if count == 0:
        return []
    limit = max(1, min(5, int(max_candidates_per_line)))
    anchors = {anchor.line_index: anchor for anchor in manual_anchors}
    layers: list[list[LineCandidate]] = []
    for line_index in range(count):
        layer = [
            candidate
            for candidate in candidates_by_line.get(line_index, ())
            if candidate.line_index == line_index and candidate.start >= 0
        ]
        if hard_manual_anchors and line_index in anchors:
            anchor = anchors[line_index]
            layer = [
                candidate
                for candidate in layer
                if abs(candidate.start - anchor.time_ms / 1000.0)
                <= max(0.01, manual_anchor_tolerance_seconds)
            ]
        layer.sort(key=lambda candidate: candidate.score(), reverse=True)
        layer = layer[:limit]
        if not layer:
            return None
        layers.append(layer)

    scores: list[dict[int, float]] = []
    predecessors: list[dict[int, int | None]] = []
    for line_index, layer in enumerate(layers):
        layer_scores: dict[int, float] = {}
        layer_predecessors: dict[int, int | None] = {}
        for candidate_index, candidate in enumerate(layer):
            own_score = candidate.score()
            own_score += _manual_anchor_score(
                candidate,
                anchors.get(candidate.line_index),
                tolerance_seconds=manual_anchor_tolerance_seconds,
            )
            if line_index == 0:
                layer_scores[candidate_index] = own_score + _relative_position_score(
                    candidate, line_index, count, audio_duration_seconds
                )
                layer_predecessors[candidate_index] = None
                continue
            best_score = float("-inf")
            best_previous: int | None = None
            for previous_index, previous in enumerate(layers[line_index - 1]):
                if previous_index not in scores[-1]:
                    continue
                transition = _transition_score(
                    previous,
                    candidate,
                    line_index=line_index,
                    line_count=count,
                    audio_duration_seconds=audio_duration_seconds,
                )
                if transition is None:
                    continue
                total = scores[-1][previous_index] + transition + own_score
                if total > best_score:
                    best_score = total
                    best_previous = previous_index
            if best_previous is not None:
                layer_scores[candidate_index] = best_score
                layer_predecessors[candidate_index] = best_previous
        if not layer_scores:
            return None
        scores.append(layer_scores)
        predecessors.append(layer_predecessors)

    current_index = max(scores[-1], key=scores[-1].get)
    selected: list[LineCandidate] = []
    for line_index in range(count - 1, -1, -1):
        selected.append(layers[line_index][current_index])
        previous_index = predecessors[line_index][current_index]
        if previous_index is None:
            break
        current_index = previous_index
    selected.reverse()
    return selected if len(selected) == count else None


def _transition_score(
    previous: LineCandidate,
    current: LineCandidate,
    *,
    line_index: int,
    line_count: int,
    audio_duration_seconds: float | None,
) -> float | None:
    gap = current.start - previous.start
    if gap <= 0:
        return None
    score = 0.0
    if gap < 0.05:
        score -= 2.0
    if gap > 20.0:
        score -= min(2.0, (gap - 20.0) / 30.0)
    if current.end is not None and current.end < current.start:
        score -= 2.0
    score += _relative_position_score(current, line_index, line_count, audio_duration_seconds)
    if "TIMESTAMP_COLLAPSE" in current.flags:
        score -= 1.0
    if "BACKWARD_JUMP" in current.flags:
        score -= 2.0
    return score


def _relative_position_score(
    candidate: LineCandidate,
    line_index: int,
    line_count: int,
    audio_duration_seconds: float | None,
) -> float:
    if audio_duration_seconds is None or audio_duration_seconds <= 0 or line_count <= 1:
        return 0.0
    expected = float(audio_duration_seconds) * line_index / (line_count - 1)
    distance = abs(candidate.start - expected) / float(audio_duration_seconds)
    return max(-0.75, 0.25 - distance)


def _normalize_score(value: float | None) -> float:
    if value is None:
        return 0.5
    numeric = float(value)
    if numeric > 1.0:
        numeric /= 100.0
    return max(0.0, min(1.0, numeric))


def _manual_anchor_score(
    candidate: LineCandidate,
    anchor: ManualAnchor | None,
    *,
    tolerance_seconds: float,
) -> float:
    if anchor is None:
        return 0.0
    distance = abs(candidate.start - anchor.time_ms / 1000.0)
    return max(-2.0, 0.75 - distance / max(0.01, tolerance_seconds))


__all__ = ["LineCandidate", "select_structural_candidates"]
