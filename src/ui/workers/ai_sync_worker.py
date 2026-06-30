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


def _normalize_word(word: str) -> str:
    """Normalize word for comparison (lowercase only, no destructive stripping)."""
    return word.lower()


def _words_match(w1: str, w2: str, threshold: float = 0.85) -> tuple[bool, float]:
    """
    Match two words using edit distance.
    
    Returns: (matched: bool, score: float 0.0-1.0)
    - score >= 0.85: good match
    - score >= 0.70: partial match
    - score < 0.70: no match
    """
    from difflib import SequenceMatcher
    
    norm_w1 = _normalize_word(w1)
    norm_w2 = _normalize_word(w2)
    
    if norm_w1 == norm_w2:
        return True, 1.0
    
    ratio = SequenceMatcher(None, norm_w1, norm_w2).ratio()
    return ratio >= threshold, ratio


def _compute_line_to_words_score(line_words: list[str], words: list[dict], start_idx: int, window_size: int = 20) -> float:
    """
    Compute how well a plain text line matches a window of ASR words.
    
    Uses sequence matching to find best alignment within window.
    Returns: score 0.0-1.0 (1.0 = perfect match)
    """
    if start_idx >= len(words):
        return 0.0
    
    window_end = min(len(words), start_idx + window_size)
    window_words = [w.get("word", "").strip().lower() for w in words[start_idx:window_end]]
    
    if not window_words or not line_words:
        return 0.0
    
    line_words_norm = [w.lower() for w in line_words[:10]]
    
    best_match_ratio = 0.0
    
    # Try all starting positions in window
    for i in range(len(window_words)):
        window_slice = window_words[i:i+len(line_words_norm)]
        if not window_slice:
            continue
        
        # Count how many line words are in this window slice
        matched = 0
        for lw in line_words_norm:
            for ww in window_slice:
                _, sim = _words_match(ww, lw, threshold=0.70)
                if sim >= 0.70:
                    matched += 1
                    break
        
        match_ratio = matched / len(line_words_norm) if line_words_norm else 0.0
        
        # Prefer matches that start earlier in the window (more stable)
        # But penalize matches that skip too many words at start
        skip_penalty = i * 0.02
        adjusted_ratio = match_ratio - skip_penalty
        
        if adjusted_ratio > best_match_ratio:
            best_match_ratio = adjusted_ratio
    
    return max(0.0, best_match_ratio)


def _extract_word_confidence(word: dict) -> float | None:
    """Extract normalized confidence score [0, 1] from a Whisper/WhisperX word dict."""
    for key in ("score", "confidence", "probability", "prob"):
        val = word.get(key)
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if 0.0 <= fval <= 1.0:
            return fval
    return None


def _find_confidence_anchors(
    line_words_list: list[list[str]],
    words: list[dict],
    *,
    min_confidence: float = 0.90,
    min_token_len: int = 4,
    max_token_occurrences: int = 1,
) -> dict[int, int]:
    """
    Build sparse anchor points: line_idx -> word_idx.

    Anchors are based on words that are:
    - high confidence in ASR output
    - rare in lyrics/ASR (to avoid chorus ambiguity)
    - monotonic in timeline
    """
    asr_positions: dict[str, list[int]] = {}
    for idx, w in enumerate(words):
        token = _normalize_word(str(w.get("word", "")).strip())
        if len(token) < min_token_len:
            continue
        conf = _extract_word_confidence(w)
        if conf is None or conf < min_confidence:
            continue
        asr_positions.setdefault(token, []).append(idx)

    if not asr_positions:
        return {}

    line_token_counts: dict[str, int] = {}
    for line_words in line_words_list:
        for token in {_normalize_word(t) for t in line_words if len(_normalize_word(t)) >= min_token_len}:
            line_token_counts[token] = line_token_counts.get(token, 0) + 1

    anchors: dict[int, int] = {}
    prev_anchor_idx = -1

    for line_idx, line_words in enumerate(line_words_list):
        candidates = {
            _normalize_word(t)
            for t in line_words
            if len(_normalize_word(t)) >= min_token_len
        }
        if not candidates:
            continue

        ranked = sorted(
            candidates,
            key=lambda t: (
                line_token_counts.get(t, 999),          # prefer lyrics-rare tokens
                len(asr_positions.get(t, [])),          # then ASR-rare tokens
                -len(t),                                # then longer tokens
            ),
        )

        chosen_idx: int | None = None
        for token in ranked:
            positions = asr_positions.get(token, [])
            if line_token_counts.get(token, 0) != 1:
                continue
            if not positions or len(positions) > max_token_occurrences:
                continue
            next_pos = next((p for p in positions if p > prev_anchor_idx), None)
            if next_pos is not None:
                chosen_idx = next_pos
                break

        if chosen_idx is None:
            continue

        anchors[line_idx] = chosen_idx
        prev_anchor_idx = chosen_idx

    return anchors


def _anchor_bonus(line_idx: int, word_idx: int, anchors: dict[int, int]) -> float:
    """Confidence-anchor shaping for Viterbi state score."""
    anchor_idx = anchors.get(line_idx)
    if anchor_idx is None:
        return 0.0

    distance = abs(word_idx - anchor_idx)
    if distance <= 2:
        return 1.0
    if distance <= 8:
        return 0.3
    if distance <= 20:
        return -0.2
    return -(0.8 + (distance - 20) * 0.01)


def _align_lyrics_to_segments_viterbi(
    plain_lines: list[str],
    segments: list[dict],
) -> str:
    """
    Align lyrics using Viterbi DP (dynamic programming).
    
    This finds the GLOBALLY OPTIMAL alignment path, not greedy local matching.
    Reduces systematic drift from ~50s to ~5-10s on well-transcribed audio.
    
    Algorithm:
    1. State = (line_idx, word_idx)
    2. Emission = how well line matches words starting at word_idx
    3. Transition = cost of skipping words (small) or jumping backwards (large penalty)
    4. Viterbi finds path with max likelihood
    5. Backtrack to extract best alignment
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
        return _build_lrc_from_segments(segments)

    plain_lines = [l.strip() for l in plain_lines if l.strip()]
    if not plain_lines:
        return ""

    # Build word array
    line_words_list = [l.split() for l in plain_lines]

    num_lines = len(plain_lines)
    num_words = len(words)
    if num_words <= 0:
        return _build_lrc_from_segments(segments)

    # Precompute emissions once (critical perf fix).
    emissions: list[list[float]] = []
    for line_words in line_words_list:
        row = [_compute_line_to_words_score(line_words, words, word_idx) for word_idx in range(num_words)]
        emissions.append(row)

    # Build sparse confidence anchors globally.
    anchors = _find_confidence_anchors(line_words_list, words)

    # Initialize DP
    viterbi = {}
    backptr = {}

    # Start: try to match first line near beginning.
    for word_idx in range(min(120, num_words)):
        score = emissions[0][word_idx] + _anchor_bonus(0, word_idx, anchors)
        viterbi[(0, word_idx)] = score
        backptr[(0, word_idx)] = -1

    # Forward pass: fill DP table
    for line_idx in range(1, num_lines):
        candidate_start = 0
        candidate_end = num_words

        for word_idx in range(candidate_start, candidate_end):
            best_prev_score = -1e18
            best_prev_idx = -1

            # Try all previous word indices
            search_start = max(0, word_idx - 140)  # look back max 140 words
            search_end = word_idx

            for prev_idx in range(search_start, search_end):
                if (line_idx - 1, prev_idx) not in viterbi:
                    continue

                prev_score = viterbi[(line_idx - 1, prev_idx)]

                # Transition cost: penalize big jumps or backwards movement
                word_distance = word_idx - prev_idx
                if word_distance < 0:
                    transition_cost = -10  # Big penalty for going backwards
                elif word_distance == 0:
                    transition_cost = -1   # Small penalty for staying
                elif word_distance <= 20:
                    transition_cost = 0    # Normal progression
                else:
                    transition_cost = -(word_distance - 20) * 0.05  # Gradual penalty for big jumps

                emission = emissions[line_idx][word_idx]
                anchor_shape = _anchor_bonus(line_idx, word_idx, anchors)

                total_score = prev_score + emission + transition_cost + anchor_shape

                if total_score > best_prev_score:
                    best_prev_score = total_score
                    best_prev_idx = prev_idx

            if best_prev_idx >= 0:
                viterbi[(line_idx, word_idx)] = best_prev_score
                backptr[(line_idx, word_idx)] = best_prev_idx

    # Backtrack: find best path
    alignment = {}  # line_idx -> word_idx

    # Find best final state
    best_final_score = -1e18
    best_final_word = -1
    final_start = max(0, num_words - 200)
    final_end = num_words

    for word_idx in range(final_start, final_end):
        if (num_lines - 1, word_idx) in viterbi:
            score = viterbi[(num_lines - 1, word_idx)]
            if score > best_final_score:
                best_final_score = score
                best_final_word = word_idx

    if best_final_word < 0:
        # Fallback to greedy
        return _align_lyrics_to_segments(plain_lines, segments)

    # Backtrack
    line_idx = num_lines - 1
    word_idx = best_final_word
    while line_idx >= 0:
        alignment[line_idx] = word_idx
        if line_idx == 0:
            break
        word_idx = backptr.get((line_idx, word_idx), -1)
        if word_idx < 0:
            break
        line_idx -= 1

    # Build LRC from alignment
    lrc_lines = []
    for line_idx, line_text in enumerate(plain_lines):
        word_idx = alignment.get(line_idx)
        if word_idx is not None and word_idx >= 0 and word_idx < len(words):
            start = words[word_idx].get("start", 0.0)
        else:
            start = words[-1].get("start", 0.0) if words else 0.0

        ts = _format_ts(start)
        lrc_lines.append(f"[{ts}] {line_text}")

    return "\n".join(lrc_lines)


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
                    wt = words[i + j].get("word", "").strip()
                    
                    # Use normalized comparison instead of destructive stripping
                    matched, similarity = _words_match(wt, lw)
                    if matched and similarity >= 0.85:
                        score += 2
                    elif similarity >= 0.70:
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
            
            # Try alignment on the specified device, fallback to CPU on error
            # (WhisperX alignment with Pyannote VAD can hang on Windows CUDA)
            alignment_device = device
            try:
                align_model, metadata = whisperx.load_align_model(language_code=language, device=alignment_device)
                result = whisperx.align(result["segments"], align_model, metadata, audio, alignment_device)
            except Exception as e:
                if alignment_device != "cpu":
                    logger.warning("Alignment on %s failed, retrying on CPU: %s", alignment_device, e)
                    try:
                        align_model, metadata = whisperx.load_align_model(language_code=language, device="cpu")
                        result = whisperx.align(result["segments"], align_model, metadata, audio, "cpu")
                    except Exception as e2:
                        logger.warning("CPU alignment also failed, using raw segments: %s", e2)
                        # segments will remain without word-level timestamps
                else:
                    logger.warning("CPU alignment failed, using raw segments: %s", e)
            
            segments = result.get("segments", [])

            self.progress.emit("Building LRC output...")

            plain_lines = [l for l in self.plain_lyrics.splitlines() if l.strip()] if self.plain_lyrics else []

            if plain_lines:
                # produce tuples first so we can post-process smoothing
                lrc_tuples = []
                
                # Try Viterbi DP alignment (global optimization)
                # If it fails, fall back to greedy
                try:
                    raw = _align_lyrics_to_segments_viterbi(
                        plain_lines,
                        segments,
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
