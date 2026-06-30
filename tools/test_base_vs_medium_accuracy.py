#!/usr/bin/env python3
"""
Benchmark WhisperX base vs medium model on accuracy.
Uses ground truth from previous benchmarks.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

TEST_AUDIO_DIR = Path(r"C:\Users\andrvoicu\Downloads\music_test")

# Test tracks
TEST_TRACKS = [
    ("House of Sleep", "House of Sleep"),
    ("Keelhauled", "Keelhauled"),
    ("Nancy the Tavern Wench", "Nancy the Tavern Wench"),
    ("See You in Hell (acoustic)", "See You in Hell (acoustic)"),
    ("Upside Down", "Upside Down"),
]

def find_audio_file(track_name: str) -> str:
    """Find audio file for a track."""
    for ext in [".mp3", ".wav", ".m4a", ".flac"]:
        path = TEST_AUDIO_DIR / f"{track_name}{ext}"
        if path.exists():
            return str(path)
    return ""

def load_ground_truth(track_name: str) -> list[tuple[float, str]]:
    """Load ground truth from reference LRC file."""
    lrc_path = TEST_AUDIO_DIR / f"{track_name}.lrc"
    if not lrc_path.exists():
        return []

    tuples = []
    for line in lrc_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("[") and "]" in line:
            try:
                end = line.index("]")
                ts = line[1:end]
                mm, rest = ts.split(":")
                ss, cs = rest.split(".")
                seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
                text = line[end+1:].strip().lower()
                if text:
                    tuples.append((seconds, text))
            except Exception:
                pass
    return tuples

def test_track(track_name: str, model: str) -> dict:
    """Test a single track with given model."""
    import whisperx
    import soundfile as sf
    import numpy as np
    from scipy import signal

    audio_file = find_audio_file(track_name)
    if not audio_file:
        return {"error": f"Audio not found"}

    ground_truth = load_ground_truth(track_name)
    if not ground_truth:
        return {"error": f"No ground truth LRC"}

    print(f"  {model}: loading audio & model...")

    try:
        # Load audio
        audio_data, sr = sf.read(audio_file)
        if sr != 16000:
            num_samples = int(len(audio_data) * 16000 / sr)
            audio_data = signal.resample(audio_data, num_samples)
        if len(audio_data.shape) > 1:
            audio_data = audio_data.mean(axis=1)
        audio_data = audio_data.astype(np.float32)

        start_total = time.time()

        # Load model
        start_load = time.time()
        model_obj = whisperx.load_model(
            model,
            device="cuda",
            compute_type="float16",
        )
        load_time = time.time() - start_load

        # Transcribe
        start_transcribe = time.time()
        result = model_obj.transcribe(audio_data, language="en")
        transcribe_time = time.time() - start_transcribe

        # Align
        language = result.get("language", "en")
        if language == "auto":
            language = "en"
        align_model, metadata = whisperx.load_align_model(language_code=language, device="cuda")
        result = whisperx.align(result["segments"], align_model, metadata, audio_data, "cuda")
        segments = result.get("segments", [])

        total_time = time.time() - start_total

        # Compute accuracy vs ground truth
        errors = []
        matched = 0
        for seg in segments:
            text = seg.get("text", "").strip().lower()
            start = seg.get("start", 0.0)
            
            # Find matching ground truth entry
            for gt_ts, gt_text in ground_truth:
                if gt_text in text or text in gt_text:
                    error = abs(start - gt_ts)
                    errors.append(error)
                    matched += 1
                    break

        if not errors:
            mean_error = float("inf")
            median_error = float("inf")
        else:
            import numpy as np
            mean_error = float(np.mean(errors))
            median_error = float(np.median(errors))

        return {
            "total_time": total_time,
            "load_time": load_time,
            "transcribe_time": transcribe_time,
            "matched": matched,
            "total": len(segments),
            "mean_error": mean_error,
            "median_error": median_error,
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

def main():
    import torch
    print("=" * 70)
    print("WhisperX: base vs medium accuracy benchmark")
    print("=" * 70)
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA: {torch.cuda.is_available()}\n")

    results = {"base": {}, "medium": {}}

    for track_label, track_name in TEST_TRACKS:
        print(f"\n{'=' * 70}")
        print(f"Testing: {track_label}")
        print("=" * 70)

        for model in ["base", "medium"]:
            res = test_track(track_name, model)
            results[model][track_name] = res

            if "error" in res:
                print(f"    {model}: ERROR - {res['error'][:50]}")
            else:
                time_s = res.get("total_time", 0)
                mean_err = res.get("mean_error", 0)
                median_err = res.get("median_error", 0)
                matched = res.get("matched", 0)
                total = res.get("total", 0)
                print(
                    f"    {model}: time={time_s:.1f}s, matched={matched}/{total}, "
                    f"mean_err={mean_err:.1f}s, median_err={median_err:.1f}s"
                )

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY - WhisperX base vs medium (Accuracy)")
    print("=" * 70)
    print(f"{'Track':<35} {'Base Error':<20} {'Medium Error':<20} {'Delta':<15}")
    print("-" * 70)

    for track_label, track_name in TEST_TRACKS:
        base_res = results["base"].get(track_name, {})
        med_res = results["medium"].get(track_name, {})

        base_err = base_res.get("mean_error", float("inf"))
        med_err = med_res.get("mean_error", float("inf"))

        if isinstance(base_err, float) and isinstance(med_err, float) and base_err != float("inf"):
            delta = (med_err - base_err) / base_err * 100 if base_err > 0 else 0
            print(
                f"{track_label:<35} {base_err:>8.2f}s       {med_err:>8.2f}s       {delta:>6.1f}%"
            )
        else:
            print(f"{track_label:<35} ERROR")

    # Average
    base_errors = [
        results["base"][tn].get("mean_error")
        for _, tn in TEST_TRACKS
        if isinstance(results["base"].get(tn, {}).get("mean_error"), float)
    ]
    med_errors = [
        results["medium"][tn].get("mean_error")
        for _, tn in TEST_TRACKS
        if isinstance(results["medium"].get(tn, {}).get("mean_error"), float)
    ]

    if base_errors and med_errors:
        import numpy as np
        avg_base = np.mean(base_errors)
        avg_med = np.mean(med_errors)
        avg_delta = (avg_med - avg_base) / avg_base * 100
        print("-" * 70)
        print(
            f"{'AVERAGE':<35} {avg_base:>8.2f}s       {avg_med:>8.2f}s       {avg_delta:>6.1f}%"
        )

    # Save results
    output_file = (
        Path(__file__).parent / "whisperx_test_output" / "base_vs_medium_accuracy.json"
    )
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved to {output_file}")

if __name__ == "__main__":
    main()
