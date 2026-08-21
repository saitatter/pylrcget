"""Optional lyrics-aligner backend for English singing."""
from __future__ import annotations

import os
import pickle
import re
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from .ai_runtime import default_lyrics_aligner_dir, resolve_ai_runtime_python


def _backend_root() -> Path | None:
    value = os.environ.get("PYLRCGET_LYRICS_ALIGNER_PATH", "").strip()
    root = (
        Path(value).expanduser()
        if value
        else default_lyrics_aligner_dir()
    )
    if not (root / "align.py").is_file() or not (root / "model_parameters.pth").is_file():
        return None
    if not (root / "files" / "phoneme2idx.pickle").is_file():
        return None
    return root


def is_available() -> bool:
    return _backend_root() is not None


def _ensure_cpu_checkpoint_compatibility(root: Path) -> None:
    """Make the upstream aligner load CUDA checkpoints on CPU runtimes."""
    script = root / "align.py"
    source = script.read_text(encoding="utf-8")
    patched = source.replace(
        "torch.load('model_parameters.pth')",
        "torch.load('model_parameters.pth', map_location=device)",
    ).replace(
        "device = 'cuda' if torch.cuda.is_available() else 'cpu'",
        "device = 'cuda' if torch.cuda.is_available() and "
        "os.environ.get('PYLRCGET_FORCE_CPU') != '1' else 'cpu'",
    )
    if patched != source:
        script.write_text(patched, encoding="utf-8")
    model_script = root / "model.py"
    model_source = model_script.read_text(encoding="utf-8")
    model_patched = model_source.replace(
        "onesided=True,\n            pad_mode='reflect'",
        "onesided=True, return_complex=False,\n            pad_mode='reflect'",
    )
    if model_patched != model_source:
        model_script.write_text(model_patched, encoding="utf-8")


def _words(text: str) -> list[str]:
    return re.findall(r"'?[a-z]+(?:'[a-z]*)?", text.lower().replace("’", "'"))


def _get_dictionary(root: Path, lyrics: str, dataset: str) -> Path:
    dictionary_path = root / "files" / f"{dataset}_word2phonemes.pickle"
    try:
        import g2p_en
    except ImportError as exc:
        raise RuntimeError(
            "lyrics-aligner requires the optional g2p-en package."
        ) from exc

    converter = g2p_en.G2p()
    dictionary: dict[str, str] = {}
    for word in _words(lyrics):
        if word in dictionary:
            continue
        source_word = word.strip("'")
        phonemes = []
        for token in converter(source_word):
            if re.fullmatch(r"[A-Z]+[012]?", token):
                phonemes.append(token.rstrip("012"))
        if phonemes:
            dictionary[word] = " ".join(phonemes)
    if not dictionary:
        raise RuntimeError("lyrics-aligner could not phonemize the supplied lyrics.")
    dictionary["'em"] = dictionary.get("em", "AH M")
    for word in _words(lyrics):
        base_word = word.strip("'")
        if word not in dictionary and base_word in dictionary:
            dictionary[word] = dictionary[base_word]
    with dictionary_path.open("wb") as handle:
        pickle.dump(dictionary, handle)
    return dictionary_path


def align(audio_path: str, lyrics: str, *, device: str) -> str:
    root = _backend_root()
    if root is None:
        raise RuntimeError(
            "lyrics-aligner is not configured; set PYLRCGET_LYRICS_ALIGNER_PATH."
        )
    _ensure_cpu_checkpoint_compatibility(root)

    with tempfile.TemporaryDirectory(prefix="pylrcget-lyrics-aligner-") as temp:
        temp_path = Path(temp)
        audio_dir = temp_path / "audio"
        lyrics_dir = temp_path / "lyrics"
        audio_dir.mkdir()
        lyrics_dir.mkdir()
        audio_file = audio_dir / Path(audio_path).name
        lyrics_file = lyrics_dir / f"{Path(audio_path).stem}.txt"
        audio_file.write_bytes(Path(audio_path).read_bytes())
        lyrics_file.write_text(lyrics, encoding="utf-8")

        dataset = f"pylrcget_{os.getpid()}"
        _get_dictionary(root, lyrics, dataset)
        aligner_python = resolve_ai_runtime_python() or Path(sys.executable)
        command = [
            str(aligner_python),
            "align.py",
            str(audio_dir),
            str(lyrics_dir),
            "--lyrics-format",
            "w",
            "--onsets",
            "w",
            "--dataset-name",
            dataset,
            "--vad-threshold",
            "30",
        ]
        if device == "cpu":
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = ""
            env["PYLRCGET_FORCE_CPU"] = "1"
        else:
            env = os.environ.copy()
        for variable in ("PYTHONHOME", "PYTHONEXECUTABLE", "PYTHONUSERBASE"):
            env.pop(variable, None)
        creationflags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt"
            else 0
        )
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip().splitlines()
            raise RuntimeError(detail[-1] if detail else "lyrics-aligner failed.")

        onset_file = (
            root
            / "outputs"
            / dataset
            / "word_onsets"
            / f"{Path(audio_path).stem}.txt"
        )
        return _build_lrc(lyrics, onset_file)


def _build_lrc(lyrics: str, onset_file: Path) -> str:
    predicted: list[tuple[float, str]] = []
    for line in onset_file.read_text(encoding="utf-8").splitlines():
        word, separator, timestamp = line.partition("\t")
        if not separator:
            continue
        try:
            predicted.append((float(timestamp), word.strip().lower()))
        except ValueError:
            continue

    output: list[str] = []
    cursor = 0
    for line in lyrics.splitlines():
        text = line.strip()
        expected = _words(text)
        if not expected:
            continue
        first_match: int | None = None
        for index, word in enumerate(expected):
            match: tuple[float, int] | None = None
            for candidate in range(cursor, min(len(predicted), cursor + 8)):
                score = SequenceMatcher(None, word, predicted[candidate][1]).ratio() * 100
                if score >= 90 and (match is None or score > match[0]):
                    match = (score, candidate)
            if match is None:
                if index == 0:
                    first_match = None
                continue
            if index == 0:
                first_match = match[1]
            cursor = match[1] + 1
        if first_match is not None:
            seconds = predicted[first_match][0]
            minutes, remainder = divmod(seconds, 60)
            output.append(f"[{int(minutes):02d}:{remainder:05.2f}] {text}")
    return "\n".join(_repair_repeated_block_timestamps(output))


def _repair_repeated_block_timestamps(lines: list[str]) -> list[str]:
    """Repair isolated timing jumps inside repeated four-line lyric blocks."""
    parsed: list[tuple[float, str]] = []
    for line in lines:
        match = re.match(r"\[(\d+):(\d+\.\d+)\]\s+(.*)", line)
        if match:
            parsed.append(
                (
                    int(match.group(1)) * 60 + float(match.group(2)),
                    match.group(3),
                )
            )

    groups: dict[tuple[str, ...], list[int]] = {}
    for index in range(len(parsed) - 3):
        key = tuple(re.sub(r"[^a-z0-9]+", " ", parsed[index + offset][1].lower()).strip()
                    for offset in range(4))
        groups.setdefault(key, []).append(index)

    claimed: set[int] = set()
    for indices in sorted(groups.values(), key=len, reverse=True):
        if len(indices) < 2:
            continue
        block_indices = {index + offset for index in indices for offset in range(4)}
        if claimed & block_indices:
            continue
        claimed.update(block_indices)
        reference = indices[0]
        reference_offsets = [
            parsed[reference + offset][0] - parsed[reference][0]
            for offset in range(4)
        ]
        for index in indices[1:]:
            start = parsed[index][0]
            for offset in range(1, 4):
                actual_offset = parsed[index + offset][0] - start
                expected_offset = reference_offsets[offset]
                if abs(actual_offset - expected_offset) > 5.0:
                    parsed[index + offset] = (
                        start + expected_offset,
                        parsed[index + offset][1],
                    )

    return [
        f"[{int(seconds // 60):02d}:{seconds % 60:05.2f}] {text}"
        for seconds, text in parsed
    ]


__all__ = ["align", "is_available"]
