"""Small deterministic corpora for AI sync benchmark and quality checks."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    language: str
    category: str
    lines: tuple[str, ...]
    expected_timestamps_ms: tuple[float, ...]
    duration_seconds: float
    audio_path: str | None = None
    repeat_group_ids: tuple[int | None, ...] = ()

    @property
    def lyrics(self) -> str:
        return "\n".join(self.lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "language": self.language,
            "category": self.category,
            "lines": list(self.lines),
            "expected_timestamps_ms": list(self.expected_timestamps_ms),
            "duration_seconds": self.duration_seconds,
            "audio_path": self.audio_path,
            "repeat_group_ids": list(self.repeat_group_ids),
        }


def builtin_corpus() -> tuple[BenchmarkCase, ...]:
    """Return a compact, non-copyrighted fixture corpus.

    The text is intentionally synthetic.  It exercises language, Unicode,
    repetition, missing metadata and punctuation categories without using a
    public service or shipping copyrighted lyrics in the repository.
    """
    return (
        BenchmarkCase(
            "en-exact-01",
            "en",
            "exact hit",
            ("Silver signals cross the room", "Quiet engines carry on", "Morning finds the open road"),
            (1200.0, 5200.0, 9100.0),
            13.0,
            repeat_group_ids=(None, None, None),
        ),
        BenchmarkCase(
            "en-repeat-01",
            "en",
            "repeated phrase",
            ("Turn the small wheel", "Turn the small wheel", "Leave the old station", "Turn the small wheel"),
            (900.0, 3500.0, 7100.0, 10400.0),
            14.0,
            repeat_group_ids=(1, 1, None, 1),
        ),
        BenchmarkCase(
            "ro-unicode-01",
            "ro",
            "Unicode punctuation",
            ("Șoapta rămâne-n aer", "Mâine începe aici", "Înapoi — fără grabă"),
            (1500.0, 5800.0, 10300.0),
            15.0,
        ),
        BenchmarkCase(
            "ja-short-01",
            "ja",
            "short lines",
            ("静かな朝", "光が進む", "道は続く"),
            (800.0, 4100.0, 7600.0),
            11.0,
        ),
        BenchmarkCase(
            "mixed-missing-duration-01",
            "mixed",
            "missing duration",
            ("Signal / semnal", "Über den Rand", "戻ってくる"),
            (1100.0, 4800.0, 8700.0),
            12.0,
        ),
    )


def build_corpus(
    *,
    profile: str = "smoke",
    count: int | None = None,
    duplicate_every: int = 0,
) -> list[BenchmarkCase]:
    base = list(builtin_corpus())
    target = {"smoke": 5, "small": 25, "medium": 100}.get(profile)
    if target is None:
        raise ValueError(f"Unknown corpus profile: {profile}")
    total = max(1, int(count if count is not None else target))
    cases: list[BenchmarkCase] = []
    for index in range(total):
        source = base[index % len(base)]
        if index < len(base):
            case = source
        else:
            case = BenchmarkCase(
                case_id=f"{source.case_id}-{index + 1:04d}",
                language=source.language,
                category=source.category,
                lines=source.lines,
                expected_timestamps_ms=source.expected_timestamps_ms,
                duration_seconds=source.duration_seconds,
                audio_path=source.audio_path,
                repeat_group_ids=source.repeat_group_ids,
            )
        if duplicate_every > 0 and index % duplicate_every == 0 and index:
            case = BenchmarkCase(
                case_id=case.case_id,
                language=case.language,
                category=f"duplicate of {base[(index - 1) % len(base)].case_id}",
                lines=base[(index - 1) % len(base)].lines,
                expected_timestamps_ms=base[(index - 1) % len(base)].expected_timestamps_ms,
                duration_seconds=base[(index - 1) % len(base)].duration_seconds,
                audio_path=case.audio_path,
                repeat_group_ids=base[(index - 1) % len(base)].repeat_group_ids,
            )
        cases.append(case)
    return cases


def load_corpus(path: str | Path) -> list[BenchmarkCase]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("AI benchmark corpus must contain a list of cases")
    cases: list[BenchmarkCase] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"Corpus case {index} is not an object")
        lines = tuple(str(line) for line in raw.get("lines", []))
        timestamps = tuple(float(value) for value in raw.get("expected_timestamps_ms", []))
        if len(lines) != len(timestamps):
            raise ValueError(f"Corpus case {index} has mismatched lines/timestamps")
        cases.append(
            BenchmarkCase(
                case_id=str(raw.get("id") or f"case-{index + 1}"),
                language=str(raw.get("language") or "auto"),
                category=str(raw.get("category") or "custom"),
                lines=lines,
                expected_timestamps_ms=timestamps,
                duration_seconds=float(raw.get("duration_seconds") or 0.0),
                audio_path=str(raw["audio_path"]) if raw.get("audio_path") else None,
                repeat_group_ids=tuple(raw.get("repeat_group_ids") or ()),
            )
        )
    return cases


__all__ = ["BenchmarkCase", "build_corpus", "builtin_corpus", "load_corpus"]
