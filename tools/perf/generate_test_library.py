#!/usr/bin/env python3
"""Generate a deterministic local audio corpus for scan benchmarks.

WAV is the default because it can be generated with the Python standard
library. Other formats require an installed ``ffmpeg`` executable and are
converted from the generated WAV before optional Mutagen tagging.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


AUDIO_FORMATS = {
    "mp3": ".mp3",
    "flac": ".flac",
    "m4a": ".m4a",
    "ogg": ".ogg",
    "opus": ".opus",
    "wma": ".wma",
    "wav": ".wav",
    "dsf": ".dsf",
    "dff": ".dff",
    "mpc": ".mpc",
}


def _write_wav(path: Path, *, duration_s: float = 0.5) -> None:
    sample_rate = 8_000
    frames = int(sample_rate * duration_s)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * frames)


def _tag_audio(
    path: Path,
    *,
    title: str,
    artist: str,
    album: str,
    track_number: int,
    embedded: str,
) -> None:
    try:
        from mutagen import File as MutagenFile
        from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TIT2, TPE1, TPE2, TRCK, TXXX, USLT
    except ImportError as exc:
        raise SystemExit(f"Mutagen is required to tag generated audio: {exc}") from exc

    audio = MutagenFile(str(path), easy=False)
    if audio is None:
        return

    ext = path.suffix.lower()
    plain = "plain lyrics for " + title
    synced = "[00:00.00]synced lyrics for " + title
    if ext in {".wav", ".mp3", ".dsf", ".dff"}:
        tags = getattr(audio, "tags", None)
        if tags is None:
            if ext == ".mp3":
                try:
                    tags = ID3(str(path))
                except ID3NoHeaderError:
                    tags = ID3()
                audio.tags = tags
            else:
                audio.add_tags()
                tags = audio.tags
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TALB(encoding=3, text=album))
        tags.add(TPE1(encoding=3, text=artist))
        tags.add(TPE2(encoding=3, text=artist))
        tags.add(TRCK(encoding=3, text=str(track_number)))
        if embedded in {"plain", "both"}:
            tags.add(USLT(encoding=3, lang="und", desc="", text=plain))
        if embedded in {"synced", "both"}:
            tags.add(TXXX(encoding=3, desc="LYRICS", text=synced))
        audio.save()
        return

    try:
        if getattr(audio, "tags", None) is None:
            audio.add_tags()
        tags = audio.tags
        tags["title"] = [title]
        tags["artist"] = [artist]
        tags["album"] = [album]
        tags["tracknumber"] = [str(track_number)]
        if embedded in {"plain", "both"}:
            tags["UNSYNCEDLYRICS"] = [plain]
        if embedded in {"synced", "both"}:
            tags["LYRICS"] = [synced]
        audio.save()
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        # The generated file remains useful as a filesystem corpus even when
        # a particular optional container cannot be tagged by this Mutagen build.
        return


def _convert_wav(source: Path, target: Path, format_name: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit(f"Generating {format_name} requires ffmpeg on PATH.")
    command = [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), str(target)]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"ffmpeg failed while creating {target}: {exc}") from exc


def generate_library(
    root: Path,
    *,
    tracks: int,
    formats: list[str],
    embedded: str,
    sidecars: str,
    depth: int,
    unicode_metadata: bool,
) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pylrcget-perf-") as tmp:
        source = Path(tmp) / "source.wav"
        _write_wav(source)
        for index in range(1, tracks + 1):
            artist = f"Artist {((index - 1) % 40) + 1}"
            title = f"Track {index:05d}"
            album = f"Album {((index - 1) % 100) + 1:03d}"
            if unicode_metadata and index % 5 == 0:
                artist = f"Артист {index % 10} – Béla"
                title = f"Трек {index:05d} / 東京"
                album = "Édition spéciale"

            directory = root / f"set_{((index - 1) % max(1, depth)) + 1:03d}"
            directory.mkdir(parents=True, exist_ok=True)
            filename_title = title.replace("/", "_").replace("\\", "_")
            for format_name in formats:
                suffix = AUDIO_FORMATS[format_name]
                audio_path = directory / f"{index:05d}-{filename_title}{suffix}"
                if format_name == "wav":
                    _write_wav(audio_path)
                else:
                    _convert_wav(source, audio_path, format_name)
                _tag_audio(
                    audio_path,
                    title=title,
                    artist=artist,
                    album=album,
                    track_number=((index - 1) % 20) + 1,
                    embedded=embedded,
                )
                created.append(str(audio_path))

            stem_path = directory / f"{index:05d}-{filename_title}"
            if sidecars in {"plain", "both"}:
                txt = stem_path.with_suffix(".txt")
                txt.write_text(f"plain sidecar for {title}\n", encoding="utf-8")
            if sidecars in {"synced", "both"}:
                lrc = stem_path.with_suffix(".lrc")
                lrc.write_text(f"[00:00.00]synced sidecar for {title}\n", encoding="utf-8")

    manifest = {
        "tracks": tracks,
        "formats": formats,
        "embedded": embedded,
        "sidecars": sidecars,
        "depth": depth,
        "unicode_metadata": unicode_metadata,
        "audio_files": created,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory to create or extend")
    parser.add_argument("--tracks", type=int, default=1_000)
    parser.add_argument("--formats", default="wav", help="Comma-separated formats; wav is dependency-free")
    parser.add_argument("--embedded", choices=("none", "plain", "synced", "both"), default="none")
    parser.add_argument("--sidecars", choices=("none", "plain", "synced", "both"), default="none")
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--unicode-metadata", action="store_true")
    args = parser.parse_args()

    if args.tracks <= 0:
        parser.error("--tracks must be positive")
    if args.depth <= 0:
        parser.error("--depth must be positive")
    formats = [item.strip().lower().lstrip(".") for item in args.formats.split(",") if item.strip()]
    invalid = sorted(set(formats) - set(AUDIO_FORMATS))
    if invalid:
        parser.error(f"Unsupported format(s): {', '.join(invalid)}")
    manifest = generate_library(
        args.root,
        tracks=args.tracks,
        formats=formats,
        embedded=args.embedded,
        sidecars=args.sidecars,
        depth=args.depth,
        unicode_metadata=args.unicode_metadata,
    )
    # Keep CLI output usable in the default Windows console encoding.
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
