#!/usr/bin/env python3
"""
Benchmark WhisperX base vs medium model on test tracks.
Measures load time, transcribe time, total time, and alignment accuracy.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

TEST_AUDIO_DIR = Path(r"C:\Users\andrvoicu\Downloads\music_test")
PLAIN_LYRICS_DIR = TEST_AUDIO_DIR

# Specific test tracks with plain lyrics
TEST_TRACKS = [
    ("House of Sleep", "House of Sleep"),
    ("Keelhauled", "Keelhauled"),
    ("Nancy the Tavern Wench", "Nancy the Tavern Wench"),
    ("See You in Hell (acoustic)", "See You in Hell (acoustic)"),
    ("Upside Down", "Upside Down"),
]

def load_plain_lyrics(track_name: str) -> str:
    """Load plain lyrics for a track."""
    for ext in [".txt", ".lrc"]:
        path = PLAIN_LYRICS_DIR / f"{track_name}{ext}"
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
    return ""

def find_audio_file(track_name: str) -> str:
    """Find audio file for a track."""
    for ext in [".mp3", ".wav", ".m4a", ".flac"]:
        path = TEST_AUDIO_DIR / f"{track_name}{ext}"
        if path.exists():
            return str(path)
    return ""

def compute_error(lrc_text: str, reference_lrc_path: str) -> float:
    """Compute mean absolute error vs reference LRC."""
    ref_times = {}
    if Path(reference_lrc_path).exists():
        with open(reference_lrc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and "]" in line:
                    try:
                        end = line.index("]")
                        ts = line[1:end]
                        mm, rest = ts.split(":")
                        ss, cs = rest.split(".")
                        seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
                        text = line[end+1:].strip()
                        ref_times[text] = seconds
                    except Exception:
                        pass

    # Parse generated LRC
    gen_times = {}
    for line in lrc_text.splitlines():
        line = line.strip()
        if line.startswith("[") and "]" in line:
            try:
                end = line.index("]")
                ts = line[1:end]
                mm, rest = ts.split(":")
                ss, cs = rest.split(".")
                seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
                text = line[end+1:].strip()
                gen_times[text] = seconds
            except Exception:
                pass

    # Compare
    errors = []
    for text, gen_sec in gen_times.items():
        if text in ref_times:
            errors.append(abs(gen_sec - ref_times[text]))

    return sum(errors) / len(errors) if errors else float("inf")


def compute_error_from_segments(segments: list, reference_lrc_path: str) -> float:
    """Compute mean absolute error from WhisperX segments vs reference LRC."""
    ref_times = {}
    if Path(reference_lrc_path).exists():
        with open(reference_lrc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and "]" in line:
                    try:
                        end = line.index("]")
                        ts = line[1:end]
                        mm, rest = ts.split(":")
                        ss, cs = rest.split(".")
                        seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
                        text = line[end+1:].strip()
                        ref_times[text.lower()] = seconds
                    except Exception:
                        pass

    errors = []
    for seg in segments:
        text = seg.get("text", "").strip().lower()
        start = seg.get("start", 0.0)
        if text in ref_times:
            errors.append(abs(start - ref_times[text]))

    return sum(errors) / len(errors) if errors else float("inf")

def test_track(track_name: str, model: str) -> dict:
    """Test a single track with given model."""
    audio_file = find_audio_file(track_name)
    if not audio_file:
        return {"error": f"Audio not found: {track_name}"}

    plain_lyrics = load_plain_lyrics(track_name)
    if not plain_lyrics:
        return {"error": f"Plain lyrics not found: {track_name}"}

    print(f"\n  Testing {model}: {track_name}")

    try:
        import whisperx
        import soundfile as sf
        import numpy as np

        # Load audio manually
        audio_data, sr = sf.read(audio_file)
        if sr != 16000:
            from scipy import signal
            num_samples = int(len(audio_data) * 16000 / sr)
            audio_data = signal.resample(audio_data, num_samples)
        if len(audio_data.shape) > 1:
            audio_data = audio_data.mean(axis=1)
        audio_data = audio_data.astype(np.float32)

        start_total = time.time()

        print(f"    Loading model {model}...")
        start_load = time.time()
        model_obj = whisperx.load_model(
            model,
            device="cuda",
            compute_type="float16",
        )
        load_time = time.time() - start_load

        print(f"    Transcribing...")
        start_transcribe = time.time()
        result = model_obj.transcribe(audio_data, language="en")
        transcribe_time = time.time() - start_transcribe

        print(f"    Aligning...")
        language = result.get("language", "en")
        if language == "auto":
            language = "en"
        align_model, metadata = whisperx.load_align_model(language_code=language, device="cuda")
        result = whisperx.align(result["segments"], align_model, metadata, audio_data, "cuda")
        segments = result.get("segments", [])

        total_time = time.time() - start_total

        # Compute error vs reference
        ref_path = (
            Path(__file__).parent / "whisperx_test_output" / f"{track_name}_whisperx.lrc"
        )
        error = compute_error_from_segments(segments, str(ref_path))

        return {
            "total_time": total_time,
            "load_time": load_time,
            "transcribe_time": transcribe_time,
            "error": error,
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

def main():
    import torch
    print("=" * 70)
    print("WhisperX: base vs medium model comparison")
    print("=" * 70)
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA: {torch.cuda.is_available()}")

    results = {"base": {}, "medium": {}}

    for track_label, track_name in TEST_TRACKS:
        print(f"\n{'=' * 70}")
        print(f"Testing: {track_label}")
        print("=" * 70)

        for model in ["base", "medium"]:
            res = test_track(track_name, model)
            results[model][track_name] = res

            if "error" in res and isinstance(res.get("error"), str) and "Transcription" not in res.get("error", ""):
                print(f"    {model}: {res['error']}")
            else:
                time_s = res.get("total_time", 0)
                error_s = res.get("error", "N/A")
                if isinstance(error_s, float):
                    print(f"    {model}: time={time_s:.1f}s, error={error_s:.2f}s")
                else:
                    print(f"    {model}: {error_s}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY - WhisperX base vs medium")
    print("=" * 70)

    for track_label, track_name in TEST_TRACKS:
        base_res = results["base"].get(track_name, {})
        med_res = results["medium"].get(track_name, {})

        base_time = base_res.get("total_time", 0)
        med_time = med_res.get("total_time", 0)
        base_error = base_res.get("error", float("inf"))
        med_error = med_res.get("error", float("inf"))

        if base_time and med_time:
            time_delta = (med_time - base_time) / base_time * 100
            print(
                f"{track_label:35} base={base_time:6.1f}s, medium={med_time:6.1f}s ({time_delta:+6.1f}%)"
            )
        else:
            print(f"{track_label:35} ERROR")

    # Save results
    output_file = (
        Path(__file__).parent / "whisperx_test_output" / "base_vs_medium_comparison.json"
    )
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved to {output_file}")

if __name__ == "__main__":
    main()
