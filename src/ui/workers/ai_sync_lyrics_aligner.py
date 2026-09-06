"""Warm optional English lyrics-aligner backend.

The upstream ``schufo/lyrics-aligner`` project is MIT licensed.  Its model
and DTW helpers are loaded as Python modules inside the already persistent AI
runtime.  This keeps the upstream checkout untouched and removes the old
per-request temporary audio directory, subprocess and checkpoint load.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import pickle
import re
import sys
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .ai_runtime import default_lyrics_aligner_dir
from .ai_sync_contracts import AlignmentOptions, AlignmentRequest, AlignmentResult, AlignedLine
from .ai_sync_phonemization import EnglishG2PPhonemizer

logger = logging.getLogger(__name__)

_BACKEND_LOCK = threading.Lock()
_BACKEND_CACHE: dict[tuple[str, str], "EnglishLyricsAlignerBackend"] = {}


def _backend_root() -> Path | None:
    value = os.environ.get("PYLRCGET_LYRICS_ALIGNER_PATH", "").strip()
    root = Path(value).expanduser() if value else default_lyrics_aligner_dir()
    if not (
        (root / "align.py").is_file()
        and (root / "model.py").is_file()
        and (root / "model_parameters.pth").is_file()
        and (root / "files" / "phoneme2idx.pickle").is_file()
    ):
        return None
    return root


def is_available() -> bool:
    return _backend_root() is not None


def _words(text: str) -> list[str]:
    return re.findall(r"'?[a-z]+(?:'[a-z]*)?", text.lower().replace("’", "'"))


def _patch_torch_compatibility(torch_module: Any) -> None:
    """Adapt old upstream ``torch.stft`` calls without editing model.py."""
    original = torch_module.stft
    if getattr(original, "_pylrcget_lyrics_aligner_compat", False):
        return

    def compatible_stft(*args, **kwargs):
        kwargs.setdefault("return_complex", False)
        return original(*args, **kwargs)

    compatible_stft._pylrcget_lyrics_aligner_compat = True
    torch_module.stft = compatible_stft


def _load_upstream_modules(root: Path) -> tuple[Any, Any]:
    """Load upstream model/DTW modules without making them global imports."""
    cache_key = str(root.resolve())
    model_name = f"_pylrcget_lyrics_aligner_model_{abs(hash(cache_key))}"
    align_name = f"_pylrcget_lyrics_aligner_align_{abs(hash(cache_key))}"

    model_module = sys.modules.get(model_name)
    if model_module is None:
        model_spec = importlib.util.spec_from_file_location(model_name, root / "model.py")
        if model_spec is None or model_spec.loader is None:
            raise RuntimeError("Could not load lyrics-aligner model module.")
        model_module = importlib.util.module_from_spec(model_spec)
        sys.modules[model_name] = model_module
        model_spec.loader.exec_module(model_module)

    align_module = sys.modules.get(align_name)
    if align_module is None:
        align_spec = importlib.util.spec_from_file_location(align_name, root / "align.py")
        if align_spec is None or align_spec.loader is None:
            raise RuntimeError("Could not load lyrics-aligner alignment module.")
        align_module = importlib.util.module_from_spec(align_spec)
        previous_model = sys.modules.get("model")
        sys.modules["model"] = model_module
        try:
            align_spec.loader.exec_module(align_module)
        finally:
            if previous_model is None:
                sys.modules.pop("model", None)
            else:
                sys.modules["model"] = previous_model
        sys.modules[align_name] = align_module
    return model_module, align_module


class EnglishLyricsAlignerBackend:
    """Reusable in-process wrapper around the MIT upstream aligner model."""

    name = "lyrics-aligner"

    def __init__(self, root: Path, *, device: str) -> None:
        self.root = root.resolve()
        self.device = str(device or "cpu")
        self._model: Any | None = None
        self._align_module: Any | None = None
        self._phoneme2idx: dict[str, int] | None = None
        self._phonemizer = EnglishG2PPhonemizer()
        self._load_count = 0

    def supports_language(self, language: str) -> bool:
        return str(language or "").strip().lower() == "en"

    @property
    def model_load_count(self) -> int:
        return self._load_count

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._align_module is not None:
            return
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "lyrics-aligner requires the optional g2p-en and torch packages."
            ) from exc
        self._phonemizer.warm()
        _patch_torch_compatibility(torch)
        model_module, align_module = _load_upstream_modules(self.root)
        with (self.root / "files" / "phoneme2idx.pickle").open("rb") as handle:
            phoneme2idx = pickle.load(handle)
        model = model_module.InformedOpenUnmix3().to(self.device)
        state_dict = torch.load(
            self.root / "model_parameters.pth",
            map_location=self.device,
        )
        model.load_state_dict(state_dict)
        model.eval()
        self._model = model
        self._align_module = align_module
        self._phoneme2idx = {str(key): int(value) for key, value in phoneme2idx.items()}
        self._load_count += 1

    def _word_phonemes(self, word: str) -> str:
        try:
            return self._phonemizer.phonemize_word(word)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    def _phoneme_inputs(self, lyrics: str, torch_module: Any) -> tuple[list[str], list[str], Any]:
        assert self._phoneme2idx is not None
        symbols = [">"]
        word_list: list[str] = []
        for raw_line in lyrics.splitlines():
            for word in _words(raw_line):
                word_list.append(word)
                symbols.extend(self._word_phonemes(word).split())
                symbols.append(">")
        if not word_list:
            raise RuntimeError("lyrics-aligner could not phonemize the supplied lyrics.")
        try:
            indices = [self._phoneme2idx[symbol] for symbol in symbols]
        except KeyError as exc:
            raise RuntimeError(f"lyrics-aligner does not support phoneme {exc.args[0]!r}.") from exc
        tensor = torch_module.tensor(
            indices,
            dtype=torch_module.float32,
            device=self.device,
        )[None, :]
        return symbols, word_list, tensor

    def _word_predictions(
        self,
        audio_path: str,
        lyrics: str,
        *,
        vad_threshold: float = 30,
    ) -> list[tuple[float, str]]:
        self._ensure_loaded()
        assert self._model is not None
        assert self._align_module is not None
        import librosa as librosa_module
        import torch

        symbols, word_list, phonemes_idx = self._phoneme_inputs(lyrics, torch)
        audio, sample_rate = librosa_module.load(audio_path, sr=16000, mono=True)
        audio_tensor = torch.tensor(audio, dtype=torch.float32, device=self.device)[None, None, :]
        with torch.no_grad():
            voice_estimate, _unused, scores = self._model((audio_tensor, phonemes_idx))
            scores = scores.cpu()
        if vad_threshold > 0:
            vocals_mag = voice_estimate[:, 0, 0, :].detach().cpu().numpy().sum(axis=0)
            predicted_silence = (vocals_mag < vad_threshold).nonzero()[0]
            space_indices = torch.nonzero(phonemes_idx == 3, as_tuple=True)[1].cpu()
            for frame in predicted_silence:
                scores[:, frame, space_indices] = scores.max()
        optimal_path = self._align_module.optimal_alignment_path(scores)
        phoneme_onsets = self._align_module.compute_phoneme_onsets(
            optimal_path,
            hop_length=256,
            sampling_rate=sample_rate,
        )
        word_onsets, _word_offsets = self._align_module.compute_word_alignment(
            symbols,
            phoneme_onsets,
        )
        return [(float(timestamp), word) for word, timestamp in zip(word_list, word_onsets)]

    def align(self, request: AlignmentRequest) -> AlignmentResult:
        started = time.perf_counter()
        predicted = self._word_predictions(request.audio_path, request.plain_lyrics)
        raw_lrc = _build_lrc_from_predictions(request.plain_lyrics, predicted)
        lines = _result_lines(request.plain_lyrics, raw_lrc)
        expected_count = sum(bool(_words(line)) for line in request.plain_lyrics.splitlines())
        coverage = len(lines) / expected_count if expected_count else 0.0
        return AlignmentResult(
            lines=lines,
            language="en",
            backend=self.name,
            coverage=coverage,
            confidence=coverage,
            structural_score=coverage,
            runtime_ms=(time.perf_counter() - started) * 1000,
            diagnostics={
                "audio_copied": False,
                "align_subprocess": False,
                "checkpoint_loads": self._load_count,
                "g2p_cache_size": self._phonemizer.cache_size,
                "predicted_words": len(predicted),
            },
        )


def get_cached_backend(*, device: str, root: Path | None = None) -> EnglishLyricsAlignerBackend:
    selected_root = root or _backend_root()
    if selected_root is None:
        raise RuntimeError("lyrics-aligner is not configured; set PYLRCGET_LYRICS_ALIGNER_PATH.")
    key = (str(selected_root.resolve()), str(device or "cpu"))
    with _BACKEND_LOCK:
        backend = _BACKEND_CACHE.get(key)
        if backend is None:
            backend = EnglishLyricsAlignerBackend(selected_root, device=device)
            _BACKEND_CACHE[key] = backend
        return backend


def clear_backend_cache() -> None:
    with _BACKEND_LOCK:
        _BACKEND_CACHE.clear()


def align(audio_path: str, lyrics: str, *, device: str) -> str:
    """Compatibility API returning the existing line-level LRC string."""
    request = AlignmentRequest(
        job_id="lyrics-aligner-compat",
        audio_path=audio_path,
        plain_lyrics=lyrics,
        requested_language="en",
        manual_anchors=[],
        device=device,
        options=AlignmentOptions(),
    )
    return get_cached_backend(device=device).align(request).to_lrc()


def _build_lrc_from_predictions(
    lyrics: str,
    predicted: list[tuple[float, str]],
) -> str:
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


def _result_lines(lyrics: str, raw_lrc: str) -> list[AlignedLine]:
    expected = [
        (index, line.strip())
        for index, line in enumerate(lyrics.splitlines())
        if _words(line)
    ]
    result: list[AlignedLine] = []
    cursor = 0
    for line in raw_lrc.splitlines():
        match = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)", line.strip())
        if not match:
            continue
        timestamp = int(match.group(1)) * 60 + float(match.group(2))
        text = match.group(3).strip()
        normalized = " ".join(_words(text))
        source_index = None
        for position in range(cursor, len(expected)):
            if " ".join(_words(expected[position][1])) == normalized:
                source_index = position
                break
        if source_index is None:
            continue
        source_line_index, source_text = expected[source_index]
        result.append(
            AlignedLine(
                source_line_index=source_line_index,
                text=source_text,
                start=timestamp,
                end=None,
                confidence=1.0,
                backend="lyrics-aligner",
                evidence={"matching": "word_onset"},
            )
        )
        cursor = source_index + 1
    return result


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
    return _build_lrc_from_predictions(lyrics, predicted)


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
        key = tuple(
            re.sub(r"[^a-z0-9]+", " ", parsed[index + offset][1].lower()).strip()
            for offset in range(4)
        )
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


__all__ = [
    "EnglishLyricsAlignerBackend",
    "align",
    "clear_backend_cache",
    "get_cached_backend",
    "is_available",
]
