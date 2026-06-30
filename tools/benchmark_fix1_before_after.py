#!/usr/bin/env python3
"""
Benchmark: Before vs After fix #1 (normalized punctuation matching).
Tests alignment accuracy on 2 tracks.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

TEST_AUDIO_DIR = Path(r"C:\Users\andrvoicu\Downloads\music_test")
TEST_TRACKS = ["Keelhauled", "Upside Down"]

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

def test_track(track_name: str) -> dict:
    """Test track with CURRENT implementation (already has fix)."""
    import whisperx
    import soundfile as sf
    import numpy as np
    from scipy import signal

    audio_file = find_audio_file(track_name)
    if not audio_file:
        return {"error": "No audio"}

    try:
        # Load audio
        audio_data, sr = sf.read(audio_file)
        if sr != 16000:
            num_samples = int(len(audio_data) * 16000 / sr)
            audio_data = signal.resample(audio_data, num_samples)
        if len(audio_data.shape) > 1:
            audio_data = audio_data.mean(axis=1)
        audio_data = audio_data.astype(np.float32)

        start = time.time()

        # Transcribe + align
        model_obj = whisperx.load_model("base", device="cuda", compute_type="float16")
        result = model_obj.transcribe(audio_data, language="en")
        language = result.get("language", "en")
        if language == "auto":
            language = "en"
        align_model, metadata = whisperx.load_align_model(language_code=language, device="cuda")
        result = whisperx.align(result["segments"], align_model, metadata, audio_data, "cuda")
        segments = result.get("segments", [])

        total_time = time.time() - start

        # Extract words
        words_pred = []
        for seg in segments:
            text = seg.get("text", "").strip()
            start_ts = seg.get("start", 0.0)
            if text:
                words_pred.append((start_ts, text))

        # Load GT and compute error
        words_gt = load_ground_truth_words(track_name)
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

        return {
            "total_time": total_time,
            "words_pred": len(words_pred),
            "words_gt": len(words_gt),
            "errors_matched": len(errors),
            "mean_error": mean_err,
            "median_error": median_err,
        }

    except Exception as e:
        return {"error": str(e)[:100]}

def main():
    print("=" * 80)
    print("BENCHMARK: Normalized Punctuation Fix (Fix #1)")
    print("=" * 80)
    print("\nComparing alignment accuracy AFTER fix:\n")

    results = {}

    for track in TEST_TRACKS:
        print(f"{track}:")
        res = test_track(track)

        if "error" in res:
            print(f"  ERROR: {res['error']}")
        else:
            mean_err = res.get("mean_error", 0)
            median_err = res.get("median_error", 0)
            t = res.get("total_time", 0)
            print(f"  Mean error:   {mean_err:.2f}s")
            print(f"  Median error: {median_err:.2f}s")
            print(f"  Time:         {t:.1f}s\n")

        results[track] = res

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    all_errors = []
    for track in TEST_TRACKS:
        err = results[track].get("mean_error")
        if isinstance(err, float) and err != float("inf"):
            all_errors.append(err)
    
    if all_errors:
        import numpy as np
        avg = np.mean(all_errors)
        print(f"\nAverage mean error: {avg:.2f}s")
        print("\nBefore fix (from previous benchmark):")
        print("  Keelhauled: 45.8s")
        print("  Upside Down: 54.3s")
        print("  Average: 50.0s")
        print("\nAfter fix #1 (normalized punctuation):")
        for track in TEST_TRACKS:
            err = results[track].get("mean_error", "N/A")
            if isinstance(err, float):
                print(f"  {track}: {err:.1f}s")
        print(f"  Average: {avg:.1f}s")
        delta = (avg - 50.0) / 50.0 * 100
        print(f"\nImprovement: {delta:.1f}%")

    # Save
    out = Path(__file__).parent / "whisperx_test_output" / "fix1_before_after.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[*] Saved to {out}")

if __name__ == "__main__":
    main()
