"""AI synchronization orchestration, independent from the Qt subprocess boundary."""
from __future__ import annotations

import logging
from pathlib import Path

from .ai_sync_alignment import (
    _align_lyrics_to_segments,
    _align_lyrics_to_segments_viterbi,
    _repair_repeated_prefix_timestamp_gaps,
)
from .ai_sync_demucs import (
    AlignmentCandidate,
)
from .ai_sync_demucs import (
    candidate_quality as _demucs_candidate_quality,
)
from .ai_sync_demucs import (
    is_available as _demucs_available,
)
from .ai_sync_demucs import (
    separated_vocal_audio as _separated_vocal_audio,
)
from .ai_sync_lrc import (
    _build_lrc_from_segments,
    _format_ts,
)
from .ai_sync_language import detect_text_language
from .ai_sync_lyrics_aligner import align as _align_with_lyrics_aligner
from .ai_sync_lyrics_aligner import is_available as _lyrics_aligner_available
from .ai_sync_runtime import (
    _check_ai_sync_available,
    _get_cached_align_model,
    _get_cached_whisperx_model,
    _patch_whisperx_audio_loading,
    _preferred_whisper_compute_type,
)
from .ai_sync_router import build_default_router
from .ai_sync_transcription import (
    _align_segments_per_chunks,
    _approximate_word_timestamps_from_segments,
    _find_targeted_retry_window,
    _normalized_transcribe_language,
    _segment_tail_seconds,
    _select_best_relaxed_segments,
    _should_retry_with_relaxed_vad,
    _should_retry_with_short_windows,
    _should_use_per_chunk_alignment,
    _transcribe_fixed_windows,
)

logger = logging.getLogger(__name__)
_DEMUCS_QUALITY_GATE = 14.0
_BACKEND_ROUTER = build_default_router()


def _select_alignment_backend(language: str | None, *, device: str):
    return _BACKEND_ROUTER.select(
        language,
        device=device,
        available_backends={"lyrics-aligner": _lyrics_aligner_available()},
    )


def align_with_optional_demucs(
    audio_path: str,
    plain_lyrics: str,
    *,
    device: str,
    enable_demucs_candidate: bool,
    aligner=_align_with_lyrics_aligner,
    demucs_available=_demucs_available,
    separated_audio=_separated_vocal_audio,
    quality=_demucs_candidate_quality,
) -> AlignmentCandidate:
    """Align the mix and optionally select a higher-quality Demucs candidate."""
    mix_lrc = aligner(audio_path, plain_lyrics, device=device)
    mix = AlignmentCandidate(
        lrc=mix_lrc, source="mix", quality=quality(mix_lrc, plain_lyrics)
    )
    if not enable_demucs_candidate or not mix.lrc.strip() or not demucs_available():
        return mix
    if mix.quality >= _DEMUCS_QUALITY_GATE:
        logger.info(
            "Skipping Demucs candidate because mix quality is already high (%.2f).",
            mix.quality,
        )
        return mix

    with separated_audio(audio_path, device=device) as vocal_path:
        vocal_lrc = aligner(vocal_path, plain_lyrics, device=device)
    if not vocal_lrc.strip():
        return mix

    vocal = AlignmentCandidate(
        lrc=vocal_lrc, source="Demucs vocal", quality=quality(vocal_lrc, plain_lyrics)
    )
    if vocal.quality > mix.quality + 0.5:
        logger.info(
            "Selected Demucs vocal candidate (quality %.2f vs mix %.2f).",
            vocal.quality,
            mix.quality,
        )
        return vocal
    logger.info(
        "Kept original mix candidate (quality %.2f vs Demucs %.2f).",
        mix.quality,
        vocal.quality,
    )
    return mix


def _try_lyrics_aligner(
    worker,
    *,
    device: str,
    stage: int,
    stage_message: str,
    fallback_stage: int | None = None,
    fallback_message: str | None = None,
    empty_message: str | None = None,
    router=align_with_optional_demucs,
) -> AlignmentCandidate | None:
    """Run the configured English aligner once and centralize fallback handling."""
    if not _lyrics_aligner_available():
        return None
    worker._emit_stage(stage, 8, stage_message)
    try:
        candidate = router(
            worker.audio_path,
            worker.plain_lyrics,
            device=device,
            enable_demucs_candidate=worker._enable_demucs_candidate,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("lyrics-aligner failed; falling back to WhisperX: %s", exc)
        if fallback_stage is not None and fallback_message:
            worker._emit_stage(fallback_stage, 8, fallback_message)
        return None
    if candidate.lrc.strip():
        return candidate
    logger.warning("lyrics-aligner returned no aligned lyric lines; using WhisperX.")
    if fallback_stage is not None:
        message = empty_message or fallback_message
        if message:
            worker._emit_stage(fallback_stage, 8, message)
    return None


def _complete_with_lyrics_aligner(worker, candidate: AlignmentCandidate) -> None:
    worker._emit_stage(8, 8, "Finalizing lyrics-aligner result…")
    worker.completed.emit(
        True,
        "Lyrics synchronized successfully with lyrics-aligner "
        f"({candidate.source}).",
        candidate.lrc,
    )


def run_ai_sync_pipeline(self, *, align_optional_demucs=None) -> None:
    if align_optional_demucs is None:
        align_optional_demucs = align_with_optional_demucs
    try:
        ok, msg = _check_ai_sync_available()
        if not ok:
            self.completed.emit(False, msg, "")
            return

        device = self._resolve_device()
        total_steps = 8
        self._emit_stage(1, total_steps, f"Loading audio file ({Path(self.audio_path).name})…")
        if self.isInterruptionRequested():
            self.completed.emit(False, "Cancelled.", "")
            return

        plain_lines = self.plain_lyrics.splitlines() if self.plain_lyrics else []
        lyrics_aligner_attempted = False
        transcribe_language = _normalized_transcribe_language(self._language)
        text_detection = (
            detect_text_language(self.plain_lyrics)
            if plain_lines and transcribe_language is None
            else None
        )
        if text_detection is not None and text_detection.language is not None:
            transcribe_language = text_detection.language
        if (
            plain_lines
            and transcribe_language == "en"
            and _select_alignment_backend(transcribe_language, device=device).backend_name
            == "lyrics-aligner"
        ):
            lyrics_aligner_attempted = True
            candidate = _try_lyrics_aligner(
                self,
                device=device,
                stage=2,
                stage_message="English selected — lyrics-aligner phonetic alignment…",
                fallback_stage=2,
                fallback_message="lyrics-aligner failed — loading WhisperX fallback…",
                router=align_optional_demucs,
            )
            if candidate is not None:
                _complete_with_lyrics_aligner(self, candidate)
                return

        import whisperx

        compute_type = _preferred_whisper_compute_type(device)
        self._emit_stage(
            2,
            total_steps,
            f"Loading WhisperX ASR ({self.whisper_model}, device: {device}, "
            f"compute: {compute_type})…",
        )
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
        language_label = transcribe_language or "auto-detect"
        detected_language = transcribe_language

        def _transcribe_and_align(
            model_obj,
            *,
            pass_label: str,
            fixed_window_s: float = 60.0,
            fixed_step_s: float = 45.0,
        ):
            self._emit_stage(
                3,
                total_steps,
                f"WhisperX transcription ({pass_label}, language: {language_label}, "
                f"device: {device})…",
            )
            if transcribe_language is None:
                result_local = model_obj.transcribe(audio)
            else:
                result_local = model_obj.transcribe(audio, language=transcribe_language)
            nonlocal detected_language
            detected_language = transcribe_language or _normalized_transcribe_language(
                result_local.get("language")
            )

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
                    window_s=fixed_window_s,
                    step_s=fixed_step_s,
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

            self._emit_stage(
                4,
                total_steps,
                f"WhisperX forced alignment ({pass_label}, language: "
                f"{chunk_language or 'auto'})…",
            )
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
            except Exception as e:  # noqa: BLE001
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
                    except Exception as e2:  # noqa: BLE001
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

        if plain_lines and not lyrics_aligner_attempted:
            if transcribe_language == "en":
                detected_language = "en"
            elif transcribe_language is None:
                self._emit_stage(
                    3,
                    total_steps,
                    f"WhisperX language detection only (device: {device})…",
                )
                try:
                    detection = model.transcribe(audio)
                    detected_language = _normalized_transcribe_language(
                        detection.get("language")
                    )
                except (RuntimeError, TypeError, ValueError) as exc:
                    logger.warning("Language detection failed; continuing with WhisperX: %s", exc)

            if (
                _select_alignment_backend(detected_language, device=device).backend_name
                == "lyrics-aligner"
            ):
                lyrics_aligner_attempted = True
                candidate = _try_lyrics_aligner(
                    self,
                    device=device,
                    stage=4,
                    stage_message="English detected — lyrics-aligner phonetic alignment…",
                    router=align_optional_demucs,
                )
                if candidate is not None:
                    _complete_with_lyrics_aligner(self, candidate)
                    return
                if _lyrics_aligner_available():
                    self.completed.emit(
                        False,
                        "English lyrics-aligner failed; WhisperX was not used as a fallback.",
                        "",
                    )
                    return

        segments = _transcribe_and_align(model, pass_label="base pass")
        selected_language = (detected_language or "unknown").lower()
        self._emit_stage(
            5,
            total_steps,
            f"Detected language: {selected_language}. "
            f"Selecting English lyrics-aligner or WhisperX fallback…",
        )
        if plain_lines and selected_language == "en" and not _lyrics_aligner_available():
            self._emit_stage(
                5,
                total_steps,
                "English detected, but lyrics-aligner is not configured — using WhisperX…",
            )
        targeted_window = _find_targeted_retry_window(segments, plain_lines)
        if targeted_window is not None:
            logger.info(
                "Detected repeated lyrics near an ASR gap; targeted retry window: %.2fs-%.2fs.",
                targeted_window[0],
                targeted_window[1],
            )
        if device != "cuda" and _should_retry_with_short_windows(segments):
            logger.info(
                "Detected a long low-density ASR segment; retrying with short windows."
            )
            segments = _transcribe_and_align(
                model,
                pass_label="short-window retry",
                fixed_window_s=30.0,
                fixed_step_s=20.0,
            )
        self._emit_stage(5, total_steps, "Checking speech coverage and selecting best pass…")
        if _should_retry_with_relaxed_vad(audio, segments, plain_lines):
            duration_s = float(len(audio)) / 16000.0 if hasattr(audio, "__len__") else 0.0
            relaxed_vad_configs = (
                ({"vad_onset": 0.15, "vad_offset": 0.05},)
                if device == "cuda"
                else (
                    {"vad_onset": 0.15, "vad_offset": 0.05},
                    {"vad_onset": 0.10, "vad_offset": 0.03},
                    {"vad_onset": 0.02, "vad_offset": 0.01},
                )
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
            except Exception as e:  # noqa: BLE001
                logger.warning("Viterbi alignment failed, falling back to greedy: %s", e)
                raw = _align_lyrics_to_segments(
                    plain_lines,
                    segments,
                    enable_fuzzy=self._enable_fuzzy,
                    fuzzy_threshold=self._fuzzy_threshold,
                    fuzzy_window_words=self._fuzzy_window_words,
                )
            raw = _repair_repeated_prefix_timestamp_gaps(raw)
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
                except Exception:  # noqa: BLE001, S112
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
        logger.exception("AI sync failed")
        self.completed.emit(False, f"AI sync failed: {exc}", "")

__all__ = ["AlignmentCandidate", "align_with_optional_demucs", "run_ai_sync_pipeline"]
