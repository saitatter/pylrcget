"""
AI-powered lyrics synchronization worker.

Pipeline: Demucs (vocal separation) → Whisper (transcription + word timestamps) → LRC generation.

Requires optional dependencies: torch, demucs, openai-whisper
These are NOT bundled with the app — users must install them separately.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


def _check_ai_sync_available() -> tuple[bool, str]:
    """Check whether the required AI sync dependencies are installed."""
    missing: list[str] = []
    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("torch")
    try:
        import demucs  # noqa: F401
    except ImportError:
        missing.append("demucs")
    try:
        import whisper  # noqa: F401
    except ImportError:
        missing.append("openai-whisper")
    if missing:
        return False, (
            f"Missing dependencies: {', '.join(missing)}.\n\n"
            "Install them with:\n"
            "  pip install torch demucs openai-whisper"
        )
    return True, ""


def is_ai_sync_available() -> bool:
    ok, _ = _check_ai_sync_available()
    return ok


def _format_ts(seconds: float) -> str:
    """Format seconds as mm:ss.xx for LRC."""
    if seconds < 0:
        seconds = 0
    total_cs = int(round(seconds * 100))
    m = total_cs // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{m:02d}:{s:02d}.{cs:02d}"


def _build_lrc_from_segments(segments: list[dict]) -> str:
    """Build LRC text from WhisperX segments (line-level timestamps)."""
    lines: list[str] = []
    for seg in segments:
        start = seg.get("start", 0.0)
        text = seg.get("text", "").strip()
        if not text:
            continue
        ts = _format_ts(start)
        lines.append(f"[{ts}] {text}")
    return "\n".join(lines)


def _align_lyrics_to_segments(
    plain_lines: list[str],
    segments: list[dict],
) -> str:
    """
    Align provided plain lyrics lines to WhisperX word timestamps.

    Strategy: for each plain lyrics line, find the best matching segment
    by text similarity and assign its start time.
    """
    if not segments:
        return ""

    # Collect all words with timestamps
    words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []):
            if "start" in w and w.get("word", "").strip():
                words.append(w)

    if not words:
        # Fall back to segment-level timestamps
        return _build_lrc_from_segments(segments)

    # Simple greedy alignment: walk through words and match to lines
    lrc_lines: list[str] = []
    word_idx = 0

    for line in plain_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        line_words = line_stripped.split()
        if not line_words:
            continue

        # Find the best starting position for this line's words
        best_idx = word_idx
        best_score = -1

        # Search in a window ahead
        search_end = min(len(words), word_idx + len(words) // max(1, len(plain_lines)) + len(line_words) * 3)
        for i in range(word_idx, search_end):
            score = 0
            for j, lw in enumerate(line_words[:5]):  # compare first 5 words
                if i + j < len(words):
                    wt = words[i + j].get("word", "").strip().lower()
                    wt = wt.strip(".,!?;:\"'()-")
                    lw_clean = lw.lower().strip(".,!?;:\"'()-")
                    if wt == lw_clean:
                        score += 2
                    elif lw_clean in wt or wt in lw_clean:
                        score += 1
            if score > best_score:
                best_score = score
                best_idx = i

        # Use the timestamp of the matched word
        if best_idx < len(words):
            start = words[best_idx].get("start", 0.0)
            ts = _format_ts(start)
            lrc_lines.append(f"[{ts}] {line_stripped}")
            # Advance word_idx past this line's words
            word_idx = min(best_idx + len(line_words), len(words))
        else:
            # No more words — use last known timestamp
            last_start = words[-1].get("start", 0.0) if words else 0.0
            ts = _format_ts(last_start)
            lrc_lines.append(f"[{ts}] {line_stripped}")

    return "\n".join(lrc_lines)


class AiSyncWorker(QThread):
    """
    Worker thread for AI-powered lyrics synchronization.

    Takes an audio file path and optional plain lyrics,
    produces synced LRC lyrics using Demucs + WhisperX.
    """

    progress = Signal(str)  # status message
    finished = Signal(bool, str, str)  # ok, message, lrc_text

    def __init__(
        self,
        audio_path: str,
        plain_lyrics: str = "",
        *,
        whisper_model: str = "base",
        device: str = "auto",
        parent=None,
    ):
        super().__init__(parent)
        self.audio_path = audio_path
        self.plain_lyrics = (plain_lyrics or "").strip()
        self.whisper_model = whisper_model or "base"
        self._device = device

    def _resolve_device(self) -> str:
        import torch
        if self._device and self._device != "auto":
            return self._device
        return "cuda" if torch.cuda.is_available() else "cpu"

    def run(self):
        try:
            ok, msg = _check_ai_sync_available()
            if not ok:
                self.finished.emit(False, msg, "")
                return

            import torch
            import whisper

            device = self._resolve_device()

            self.progress.emit("Separating vocals with Demucs...")
            vocals_path = self._separate_vocals(device)

            audio_input = vocals_path or self.audio_path

            self.progress.emit("Loading Whisper model...")
            model = whisper.load_model(
                self.whisper_model,
                device=device,
            )

            self.progress.emit("Transcribing audio...")
            audio_np = self._load_audio_as_numpy(audio_input)
            result = model.transcribe(
                audio_np,
                word_timestamps=True,
            )
            segments = result.get("segments", [])

            # Clean up temporary vocals file
            if vocals_path and os.path.isfile(vocals_path):
                try:
                    os.unlink(vocals_path)
                except OSError:
                    pass

            self.progress.emit("Building LRC output...")

            plain_lines = [l for l in self.plain_lyrics.splitlines() if l.strip()] if self.plain_lyrics else []

            if plain_lines:
                lrc = _align_lyrics_to_segments(plain_lines, segments)
            else:
                lrc = _build_lrc_from_segments(segments)

            if not lrc.strip():
                self.finished.emit(False, "Could not generate synced lyrics — no speech detected.", "")
                return

            self.finished.emit(True, "Lyrics synchronized successfully.", lrc)

        except Exception as exc:
            logger.error("AI sync failed: %s", exc, exc_info=True)
            self.finished.emit(False, f"AI sync failed: {exc}", "")

    @staticmethod
    def _load_audio_as_numpy(path: str):
        """Load audio file via soundfile and return float32 numpy array at 16 kHz mono (Whisper format)."""
        import soundfile as sf
        import torch
        import torchaudio.functional as F

        data, sr = sf.read(path, dtype="float32")  # [samples] or [samples, channels]
        if data.ndim > 1:
            data = data.mean(axis=1)  # mono
        # Resample to 16 kHz (Whisper expects 16 kHz)
        if sr != 16000:
            tensor = torch.from_numpy(data).unsqueeze(0)
            tensor = F.resample(tensor, sr, 16000)
            data = tensor.squeeze(0).numpy()
        return data

    def _separate_vocals(self, device: str) -> str | None:
        """Run Demucs vocal separation, return path to vocals WAV or None on failure."""
        try:
            from demucs.apply import apply_model
            from demucs.pretrained import get_model
            import soundfile as sf
            import torch
            import torchaudio.functional as F

            self.progress.emit("Loading Demucs model...")
            model = get_model("htdemucs")
            model.to(device)

            self.progress.emit("Separating vocals...")
            data, sr = sf.read(self.audio_path, dtype="float32")  # [samples, channels]
            if data.ndim == 1:
                data = data[:, None]  # [samples, 1]
            wav = torch.from_numpy(data.T).float()  # [channels, samples]
            # Resample to model's sample rate if needed
            if sr != model.samplerate:
                wav = F.resample(wav, sr, model.samplerate)
            # Ensure correct number of channels
            if wav.shape[0] != model.audio_channels:
                if model.audio_channels == 1:
                    wav = wav.mean(0, keepdim=True)
                else:
                    wav = wav.repeat(model.audio_channels, 1)[:model.audio_channels]
            ref = wav.mean(0)
            wav = (wav - ref.mean()) / ref.std()
            wav = wav.to(device)

            with torch.no_grad():
                sources = apply_model(model, wav[None], progress=False)[0]

            # Demucs htdemucs sources order: drums, bass, other, vocals
            sources = sources.cpu()
            vocals = sources[-1]  # vocals is the last source
            vocals = vocals * ref.std() + ref.mean()

            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            sf.write(tmp.name, vocals.numpy().T, model.samplerate)

            self.progress.emit("Vocal separation complete.")
            return tmp.name

        except Exception as exc:
            logger.warning("Demucs vocal separation failed, proceeding with full mix: %s", exc)
            self.progress.emit("Vocal separation skipped, using full audio...")
            return None
