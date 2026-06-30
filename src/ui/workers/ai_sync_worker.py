"""
AI-powered lyrics synchronization worker.

Pipeline: WhisperX transcription (with forced alignment) → LRC generation.

Requires optional dependencies: torch, torchaudio, soundfile, whisperx.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


def get_missing_ai_dependencies() -> list[str]:
    deps = [
        ("torch", "torch"),
        ("torchaudio", "torchaudio"),
        ("soundfile", "soundfile"),
        ("whisperx", "whisperx"),
    ]
    missing: list[str] = []
    for module, package in deps:
        if not _module_available(module):
            missing.append(package)
    return missing


def _module_available(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def _check_ai_sync_available() -> tuple[bool, str]:
    """Check whether the required AI sync dependencies are installed."""
    missing = get_missing_ai_dependencies()
    if missing:
        return False, (
            f"Missing AI dependencies: {', '.join(missing)}.\n\n"
            "If you run PyLrcGet from source, install them in that environment:\n"
            "  pip install .[ai]\n\n"
            "If you use the packaged .exe, install these packages in the app's bundled Python "
            "(installing into system Python is not enough)."
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


def _postprocess_lrc_tuples(lrc_tuples: list[tuple[float,str]], *, max_shift: float = 6.0, median_cutoff: float = 20.0) -> list[tuple[float,str]]:
    """Post-process (smooth) list of (start_seconds, text) tuples.

    Strategy:
    - Ensure monotonic increasing starts
    - Compute a robust median of inter-line diffs (excluding huge outliers)
    - Clamp large deviations: if a line is offset from expected by > max_shift, snap it to expected
    - Spread blocks of identical timestamps evenly using median spacing
    """
    if not lrc_tuples:
        return lrc_tuples

    # Work on a copy
    vals = [(float(s), t) for s, t in lrc_tuples]
    # Sort by start to be safe
    vals.sort(key=lambda x: x[0])
    starts = [s for s, _ in vals]
    texts = [t for _, t in vals]

    # Compute diffs and median excluding tiny/huge values
    diffs = []
    for i in range(1, len(starts)):
        d = starts[i] - starts[i-1]
        if 0.05 <= d <= median_cutoff:
            diffs.append(d)
    import statistics
    median_diff = statistics.median(diffs) if diffs else 3.0
    # clamp reasonable bounds
    if median_diff < 0.1:
        median_diff = 0.5

    # Enforce monotonic and clamp large jumps
    new_starts = [starts[0]]
    for i in range(1, len(starts)):
        prev = new_starts[-1]
        cur = starts[i]
        expected = prev + median_diff
        # if current is too far ahead, clamp to expected
        if cur - expected > max_shift:
            cur = expected
        # if current is behind previous (non-monotonic), nudge forward
        if cur <= prev + 0.001:
            cur = prev + max(0.01, median_diff * 0.05)
        new_starts.append(cur)

    # Now detect blocks having identical timestamps (or near-equal) and spread them
    final_starts = new_starts.copy()
    i = 0
    n = len(final_starts)
    while i < n:
        # find run of nearly-equal starts
        j = i + 1
        while j < n and abs(final_starts[j] - final_starts[j-1]) < 0.02:
            j += 1
        run_len = j - i
        if run_len > 1:
            # spread across median_diff spacing starting at final_starts[i]
            base = final_starts[i]
            for k in range(run_len):
                final_starts[i + k] = base + k * (median_diff * 0.9)
        i = j

    # Pair back with texts
    smoothed = [(s, t) for s, t in zip(final_starts, texts)]
    return smoothed


def _align_lyrics_to_segments(
    plain_lines: list[str],
    segments: list[dict],
    *,
    enable_fuzzy: bool = False,
    fuzzy_threshold: int = 60,
    fuzzy_window_words: int = 12,
) -> str:
    """
    Align provided plain lyrics lines to word timestamps.

    Two modes:
    - Greedy (original): compare first few words with windowed words
    - Fuzzy (optional): use rapidfuzz to score a sliding window of words and pick best match

    Returns LRC text.
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

    # Try to import rapidfuzz if fuzzy matching requested
    fuzz = None
    if enable_fuzzy:
        try:
            from rapidfuzz import fuzz as _fuzz
            fuzz = _fuzz
        except Exception:
            fuzz = None

    lrc_lines: list[str] = []
    word_idx = 0

    for line in plain_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        line_words = line_stripped.split()
        if not line_words:
            continue

        # Define search window end
        search_end = min(
            len(words),
            word_idx + len(words) // max(1, len(plain_lines)) + len(line_words) * 3,
        )

        # If fuzzy available, search by sliding window and use partial_ratio
        if fuzz is not None:
            best_idx = None
            best_score = -1
            # window size heuristic
            base_window = max(fuzzy_window_words, len(line_words) * 2)
            for i in range(word_idx, search_end):
                window_end = min(len(words), i + base_window)
                if window_end <= i:
                    continue
                wtext = " ".join(w.get("word", "") for w in words[i:window_end])
                try:
                    score = fuzz.partial_ratio(line_stripped, wtext)
                except Exception:
                    score = 0
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_score >= fuzzy_threshold and best_idx is not None:
                start = words[best_idx].get("start", 0.0)
                ts = _format_ts(start)
                lrc_lines.append(f"[{ts}] {line_stripped}")
                word_idx = min(best_idx + len(line_words), len(words))
                continue
            # else fall through to greedy

        # Greedy fallback (original behavior)
        best_idx = word_idx
        best_score = -1
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
            word_idx = min(best_idx + len(line_words), len(words))
        else:
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
    completed = Signal(bool, str, str)  # ok, message, lrc_text

    def __init__(
        self,
        audio_path: str,
        plain_lyrics: str = "",
        *,
        whisper_model: str = "base",
        device: str = "auto",
        enable_fuzzy: bool = True,
        fuzzy_threshold: int = 60,
        fuzzy_window_words: int = 12,
        parent=None,
    ):
        super().__init__(parent)
        self.audio_path = audio_path
        self.plain_lyrics = (plain_lyrics or "").strip()
        self.whisper_model = whisper_model or "base"
        self._device = device
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

    def run(self):
        vocals_path = None
        try:
            ok, msg = _check_ai_sync_available()
            if not ok:
                self.completed.emit(False, msg, "")
                return

            import torch
            import whisperx

            device = self._resolve_device()

            self.progress.emit("Loading audio...")
            if self.isInterruptionRequested():
                self.completed.emit(False, "Cancelled.", "")
                return

            self.progress.emit("Loading WhisperX model...")
            model = whisperx.load_model(
                self.whisper_model,
                device=device,
                compute_type="float16" if device == "cuda" else "int8",
            )
            if self.isInterruptionRequested():
                self.completed.emit(False, "Cancelled.", "")
                return

            self.progress.emit("Transcribing audio...")
            audio = whisperx.load_audio(self.audio_path)
            result = model.transcribe(audio, language="auto")

            self.progress.emit("Performing alignment (forced alignment)...")
            language = result.get("language", "en")
            align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
            result = whisperx.align(result["segments"], align_model, metadata, audio, device)
            segments = result.get("segments", [])

            self.progress.emit("Building LRC output...")

            plain_lines = [l for l in self.plain_lyrics.splitlines() if l.strip()] if self.plain_lyrics else []

            if plain_lines:
                # produce tuples first so we can post-process smoothing
                lrc_tuples = []
                raw = _align_lyrics_to_segments(
                    plain_lines,
                    segments,
                    enable_fuzzy=self._enable_fuzzy,
                    fuzzy_threshold=self._fuzzy_threshold,
                    fuzzy_window_words=self._fuzzy_window_words,
                )
                # raw is LRC string; parse into tuples
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
                        text = ln[end+1:].strip()
                        lrc_tuples.append((seconds, text))
                    except Exception:
                        continue
                # Postprocess smoothing to remove large outliers/drift
                smoothed = _postprocess_lrc_tuples(lrc_tuples)
                # Format back to lrc
                lrc = "\n".join(f"[{_format_ts(s)}] {t}" for s, t in smoothed)
            else:
                lrc = _build_lrc_from_segments(segments)

            if not lrc.strip():
                self.completed.emit(False, "Could not generate synced lyrics — no speech detected.", "")
                return

            self.completed.emit(True, "Lyrics synchronized successfully.", lrc)

        except Exception as exc:
            logger.error("AI sync failed: %s", exc, exc_info=True)
            self.completed.emit(False, f"AI sync failed: {exc}", "")
        finally:
            if vocals_path and os.path.isfile(vocals_path):
                try:
                    os.unlink(vocals_path)
                except OSError:
                    pass


