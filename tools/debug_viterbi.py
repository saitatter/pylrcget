#!/usr/bin/env python3
"""
Benchmark: Viterbi DP alignment test with debug output.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

TEST_AUDIO_DIR = Path(r"C:\Users\andrvoicu\Downloads\music_test")
TEST_TRACKS = ["Keelhauled"]

def find_audio_file(track_name: str) -> str:
    for ext in [".mp3", ".wav", ".m4a", ".flac"]:
        path = TEST_AUDIO_DIR / f"{track_name}{ext}"
        if path.exists():
            return str(path)
    return ""

def load_ground_truth_words(track_name: str) -> list[tuple[float, str]]:
    lrc_path = TEST_AUDIO_DIR / f"{track_name}.lrc"
    if not lrc_path.exists():
        return []
    words = []
    for line in lrc_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("[") and "]" in line:
            try:
                end = line.index("]")
                ts = line[1:end]
                mm, rest = ts.split(":")
                ss, cs = rest.split(".")
                seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
                text = line[end+1:].strip()
                if text:
                    words.append((seconds, text))
            except Exception:
                pass
    return words

def test_track_debug(track_name: str) -> dict:
    """Test track with debug output."""
    import whisperx
    import soundfile as sf
    import numpy as np
    from scipy import signal

    audio_file = find_audio_file(track_name)
    if not audio_file:
        return {"error": "No audio"}

    try:
        print(f"\n[1] Loading audio...")
        audio_data, sr = sf.read(audio_file)
        if sr != 16000:
            num_samples = int(len(audio_data) * 16000 / sr)
            audio_data = signal.resample(audio_data, num_samples)
        if len(audio_data.shape) > 1:
            audio_data = audio_data.mean(axis=1)
        audio_data = audio_data.astype(np.float32)
        print(f"    Audio loaded: {len(audio_data)} samples")

        print(f"[2] Transcribing with WhisperX...")
        model_obj = whisperx.load_model("base", device="cuda", compute_type="float16")
        result = model_obj.transcribe(audio_data, language="en")
        print(f"    Transcribed: {len(result.get('segments', []))} segments")
        
        language = result.get("language", "en")
        if language == "auto":
            language = "en"
        
        print(f"[3] Aligning with forced alignment...")
        align_model, metadata = whisperx.load_align_model(language_code=language, device="cuda")
        result = whisperx.align(result["segments"], align_model, metadata, audio_data, "cuda")
        segments = result.get("segments", [])
        
        # Count words in segments
        total_words = sum(len(seg.get("words", [])) for seg in segments)
        print(f"    Aligned: {total_words} words")

        print(f"[4] Running Viterbi alignment...")
        from ui.workers.ai_sync_worker import _align_lyrics_to_segments_viterbi
        
        # Load plain lyrics
        txt_path = TEST_AUDIO_DIR / f"{track_name}.txt"
        if txt_path.exists():
            plain_lyrics = txt_path.read_text()
        else:
            # Use ground truth
            lrc_path = TEST_AUDIO_DIR / f"{track_name}.lrc"
            plain_lyrics = "\n".join([text for _, text in load_ground_truth_words(track_name)])
        
        plain_lines = [l.strip() for l in plain_lyrics.splitlines() if l.strip()]
        print(f"    Plain lyrics: {len(plain_lines)} lines")
        
        lrc_output = _align_lyrics_to_segments_viterbi(plain_lines, segments)
        print(f"    Viterbi output: {len(lrc_output.splitlines())} lines")
        print(f"[5] Computing accuracy...")

        # Parse output
        words_pred = []
        for line in lrc_output.splitlines():
            line = line.strip()
            if line.startswith("[") and "]" in line:
                try:
                    end = line.index("]")
                    ts = line[1:end]
                    mm, rest = ts.split(":")
                    ss, cs = rest.split(".")
                    seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
                    text = line[end+1:].strip()
                    words_pred.append((seconds, text))
                except Exception:
                    pass

        words_gt = load_ground_truth_words(track_name)
        print(f"    Predicted: {len(words_pred)} lines, GT: {len(words_gt)} lines")

        # Compute error
        errors = []
        for i, (pred_ts, pred_text) in enumerate(words_pred[:len(words_gt)]):
            if i < len(words_gt):
                gt_ts, gt_text = words_gt[i]
                error = abs(pred_ts - gt_ts)
                errors.append(error)

        if errors:
            import numpy as np
            mean_err = float(np.mean(errors))
            median_err = float(np.median(errors))
        else:
            mean_err = median_err = float("inf")

        print(f"\nRESULT:")
        print(f"  Mean error: {mean_err:.2f}s")
        print(f"  Median error: {median_err:.2f}s")

        return {
            "mean_error": mean_err,
            "median_error": median_err,
        }

    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        print(traceback.format_exc())
        return {"error": str(e)}

if __name__ == "__main__":
    print("=" * 80)
    print("DEBUG: Viterbi DP Alignment Test")
    print("=" * 80)
    
    test_track_debug("Keelhauled")
