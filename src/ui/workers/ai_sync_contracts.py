"""Backend-independent data contracts for AI lyrics alignment.

The Qt worker and the optional external runtime exchange plain dictionaries,
but backends operate on these typed objects.  Keeping the conversion here
prevents each backend from inventing a slightly different result shape.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(slots=True, frozen=True)
class ManualAnchor:
    line_index: int
    time_ms: int

    def to_dict(self) -> dict[str, int]:
        return {"line_index": self.line_index, "time_ms": self.time_ms}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ManualAnchor":
        return cls(line_index=int(value["line_index"]), time_ms=int(value["time_ms"]))


@dataclass(slots=True)
class AlignmentOptions:
    """Options shared by current and experimental alignment backends."""

    whisper_model: str = "base"
    enable_fuzzy: bool = True
    fuzzy_threshold: int = 60
    fuzzy_window_words: int = 12
    enable_demucs_candidate: bool = True
    allow_legacy_fallback: bool = True
    extras: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "whisper_model": self.whisper_model,
            "enable_fuzzy": self.enable_fuzzy,
            "fuzzy_threshold": self.fuzzy_threshold,
            "fuzzy_window_words": self.fuzzy_window_words,
            "enable_demucs_candidate": self.enable_demucs_candidate,
            "allow_legacy_fallback": self.allow_legacy_fallback,
        }
        result.update(self.extras)
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "AlignmentOptions":
        raw = dict(value or {})
        nested_extras = raw.pop("extras", {})
        extras = dict(nested_extras) if isinstance(nested_extras, Mapping) else {}
        known = {
            "whisper_model",
            "enable_fuzzy",
            "fuzzy_threshold",
            "fuzzy_window_words",
            "enable_demucs_candidate",
            "allow_legacy_fallback",
        }
        return cls(
            whisper_model=str(raw.get("whisper_model") or "base"),
            enable_fuzzy=bool(raw.get("enable_fuzzy", True)),
            fuzzy_threshold=int(raw.get("fuzzy_threshold", 60)),
            fuzzy_window_words=int(raw.get("fuzzy_window_words", 12)),
            enable_demucs_candidate=bool(raw.get("enable_demucs_candidate", True)),
            allow_legacy_fallback=bool(raw.get("allow_legacy_fallback", True)),
            extras={
                **extras,
                **{key: item for key, item in raw.items() if key not in known},
            },
        )


@dataclass(slots=True)
class AlignmentRequest:
    job_id: str
    audio_path: str
    plain_lyrics: str
    requested_language: str | None
    manual_anchors: list[ManualAnchor]
    device: str
    options: AlignmentOptions

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "audio_path": self.audio_path,
            "plain_lyrics": self.plain_lyrics,
            "requested_language": self.requested_language,
            "manual_anchors": [anchor.to_dict() for anchor in self.manual_anchors],
            "device": self.device,
            "options": self.options.to_dict(),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AlignmentRequest":
        anchors = [
            ManualAnchor.from_mapping(anchor)
            for anchor in value.get("manual_anchors", [])
            if isinstance(anchor, Mapping)
        ]
        requested_language = value.get("requested_language")
        return cls(
            job_id=str(value.get("job_id") or ""),
            audio_path=str(value["audio_path"]),
            plain_lyrics=str(value.get("plain_lyrics") or ""),
            requested_language=(
                str(requested_language) if requested_language is not None else None
            ),
            manual_anchors=anchors,
            device=str(value.get("device") or "auto"),
            options=AlignmentOptions.from_mapping(value.get("options")),
        )


@dataclass(slots=True)
class AlignedLine:
    source_line_index: int
    text: str
    start: float
    end: float | None
    confidence: float | None
    backend: str
    evidence: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AlignedLine":
        confidence = value.get("confidence")
        end = value.get("end")
        return cls(
            source_line_index=int(value["source_line_index"]),
            text=str(value.get("text") or ""),
            start=float(value["start"]),
            end=float(end) if end is not None else None,
            confidence=float(confidence) if confidence is not None else None,
            backend=str(value.get("backend") or "unknown"),
            evidence=dict(value.get("evidence") or {}),
        )


@dataclass(slots=True)
class AlignmentResult:
    lines: list[AlignedLine]
    language: str
    backend: str
    coverage: float
    confidence: float
    structural_score: float
    runtime_ms: float
    diagnostics: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "lines": [line.to_dict() for line in self.lines],
            "language": self.language,
            "backend": self.backend,
            "coverage": self.coverage,
            "confidence": self.confidence,
            "structural_score": self.structural_score,
            "runtime_ms": self.runtime_ms,
            "diagnostics": dict(self.diagnostics),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AlignmentResult":
        return cls(
            lines=[
                AlignedLine.from_mapping(line)
                for line in value.get("lines", [])
                if isinstance(line, Mapping)
            ],
            language=str(value.get("language") or "unknown"),
            backend=str(value.get("backend") or "unknown"),
            coverage=float(value.get("coverage", 0.0)),
            confidence=float(value.get("confidence", 0.0)),
            structural_score=float(value.get("structural_score", 0.0)),
            runtime_ms=float(value.get("runtime_ms", 0.0)),
            diagnostics=dict(value.get("diagnostics") or {}),
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not 0.0 <= self.coverage <= 1.0:
            errors.append("coverage must be between 0 and 1")
        for score_name in ("confidence", "structural_score"):
            score = getattr(self, score_name)
            if not 0.0 <= score <= 1.0:
                errors.append(f"{score_name} must be between 0 and 1")
        if self.runtime_ms < 0 or not math.isfinite(self.runtime_ms):
            errors.append("runtime_ms must be finite and non-negative")

        previous_start: float | None = None
        previous_source_index: int | None = None
        for position, line in enumerate(self.lines):
            if not math.isfinite(line.start) or line.start < 0:
                errors.append(f"line {position} has an invalid start time")
            if line.end is not None and (
                not math.isfinite(line.end) or line.end < line.start
            ):
                errors.append(f"line {position} has an invalid end time")
            if line.confidence is not None and not 0.0 <= line.confidence <= 1.0:
                errors.append(f"line {position} has an invalid confidence")
            if previous_start is not None and line.start <= previous_start:
                errors.append(f"line {position} is not strictly after the previous line")
            if previous_source_index is not None and line.source_line_index <= previous_source_index:
                errors.append(f"line {position} has a non-increasing source index")
            previous_start = line.start
            previous_source_index = line.source_line_index
        return errors

    def to_lrc(self) -> str:
        """Serialize only a validated result into line-level LRC."""
        errors = self.validation_errors()
        if errors:
            raise ValueError("Cannot serialize invalid alignment result: " + "; ".join(errors))
        return "\n".join(
            f"[{_format_timestamp(line.start)}] {line.text}"
            for line in self.lines
            if line.text.strip()
        )


def _format_timestamp(seconds: float) -> str:
    total_centiseconds = max(0, int(round(float(seconds) * 100)))
    minutes, remainder = divmod(total_centiseconds, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


class LyricsAlignmentBackend(Protocol):
    name: str

    def supports_language(self, language: str) -> bool:
        ...

    def align(self, request: AlignmentRequest) -> AlignmentResult:
        ...


def manual_anchors_from_mappings(values: list[dict[str, Any]] | None) -> list[ManualAnchor]:
    """Convert legacy worker dictionaries while retaining its ignore-invalid behavior."""
    anchors: list[ManualAnchor] = []
    for value in values or []:
        try:
            anchors.append(ManualAnchor.from_mapping(value))
        except (KeyError, TypeError, ValueError):
            continue
    return anchors


__all__ = [
    "AlignedLine",
    "AlignmentOptions",
    "AlignmentRequest",
    "AlignmentResult",
    "LyricsAlignmentBackend",
    "ManualAnchor",
    "manual_anchors_from_mappings",
]
