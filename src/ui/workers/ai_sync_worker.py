"""Qt orchestrator for AI-powered lyrics synchronization."""
from __future__ import annotations

import logging
import multiprocessing
import os
import queue
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .ai_sync_alignment import (
    _align_lyrics_to_segments,
    _align_lyrics_to_segments_viterbi,
    _anchor_bonus,
    _build_guided_word_ranges,
    _build_plain_vocabulary,
    _build_same_phrase_rewind_targets,
    _build_speech_candidate_mask,
    _compute_line_to_words_score,
    _ensure_strictly_increasing_alignment_indices,
    _expected_time_position,
    _expected_word_position,
    _extract_word_confidence,
    _find_confidence_anchors,
    _is_late_line,
    _is_speech_like_token,
    _late_line_candidate_start_floor,
    _late_line_expected_position_bonus,
    _manual_anchor_bonus,
    _normalize_line_text,
    _normalize_word,
    _prepare_manual_line_anchors,
    _same_phrase_rewind_penalty,
    _same_phrase_rewind_transition_penalty,
    _repair_repeated_prefix_timestamp_gaps,
    _tail_rescue_alignment_indices,
    _tail_rescue_collapsed_cluster_indices,
    _tail_rescue_forward_jump_indices,
    _tail_rescue_rewind_target_lag_indices,
    _words_match,
)
from .ai_sync_lrc import (
    _build_lrc_from_plain_layout,
    _build_lrc_from_plain_lines_and_segments,
    _build_lrc_from_segments,
    _format_ts,
    _is_non_lyric_line,
)
from .ai_sync_lyrics_aligner import align as _align_with_lyrics_aligner
from .ai_sync_lyrics_aligner import is_available as _lyrics_aligner_available
from .ai_sync_demucs import (
    AlignmentCandidate,
    candidate_quality as _demucs_candidate_quality,
    is_available as _demucs_available,
    separated_vocal_audio as _separated_vocal_audio,
)
from .ai_sync_runtime import (
    _canonical_vad_options,
    _check_ai_sync_available,
    _clear_inference_caches,
    _get_cached_align_model,
    _get_cached_whisperx_model,
    _module_available,
    _patch_faster_whisper_compatibility,
    _patch_pyannote_compatibility,
    _patch_whisperx_audio_loading,
    get_missing_ai_dependencies,
    is_ai_sync_available,
)
from .ai_sync_transcription import (
    _align_segments_per_chunks,
    _approximate_word_timestamps_from_segments,
    _deduplicate_transcribed_segments,
    _normalized_transcribe_language,
    _segment_alignment_quality,
    _segment_reliable_tail_seconds,
    _segment_tail_seconds,
    _segment_word_starts,
    _find_targeted_retry_window,
    _select_best_relaxed_segments,
    _should_retry_with_short_windows,
    _should_retry_with_relaxed_vad,
    _should_use_per_chunk_alignment,
    _should_use_relaxed_vad_result,
    _transcribe_fixed_windows,
    _transcribe_tail_window,
)

logger = logging.getLogger(__name__)


def _align_with_optional_demucs(
    audio_path: str,
    plain_lyrics: str,
    *,
    device: str,
    enable_demucs_candidate: bool,
) -> AlignmentCandidate:
    """Compatibility wrapper for the centralized mix/Demucs candidate router."""
    from .ai_sync_pipeline import align_with_optional_demucs

    return align_with_optional_demucs(
        audio_path,
        plain_lyrics,
        device=device,
        enable_demucs_candidate=enable_demucs_candidate,
        aligner=_align_with_lyrics_aligner,
        demucs_available=_demucs_available,
        separated_audio=_separated_vocal_audio,
        quality=_demucs_candidate_quality,
    )


class AiSyncWorker(QThread):
    """Worker thread for AI-powered lyrics synchronization."""

    progress = Signal(str)
    completed = Signal(bool, str, str)
    _PROGRESS_MARKER = "__AI_SYNC_PROGRESS__"

    def __init__(
        self,
        audio_path: str,
        plain_lyrics: str = "",
        *,
        manual_anchors: list[dict] | None = None,
        whisper_model: str = "base",
        device: str = "auto",
        language: str = "auto",
        enable_fuzzy: bool = True,
        fuzzy_threshold: int = 60,
        fuzzy_window_words: int = 12,
        enable_demucs_candidate: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.audio_path = audio_path
        self.plain_lyrics = (plain_lyrics or "").strip()
        self.manual_anchors = [a for a in (manual_anchors or []) if isinstance(a, dict)]
        self.whisper_model = whisper_model or "base"
        self._device = device
        self._language = str(language or "auto")
        self._enable_fuzzy = bool(enable_fuzzy)
        self._fuzzy_threshold = int(fuzzy_threshold)
        self._fuzzy_window_words = int(fuzzy_window_words)
        self._enable_demucs_candidate = bool(enable_demucs_candidate)

    def _resolve_device(self) -> str:
        import torch
        if self._device and self._device != "auto":
            return self._device
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _emit_stage(self, current: int, total: int, message: str) -> None:
        self.progress.emit(f"{self._PROGRESS_MARKER}|{int(current)}|{int(total)}|{message}")

    def run(self):
        if os.environ.get("_PYLRCGET_AI_SYNC_CHILD") != "1":
            self._run_in_subprocess()
            return
        self._run_in_process()

    def _run_in_subprocess(self) -> None:
        from .ai_sync_process import run_ai_sync_process

        context = multiprocessing.get_context("spawn")
        messages = context.Queue()
        config = {
            "audio_path": self.audio_path,
            "plain_lyrics": self.plain_lyrics,
            "manual_anchors": self.manual_anchors,
            "whisper_model": self.whisper_model,
            "device": self._device,
            "language": self._language,
            "enable_fuzzy": self._enable_fuzzy,
            "fuzzy_threshold": self._fuzzy_threshold,
            "fuzzy_window_words": self._fuzzy_window_words,
            "enable_demucs_candidate": self._enable_demucs_candidate,
        }
        process = context.Process(
            target=run_ai_sync_process,
            args=(config, messages),
            name="pylrcget-ai-sync",
        )
        process.start()
        try:
            while True:
                try:
                    message = messages.get(timeout=0.1)
                except queue.Empty:
                    if self.isInterruptionRequested():
                        process.terminate()
                        process.join(timeout=2.0)
                        self.completed.emit(False, "Cancelled.", "")
                        return
                    if not process.is_alive():
                        break
                    continue
                if message[0] == "progress":
                    self.progress.emit(str(message[1]))
                elif message[0] == "completed":
                    self.completed.emit(bool(message[1]), str(message[2]), str(message[3]))
                    process.join(timeout=2.0)
                    return

            if self.isInterruptionRequested():
                self.completed.emit(False, "Cancelled.", "")
            elif process.exitcode:
                self.completed.emit(
                    False,
                    f"AI sync process exited unexpectedly (code {process.exitcode}).",
                    "",
                )
        finally:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2.0)
            messages.close()

    def _run_in_process(self) -> None:
        from .ai_sync_pipeline import run_ai_sync_pipeline

        run_ai_sync_pipeline(
            self,
            align_optional_demucs=_align_with_optional_demucs,
        )


__all__ = [
    "AiSyncWorker",
    "AlignmentCandidate",
    "_align_with_optional_demucs",
    "_align_lyrics_to_segments",
    "_align_lyrics_to_segments_viterbi",
    "_approximate_word_timestamps_from_segments",
    "_transcribe_tail_window",
    "_transcribe_fixed_windows",
    "_align_segments_per_chunks",
    "_should_use_per_chunk_alignment",
    "_build_same_phrase_rewind_targets",
    "_build_speech_candidate_mask",
    "_build_guided_word_ranges",
    "_build_lrc_from_segments",
    "_build_lrc_from_plain_lines_and_segments",
    "_check_ai_sync_available",
    "_clear_inference_caches",
    "_get_cached_align_model",
    "_get_cached_whisperx_model",
    "_format_ts",
    "_normalized_transcribe_language",
    "_prepare_manual_line_anchors",
    "_late_line_expected_position_bonus",
    "_late_line_candidate_start_floor",
    "_segment_alignment_quality",
    "_segment_reliable_tail_seconds",
    "_segment_tail_seconds",
    "_tail_rescue_forward_jump_indices",
    "_tail_rescue_collapsed_cluster_indices",
    "_repair_repeated_prefix_timestamp_gaps",
    "_should_retry_with_short_windows",
    "_find_targeted_retry_window",
    "_should_use_relaxed_vad_result",
    "_should_retry_with_relaxed_vad",
    "_select_best_relaxed_segments",
    "_tail_rescue_alignment_indices",
    "_tail_rescue_rewind_target_lag_indices",
    "_ensure_strictly_increasing_alignment_indices",
    "get_missing_ai_dependencies",
]
