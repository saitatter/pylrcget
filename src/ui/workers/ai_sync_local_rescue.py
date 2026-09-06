"""Bounded local Whisper rescue helpers for low-confidence regions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(slots=True, frozen=True)
class RescueWindow:
    start: float
    end: float
    reason: str = "low-confidence"


def build_rescue_windows(
    windows: Iterable[tuple[float, float]],
    *,
    audio_duration_seconds: float,
    context_seconds: float = 3.0,
    max_windows: int = 3,
) -> list[RescueWindow]:
    duration = max(0.1, float(audio_duration_seconds))
    expanded = [
        RescueWindow(
            max(0.0, float(start) - max(0.0, context_seconds)),
            min(duration, float(end) + max(0.0, context_seconds)),
        )
        for start, end in windows
        if float(end) > float(start)
    ]
    expanded.sort(key=lambda window: (window.start, window.end))
    merged: list[RescueWindow] = []
    for window in expanded:
        if merged and window.start <= merged[-1].end:
            previous = merged[-1]
            merged[-1] = RescueWindow(previous.start, max(previous.end, window.end))
        else:
            merged.append(window)
    return merged[: max(1, min(8, int(max_windows)))]


def transcribe_local_rescue(
    model: Any,
    audio: Any,
    windows: Iterable[RescueWindow],
    *,
    language: str | None,
    sample_rate: int = 16_000,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Transcribe only bounded audio windows and restore absolute timestamps."""
    result: list[dict[str, Any]] = []
    total_samples = len(audio) if hasattr(audio, "__len__") else 0
    for window in windows:
        if is_cancelled is not None and is_cancelled():
            break
        start_sample = max(0, int(window.start * sample_rate))
        end_sample = min(total_samples, int(window.end * sample_rate))
        if end_sample <= start_sample:
            continue
        local_audio = audio[start_sample:end_sample]
        kwargs = {"language": language} if language else {}
        transcription = model.transcribe(local_audio, **kwargs)
        for raw_segment in transcription.get("segments", []):
            segment = dict(raw_segment)
            if segment.get("start") is not None:
                segment["start"] = float(segment["start"]) + window.start
            if segment.get("end") is not None:
                segment["end"] = float(segment["end"]) + window.start
            result.append(segment)
    result.sort(key=lambda segment: float(segment.get("start", 0.0)))
    return result


def replace_segments_in_windows(
    segments: Iterable[dict[str, Any]],
    rescued_segments: Iterable[dict[str, Any]],
    windows: Iterable[RescueWindow],
) -> list[dict[str, Any]]:
    """Replace only the suspicious time regions and retain other ASR output."""
    source = [dict(segment) for segment in segments]
    rescued = [dict(segment) for segment in rescued_segments]
    for window in windows:
        source = [
            segment
            for segment in source
            if float(segment.get("end", segment.get("start", 0.0))) <= window.start
            or float(segment.get("start", 0.0)) >= window.end
        ]
    combined = source + rescued
    combined.sort(key=lambda segment: float(segment.get("start", 0.0)))
    return combined


__all__ = [
    "RescueWindow",
    "build_rescue_windows",
    "replace_segments_in_windows",
    "transcribe_local_rescue",
]
