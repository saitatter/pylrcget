#!/usr/bin/env python3
"""
Comprehensive investigation: test all Whisper models + compute types.
Goal: Find best accuracy configuration for AI sync.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

TEST_AUDIO_DIR = Path(r"C:\Users\andrvoicu\Downloads\music_test")

# Focus on 2 test tracks for speed
TEST_TRACKS = ["Keelhauled", "Upside Down"]

# All available models
MODELS = ["tiny", "base", "small", "medium", "large"]

# Compute types to test
COMPUTE_TYPES = ["float16", "int8", "float32"]

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

def test_config(track_name: str, model: str, compute_type: str) -> dict:
    """Test single configuration."""
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
        try:
            model_obj = whisperx.load_model(
                model,
                device="cuda",
                compute_type=compute_type,
            )
        except Exception as e:
            if "compute_type" in str(e) or "not supported" in str(e):
                return {"error": f"compute_type {compute_type} not supported for {model}"}
            raise

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
            "mean_error": mean_err,
            "median_error": median_err,
        }

    except Exception as e:
        return {"error": str(e)[:100]}

def main():
    print("=" * 90)
    print("MODEL INVESTIGATION: Testing all Whisper models + compute types for accuracy")
    print("=" * 90)
    print(f"Models: {MODELS}")
    print(f"Compute types: {COMPUTE_TYPES}")
    print(f"Tracks: {TEST_TRACKS}\n")

    results = {}

    for track in TEST_TRACKS:
        print(f"\n{'=' * 90}")
        print(f"Track: {track}")
        print("=" * 90)
        results[track] = {}

        for model in MODELS:
            print(f"\n  Model: {model}")
            results[track][model] = {}

            for compute_type in COMPUTE_TYPES:
                print(f"    compute_type={compute_type}...", end=" ", flush=True)
                res = test_config(track, model, compute_type)

                if "error" in res:
                    print(f"SKIP ({res['error'][:40]})")
                    results[track][model][compute_type] = {"error": res["error"]}
                else:
                    mean_err = res.get("mean_error", 0)
                    t = res.get("total_time", 0)
                    print(f"OK (mean={mean_err:.1f}s, time={t:.1f}s)")
                    results[track][model][compute_type] = res

    # Summary
    print("\n" + "=" * 90)
    print("SUMMARY - Best configurations per track")
    print("=" * 90)

    for track in TEST_TRACKS:
        print(f"\n{track}:")
        print("-" * 90)
        print(f"{'Model':<10} {'Compute':<12} {'Time':<10} {'Mean Error':<15} {'Median':<15}")
        print("-" * 90)

        best_error = float("inf")
        best_config = None

        for model in MODELS:
            for compute_type in COMPUTE_TYPES:
                res = results.get(track, {}).get(model, {}).get(compute_type, {})
                if "error" in res:
                    continue

                mean_err = res.get("mean_error", float("inf"))
                median_err = res.get("median_error", float("inf"))
                t = res.get("total_time", 0)

                if mean_err != float("inf"):
                    print(f"{model:<10} {compute_type:<12} {t:>8.1f}s  {mean_err:>8.1f}s (p50={median_err:.1f}s)")

                    if mean_err < best_error:
                        best_error = mean_err
                        best_config = (model, compute_type, mean_err, t)

        if best_config:
            model, ct, err, t = best_config
            print("-" * 90)
            print(f"BEST: {model} + {ct} = {err:.1f}s error (time={t:.1f}s)")

    # Save
    out = Path(__file__).parent / "whisperx_test_output" / "model_investigation.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[*] Saved to {out}")

if __name__ == "__main__":
    main()
