"""Qt orchestrator for AI-powered lyrics synchronization."""
from __future__ import annotations

import logging
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
    _tail_rescue_alignment_indices,
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
    _select_best_relaxed_segments,
    _should_retry_with_relaxed_vad,
    _should_use_per_chunk_alignment,
    _should_use_relaxed_vad_result,
    _transcribe_fixed_windows,
    _transcribe_tail_window,
)

logger = logging.getLogger(__name__)


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
        try:
            ok, msg = _check_ai_sync_available()
            if not ok:
                self.completed.emit(False, msg, "")
                return

            import torch
            import whisperx

            device = self._resolve_device()
            total_steps = 8
            self._emit_stage(1, total_steps, f"Loading audio file ({Path(self.audio_path).name})…")
            if self.isInterruptionRequested():
                self.completed.emit(False, "Cancelled.", "")
                return

            self._emit_stage(2, total_steps, f"Loading ASR model ({self.whisper_model}, {device})…")
            compute_type = "float16" if device == "cuda" else "int8"
            model = _get_cached_whisperx_model(
                whisperx,
                self.whisper_model,
                device=device,
                compute_type=compute_type,
            )
            if self.isInterruptionRequested():
                self.completed.emit(False, "Cancelled.", "")
                return

            _patch_whisperx_audio_loading()
            audio = whisperx.load_audio(self.audio_path)
            transcribe_language = _normalized_transcribe_language(self._language)
            language_label = transcribe_language or "auto-detect"

            def _transcribe_and_align(model_obj, *, pass_label: str):
                self._emit_stage(
                    3,
                    total_steps,
                    f"Transcribing audio ({pass_label}, language: {language_label})…",
                )
                if transcribe_language is None:
                    result_local = model_obj.transcribe(audio)
                else:
                    result_local = model_obj.transcribe(audio, language=transcribe_language)

                audio_duration = float(len(audio)) / 16000.0 if hasattr(audio, "__len__") else 0.0
                raw_segments = [dict(segment) for segment in result_local.get("segments", [])]
                used_chunked_segments = False
                raw_tail = max(
                    (float(seg.get("end", 0.0)) for seg in raw_segments if seg.get("end") is not None),
                    default=0.0,
                )
                chunk_language = transcribe_language or _normalized_transcribe_language(
                    result_local.get("language")
                )
                if audio_duration - raw_tail >= 20.0:
                    chunked_segments = _transcribe_fixed_windows(
                        model_obj,
                        audio,
                        duration_s=audio_duration,
                        language=chunk_language,
                    )
                    if len(chunked_segments) > len(raw_segments):
                        raw_segments = chunked_segments
                        used_chunked_segments = True
                        result_local["segments"] = raw_segments
                        logger.warning(
                            "ASR coverage ended at %.2fs of %.2fs; using %d fixed-window segments.",
                            raw_tail,
                            audio_duration,
                            len(raw_segments),
                        )

                self._emit_stage(4, total_steps, f"Aligning detected words to audio ({pass_label})…")
                raw_tail = max(
                    (float(seg.get("end", 0.0)) for seg in raw_segments if seg.get("end") is not None),
                    default=0.0,
                )
                language = transcribe_language or result_local.get("language", "en")
                if language == "auto":
                    language = "en"

                alignment_device = device
                try:
                    align_model, metadata = _get_cached_align_model(
                        whisperx,
                        language_code=str(language),
                        device=alignment_device,
                    )
                    if used_chunked_segments:
                        globally_aligned = whisperx.align(
                            result_local["segments"],
                            align_model,
                            metadata,
                            audio,
                            alignment_device,
                        ).get("segments", [])
                        if _should_use_per_chunk_alignment(raw_segments, globally_aligned):
                            aligned = _align_segments_per_chunks(
                                whisperx,
                                result_local["segments"],
                                align_model,
                                metadata,
                                audio,
                                alignment_device,
                            )
                            result_local = {"segments": aligned}
                        else:
                            result_local = {"segments": globally_aligned}
                    else:
                        result_local = whisperx.align(
                            result_local["segments"],
                            align_model,
                            metadata,
                            audio,
                            alignment_device,
                        )
                except Exception as e:
                    if alignment_device != "cpu":
                        logger.warning("Alignment on %s failed, retrying on CPU: %s", alignment_device, e)
                        try:
                            align_model, metadata = _get_cached_align_model(
                                whisperx,
                                language_code=str(language),
                                device="cpu",
                            )
                            if used_chunked_segments:
                                aligned = _align_segments_per_chunks(
                                    whisperx,
                                    raw_segments,
                                    align_model,
                                    metadata,
                                    audio,
                                    "cpu",
                                )
                                result_local = {"segments": aligned}
                            else:
                                result_local = whisperx.align(
                                    result_local["segments"],
                                    align_model,
                                    metadata,
                                    audio,
                                    "cpu",
                                )
                        except Exception as e2:
                            logger.warning("CPU alignment also failed, using raw segments: %s", e2)
                    else:
                        logger.warning("CPU alignment failed, using raw segments: %s", e)
                aligned_segments = result_local.get("segments", [])
                aligned_tail = _segment_tail_seconds(aligned_segments)
                if raw_tail - aligned_tail >= 12.0:
                    recovered_segments = _approximate_word_timestamps_from_segments(raw_segments)
                    if recovered_segments:
                        logger.warning(
                            "Forced alignment lost %.2fs of ASR coverage; using coarse segment word timings.",
                            raw_tail - aligned_tail,
                        )
                        return recovered_segments
                return aligned_segments

            segments = _transcribe_and_align(model, pass_label="base pass")
            plain_lines = self.plain_lyrics.splitlines() if self.plain_lyrics else []
            self._emit_stage(5, total_steps, "Checking speech coverage and selecting best pass…")
            if _should_retry_with_relaxed_vad(audio, segments, plain_lines):
                duration_s = float(len(audio)) / 16000.0 if hasattr(audio, "__len__") else 0.0
                relaxed_vad_configs = (
                    {"vad_onset": 0.15, "vad_offset": 0.05},
                    {"vad_onset": 0.10, "vad_offset": 0.03},
                    {"vad_onset": 0.02, "vad_offset": 0.01},
                )
                relaxed_candidates: list[list[dict]] = []
                for idx, vad_options in enumerate(relaxed_vad_configs, start=1):
                    self._emit_stage(
                        5,
                        total_steps,
                        f"Low coverage detected — running relaxed VAD retry "
                        f"({idx}/{len(relaxed_vad_configs)}, onset {vad_options['vad_onset']:.2f})…",
                    )
                    relaxed_model = _get_cached_whisperx_model(
                        whisperx,
                        self.whisper_model,
                        device=device,
                        compute_type=compute_type,
                        vad_method="pyannote",
                        vad_options=vad_options,
                    )
                    relaxed_candidates.append(
                        _transcribe_and_align(
                            relaxed_model,
                            pass_label=f"relaxed VAD pass (onset {vad_options['vad_onset']:.2f})",
                        )
                    )
                best_relaxed = _select_best_relaxed_segments(
                    segments, relaxed_candidates, plain_lines, duration_s
                )
                if best_relaxed is not None:
                    logger.info(
                        "Using relaxed VAD result (tail %.2fs -> %.2fs).",
                        _segment_tail_seconds(segments),
                        _segment_tail_seconds(best_relaxed),
                    )
                    segments = best_relaxed

            self._emit_stage(6, total_steps, "Building synced LRC output…")
            if plain_lines:
                lrc_tuples = []
                if self.manual_anchors:
                    self._emit_stage(
                        7,
                        total_steps,
                        f"Aligning lyric lines (using {len(self.manual_anchors)} manual anchor hint(s))…",
                    )
                else:
                    self._emit_stage(7, total_steps, "Aligning lyric lines to word timestamps…")
                try:
                    raw = _align_lyrics_to_segments_viterbi(
                        plain_lines,
                        segments,
                        manual_anchors=self.manual_anchors,
                    )
                except Exception as e:
                    logger.warning("Viterbi alignment failed, falling back to greedy: %s", e)
                    raw = _align_lyrics_to_segments(
                        plain_lines,
                        segments,
                        enable_fuzzy=self._enable_fuzzy,
                        fuzzy_threshold=self._fuzzy_threshold,
                        fuzzy_window_words=self._fuzzy_window_words,
                    )
                for ln in raw.splitlines():
                    ln = ln.strip()
                    if not ln or not ln.startswith("["):
                        continue
                    try:
                        end = ln.index("]")
                        ts = ln[1:end]
                        mm, rest = ts.split(":")
                        ss, cs = rest.split(".")
                        seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
                        text = ln[end + 1:].strip()
                        lrc_tuples.append((seconds, text))
                    except Exception:
                        continue
                lrc = "\n".join(f"[{_format_ts(s)}] {t}" for s, t in lrc_tuples)
            else:
                self._emit_stage(
                    7,
                    total_steps,
                    "No plain lyrics provided — using segment-level timestamps…",
                )
                lrc = _build_lrc_from_segments(segments)

            self._emit_stage(8, total_steps, "Finalizing AI sync result…")
            if not lrc.strip():
                self.completed.emit(False, "Could not generate synced lyrics — no speech detected.", "")
                return
            self.completed.emit(True, "Lyrics synchronized successfully.", lrc)
        except Exception as exc:
            logger.error("AI sync failed: %s", exc, exc_info=True)
            self.completed.emit(False, f"AI sync failed: {exc}", "")


__all__ = [
    "AiSyncWorker",
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
    "_should_use_relaxed_vad_result",
    "_should_retry_with_relaxed_vad",
    "_select_best_relaxed_segments",
    "_tail_rescue_alignment_indices",
    "_tail_rescue_rewind_target_lag_indices",
    "_ensure_strictly_increasing_alignment_indices",
    "get_missing_ai_dependencies",
]
