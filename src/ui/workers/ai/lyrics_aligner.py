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

from .contracts import (
    AlignedLine,
    AlignmentOptions,
    AlignmentRequest,
    AlignmentResult,
)
from .phonemization import EnglishG2PPhonemizer
from .runtime import default_lyrics_aligner_dir

logger = logging.getLogger(__name__)

_MODEL_SAMPLE_RATE = 16000
_BACKEND_LOCK = threading.Lock()
_BACKEND_CACHE: dict[tuple[str, str], EnglishLyricsAlignerBackend] = {}


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


def _vectorized_optimal_alignment_path(matrix: Any, *, init: int = 200) -> Any:
    """Evaluate the final path with row-vectorized float64 accumulation.

    Copy the neural scores to the host once. Row operations avoid upstream
    diagonal indexing and thousands of small CUDA kernels. Float64 and the
    original tie-breaking rules preserve the upstream final alignment path.
    """

    import numpy as np

    if matrix.ndim != 3 or matrix.shape[0] != 1:
        raise ValueError("lyrics-aligner DTW expects a [1, time, phoneme] matrix")
    scores = matrix.detach().cpu().numpy()[0].astype(np.float64)
    sequence_length, phoneme_length = scores.shape
    accumulated = np.full((sequence_length + 1, phoneme_length + 1), -100000.0)
    accumulated[0, 0] = init
    for row in range(1, sequence_length + 1):
        accumulated[row, 1:] = scores[row - 1] + np.maximum(
            accumulated[row - 1, 1:], accumulated[row - 1, :-1],
        )
    accumulated_scores = accumulated[1:, 1:]
    sequence_length, phoneme_length = accumulated_scores.shape
    optimal_path = np.zeros((sequence_length, phoneme_length))
    optimal_path[-1, -1] = 1

    row = sequence_length - 2
    column = phoneme_length - 1
    while column > 0:
        same_phoneme = accumulated_scores[row, column]
        previous_phoneme = accumulated_scores[row, column - 1]
        step_back = np.argmax([same_phoneme, previous_phoneme])
        optimal_path[row, column - step_back] = 1
        row -= 1
        column -= step_back
        if row == -2:
            logger.warning("lyrics-aligner DTW backtracking reached an invalid row")
            break
    optimal_path[0 : row + 1, 0] = 1
    return optimal_path


def _patch_inference_dtw(model_module: Any) -> None:
    """Keep upstream float32 inference scores while removing diagonal indexing.

    The model calls this separately from the final float64 path search. Each
    cell depends only on the previous row. A single host transfer and NumPy
    row operations avoid thousands of tiny Torch indexing/reduction kernels.
    Leave gradients, other modes and unsupported dtypes to upstream unchanged.
    """
    original = model_module.dtw_matrix
    if getattr(original, "_pylrcget_inference_dtw", False):
        return

    def inference_dtw(scores, mode="faster", idx_to_skip=None):
        import numpy as np
        import torch

        if (
            torch.is_grad_enabled() or mode != "faster" or idx_to_skip is not None
            or scores.dtype != torch.float32 or torch.get_default_dtype() != torch.float32
        ):
            return original(scores, mode=mode, idx_to_skip=idx_to_skip)
        values = scores.detach().cpu().numpy()
        batch, frames, phonemes = values.shape
        accumulated = np.full((batch, frames + 1, phonemes + 1), -100000, dtype=np.float32)
        accumulated[:, 0, 0] = 200000
        for row in range(1, frames + 1):
            accumulated[:, row, 1:] = values[:, row - 1, :] + np.maximum(
                accumulated[:, row - 1, 1:], accumulated[:, row - 1, :-1],
            )
        return torch.from_numpy(accumulated[:, 1:, 1:]).to(scores.device)

    inference_dtw._pylrcget_inference_dtw = True
    model_module.dtw_matrix = inference_dtw


def _prefer_spaces_in_silence(
    alignment_scores: Any,
    voice_estimate: Any,
    *,
    space_indices: Any,
    vad_threshold: float,
) -> None:
    """Give word gaps the highest score in frames without vocal energy.

    ``voice_estimate`` is ``[frame, sample, channel, bin]``. Upstream sums it
    over frequency bins to get one vocal magnitude per frame; frames below the
    threshold are treated as silence, so the alignment path spends
    instrumental passages between words instead of stretching words over them.
    """
    import torch

    frame_magnitude = voice_estimate[:, 0, 0, :].detach().sum(dim=1)
    silent_frames = torch.nonzero(frame_magnitude < vad_threshold, as_tuple=True)[0]
    silent_frames = silent_frames[silent_frames < alignment_scores.shape[1]].to(alignment_scores.device)
    if silent_frames.numel() == 0 or space_indices.numel() == 0:
        return
    # Every silent frame receives the same value, so one maximum is enough.
    alignment_scores[:, silent_frames[:, None], space_indices.to(alignment_scores.device)] = (
        alignment_scores.max()
    )


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
        _patch_inference_dtw(model_module)
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

    def _model_evidence(self, audio_path: str, phonemes_idx: Any) -> tuple[Any, Any]:
        """Return the model's voice estimate and phoneme scores for one recording."""
        assert self._model is not None
        import librosa as librosa_module
        import torch

        audio, _sample_rate = librosa_module.load(audio_path, sr=_MODEL_SAMPLE_RATE, mono=True)
        audio_tensor = torch.tensor(audio, dtype=torch.float32, device=self.device)[None, None, :]
        with torch.no_grad():
            voice_estimate, _unused, scores = self._model((audio_tensor, phonemes_idx))
        return voice_estimate, scores if self.device == "cuda" else scores.cpu()

    def _word_predictions(
        self,
        audio_path: str,
        lyrics: str,
        *,
        vad_threshold: float = 30,
        vocal_stem_path: str | None = None,
    ) -> list[tuple[float, str]]:
        self._ensure_loaded()
        assert self._align_module is not None
        import torch

        symbols, word_list, phonemes_idx = self._phoneme_inputs(lyrics, torch)
        voice_estimate, alignment_scores = self._model_evidence(audio_path, phonemes_idx)
        if vocal_stem_path:
            # The mix and its separated vocals fail on different passages, so
            # one path is searched over the evidence of both recordings.
            _stem_voice, stem_scores = self._model_evidence(vocal_stem_path, phonemes_idx)
            frames = min(alignment_scores.shape[1], stem_scores.shape[1])
            alignment_scores = alignment_scores[:, :frames] + stem_scores[:, :frames]
        if vad_threshold > 0:
            _prefer_spaces_in_silence(
                alignment_scores,
                voice_estimate,
                space_indices=torch.nonzero(phonemes_idx == 3, as_tuple=True)[1],
                vad_threshold=vad_threshold,
            )
        optimal_path = _vectorized_optimal_alignment_path(alignment_scores)
        phoneme_onsets = self._align_module.compute_phoneme_onsets(
            optimal_path,
            hop_length=256,
            sampling_rate=_MODEL_SAMPLE_RATE,
        )
        word_onsets, _word_offsets = self._align_module.compute_word_alignment(
            symbols,
            phoneme_onsets,
        )
        return [(float(timestamp), word) for word, timestamp in zip(word_list, word_onsets)]

    def align(
        self,
        request: AlignmentRequest,
        *,
        vocal_stem_path: str | None = None,
    ) -> AlignmentResult:
        started = time.perf_counter()
        stem_options = {"vocal_stem_path": vocal_stem_path} if vocal_stem_path else {}
        predicted = self._word_predictions(request.audio_path, request.plain_lyrics, **stem_options)
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
                "vocal_stem": bool(vocal_stem_path),
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


def align(
    audio_path: str,
    lyrics: str,
    *,
    device: str,
    vocal_stem_path: str | None = None,
) -> str:
    """Return line-level LRC, optionally adding evidence from a separated vocal stem."""
    request = AlignmentRequest(
        job_id="lyrics-aligner-compat",
        audio_path=audio_path,
        plain_lyrics=lyrics,
        requested_language="en",
        manual_anchors=[],
        device=device,
        options=AlignmentOptions(),
    )
    return get_cached_backend(device=device).align(request, vocal_stem_path=vocal_stem_path).to_lrc()


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
                score = (
                    100 if word == predicted[candidate][1]
                    else SequenceMatcher(None, word, predicted[candidate][1]).ratio() * 100
                )
                if score >= 90 and (match is None or score > match[0]):
                    match = (score, candidate)
                    if score == 100:
                        break
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
    return "\n".join(output)


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


__all__ = [
    "EnglishLyricsAlignerBackend",
    "align",
    "clear_backend_cache",
    "get_cached_backend",
    "is_available",
]
