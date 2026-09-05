#!/usr/bin/env python3
"""Apply deterministic mutations used by incremental scan benchmarks."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


AUDIO_SUFFIXES = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".wma", ".asf", ".dsf", ".dff", ".mpc"}


def audio_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
    )


def choose_paths(root: Path, fraction: float, seed: int) -> list[Path]:
    paths = audio_files(root)
    if not paths:
        raise ValueError(f"No supported audio files found below {root}")
    count = max(1, round(len(paths) * fraction))
    if count > len(paths):
        count = len(paths)
    generator = random.Random(seed)
    return sorted(generator.sample(paths, count))


def mutate(
    root: Path,
    *,
    operation: str,
    suffix: str,
    fraction: float,
    seed: int,
) -> dict[str, object]:
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in the interval (0, 1]")
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    selected = choose_paths(root, fraction, seed)
    changed: list[str] = []
    skipped: list[str] = []

    for audio in selected:
        sidecar = audio.with_suffix(suffix)
        if operation == "add-sidecar":
            sidecar.write_text(f"[00:00.00]new sidecar for {audio.stem}\n", encoding="utf-8")
            changed.append(str(sidecar))
        elif operation == "change-sidecar":
            if not sidecar.exists():
                sidecar.write_text(f"[00:00.00]initial sidecar for {audio.stem}\n", encoding="utf-8")
            else:
                with sidecar.open("a", encoding="utf-8") as output:
                    output.write("[00:01.00]changed sidecar\n")
            changed.append(str(sidecar))
        elif operation == "remove-sidecar":
            if sidecar.exists():
                sidecar.unlink()
                changed.append(str(sidecar))
            else:
                skipped.append(str(sidecar))
        elif operation == "rename-sidecar":
            source = sidecar
            target = audio.with_name(f"{audio.stem} renamed{suffix}")
            if source.exists():
                source.replace(target)
                changed.extend([str(source), str(target)])
            else:
                skipped.append(str(source))
        elif operation == "change-audio":
            with audio.open("ab") as output:
                output.write(b"\x00")
            changed.append(str(audio))
        elif operation == "mixed":
            with audio.open("ab") as output:
                output.write(b"\x00")
            sidecar.write_text(f"[00:02.00]mixed mutation for {audio.stem}\n", encoding="utf-8")
            changed.extend([str(audio), str(sidecar)])
        else:
            raise ValueError(f"Unsupported operation: {operation}")

    return {
        "root": str(root),
        "operation": operation,
        "suffix": suffix,
        "fraction": fraction,
        "seed": seed,
        "selected_audio_files": len(selected),
        "changed": changed,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "operation",
        choices=("add-sidecar", "change-sidecar", "remove-sidecar", "rename-sidecar", "change-audio", "mixed"),
    )
    parser.add_argument("--suffix", default=".lrc", choices=(".lrc", ".txt"))
    parser.add_argument("--fraction", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = mutate(
        args.root,
        operation=args.operation,
        suffix=args.suffix,
        fraction=args.fraction,
        seed=args.seed,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
