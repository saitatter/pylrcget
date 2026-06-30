#!/usr/bin/env python3
"""
Benchmark WhisperX base vs medium accuracy - simplified version.
Measures alignment error directly on segments vs ground truth.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

TEST_AUDIO_DIR = Path(r"C:\Users\andrvoicu\Downloads\music_test")

TEST_TRACKS = [
    "Keelhauled",
    "Upside Down",
]

def find_audio_file(track_name: str) -> str:
    for ext in [".mp3", ".wav", ".m4a", ".flac"]:
        path = TEST_AUDIO_DIR / f"{track_name}{ext}"
        if path.exists():
            return str(path)
    return ""

def load_ground_truth_words(track_name: str) -> list[tuple[float, str]]:
    """Load word-level ground truth from .lrc file."""
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

def test_model(track_name: str, model: str) -> dict:
    """Test single track with given model."""
    import whisperx
    import soundfile as sf
    import numpy as np
    from scipy import signal

    audio_file = find_audio_file(track_name)
    if not audio_file:
        return {"error": "No audio"}

    print(f"    {model}: transcribing...")
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
        model_obj = whisperx.load_model(model, device="cuda", compute_type="float16")
        result = model_obj.transcribe(audio_data, language="en")
        language = result.get("language", "en")
        if language == "auto":
            language = "en"
        align_model, metadata = whisperx.load_align_model(language_code=language, device="cuda")
        result = whisperx.align(result["segments"], align_model, metadata, audio_data, "cuda")
        segments = result.get("segments", [])

        total_time = time.time() - start

        # Extract word-level timestamps from segments
        words_predicted = []
        for seg in segments:
            text = seg.get("text", "").strip()
            start_ts = seg.get("start", 0.0)
            if text:
                words_predicted.append((start_ts, text))

        # Load ground truth
        words_gt = load_ground_truth_words(track_name)

        # Compute error (simple: match first N words)
        errors = []
        for i, (pred_ts, pred_text) in enumerate(words_predicted[:len(words_gt)]):
            if i < len(words_gt):
                gt_ts, gt_text = words_gt[i]
                error = abs(pred_ts - gt_ts)
                errors.append(error)

        if errors:
            import numpy as np
            mean_err = float(np.mean(errors))
            median_err = float(np.median(errors))
            p95_err = float(np.percentile(errors, 95))
        else:
            mean_err = median_err = p95_err = float("inf")

        return {
            "total_time": total_time,
            "words_predicted": len(words_predicted),
            "words_gt": len(words_gt),
            "errors_matched": len(errors),
            "mean_error": mean_err,
            "median_error": median_err,
            "p95_error": p95_err,
        }

    except Exception as e:
        return {"error": str(e)}

def main():
    import torch
    print("=" * 80)
    print("WhisperX: base vs medium - ACCURACY BENCHMARK")
    print("=" * 80)
    print(f"CUDA: {torch.cuda.is_available()}\n")

    results = {}

    for track in TEST_TRACKS:
        print(f"\n{'=' * 80}")
        print(f"Track: {track}")
        print("=" * 80)

        results[track] = {}

        for model in ["base", "medium"]:
            res = test_model(track, model)
            results[track][model] = res

            if "error" in res:
                print(f"    ERROR: {res['error']}")
            else:
                t = res.get("total_time", 0)
                mean = res.get("mean_error", 0)
                median = res.get("median_error", 0)
                p95 = res.get("p95_error", 0)
                print(
                    f"    OK time={t:.1f}s | mean_error={mean:.1f}s | "
                    f"median={median:.1f}s | p95={p95:.1f}s"
                )

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY - Accuracy Comparison")
    print("=" * 80)
    print(f"{'Track':<25} {'Base Mean':<15} {'Medium Mean':<15} {'Better':<10}")
    print("-" * 80)

    for track in TEST_TRACKS:
        base = results.get(track, {}).get("base", {})
        medium = results.get(track, {}).get("medium", {})

        base_mean = base.get("mean_error", float("inf"))
        med_mean = medium.get("mean_error", float("inf"))

        if isinstance(base_mean, float) and isinstance(med_mean, float):
            if base_mean == float("inf") or med_mean == float("inf"):
                better = "ERROR"
            elif base_mean < med_mean:
                delta = (med_mean - base_mean) / base_mean * 100
                better = f"base ({delta:+.1f}%)"
            else:
                delta = (med_mean - base_mean) / base_mean * 100
                better = f"medium ({delta:+.1f}%)"

            print(
                f"{track:<25} {base_mean:>8.2f}s      {med_mean:>8.2f}s      {better:<10}"
            )

    # Save
    out = Path(__file__).parent / "whisperx_test_output" / "base_vs_medium_accuracy_final.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[*] Saved to {out}")

if __name__ == "__main__":
    main()
