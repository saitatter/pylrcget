#!/usr/bin/env python3
"""
Test confidence filtering impact on alignment accuracy.
Compare greedy baseline vs greedy+confidence filtering.
"""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import whisper
from ui.workers.ai_sync_worker import _align_lyrics_to_segments, _postprocess_lrc_tuples


def parse_lrc_file(lrc_path: str) -> list[tuple[float, str]]:
    """Parse LRC file and return list of (timestamp_seconds, text) tuples."""
    import re
    lrc_ts_re = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
    
    tuples = []
    for line in Path(lrc_path).read_text().splitlines():
        line = line.strip()
        if not line or not line.startswith("["):
            continue
        
        match = lrc_ts_re.search(line)
        if not match:
            continue
        
        mm, ss, frac = match.groups()
        m = int(mm)
        s = int(ss)
        cs = int(frac or "0")
        seconds = m * 60 + s + cs / 100.0
        
        text = lrc_ts_re.sub("", line).strip()
        if text:
            tuples.append((seconds, text))
    
    return tuples


def load_test_data(track_name: str) -> tuple[str, str, list[dict]]:
    """Load audio, plain lyrics, and ground truth LRC for a test track."""
    test_dir = Path("C:\\Users\\andrvoicu\\Downloads\\music_test")
    
    # Find audio file
    audio_path = None
    for ext in [".flac", ".mp3", ".wav"]:
        candidate = test_dir / f"{track_name}{ext}"
        if candidate.exists():
            audio_path = str(candidate)
            break
    
    if not audio_path:
        raise FileNotFoundError(f"No audio file for {track_name} in {test_dir}")
    
    # Load ground truth LRC
    lrc_path = test_dir / f"{track_name}.lrc"
    if not lrc_path.exists():
        raise FileNotFoundError(f"No LRC file for {track_name}")
    
    ground_truth = parse_lrc_file(str(lrc_path))
    
    # Load plain lyrics
    txt_path = test_dir / f"{track_name}.txt"
    if not txt_path.exists():
        # Try to extract from LRC
        plain_lines = [text for _, text in ground_truth]
    else:
        plain_lines = [l.strip() for l in txt_path.read_text().splitlines() if l.strip()]
    
    return audio_path, "\n".join(plain_lines), ground_truth


def compute_error(predicted: list[tuple[float, str]], ground_truth: list[tuple[float, str]]) -> dict:
    """Compute alignment error metrics."""
    # Match lines by text
    gt_by_text = {text.lower(): ts for ts, text in ground_truth}
    
    errors = []
    matched = 0
    
    for pred_ts, pred_text in predicted:
        pred_text_norm = pred_text.lower()
        if pred_text_norm in gt_by_text:
            gt_ts = gt_by_text[pred_text_norm]
            error = abs(pred_ts - gt_ts)
            errors.append(error)
            matched += 1
    
    if not errors:
        return {"error": "no_matches", "matched": 0, "total": len(predicted)}
    
    import numpy as np
    return {
        "matched": matched,
        "total": len(predicted),
        "coverage": matched / len(predicted) if predicted else 0,
        "mean_error": float(np.mean(errors)),
        "median_error": float(np.median(errors)),
        "p95_error": float(np.percentile(errors, 95)),
        "max_error": float(np.max(errors)),
    }


def benchmark_confidence_filtering(track_name: str) -> dict:
    """Benchmark with and without confidence filtering."""
    print(f"\n{'='*70}")
    print(f"Testing: {track_name}")
    print(f"{'='*70}")
    
    audio_path, plain_lyrics, ground_truth = load_test_data(track_name)
    
    print("  Loading Whisper...")
    model = whisper.load_model("base")
    
    print("  Transcribing audio...")
    import soundfile as sf
    from scipy import signal
    audio, sr = sf.read(audio_path)
    if sr != 16000:
        num_samples = int(len(audio) * 16000 / sr)
        audio = signal.resample(audio, num_samples)
    if len(audio.shape) > 1:
        audio = __import__('numpy').mean(audio, axis=1)
    
    result = model.transcribe(audio.astype(__import__('numpy').float32), word_timestamps=True)
    segments = result.get("segments", [])
    
    print("  Testing: greedy baseline (no confidence filtering)...")
    lrc_baseline = _align_lyrics_to_segments(
        plain_lyrics.splitlines(),
        segments,
        enable_fuzzy=False,
        confidence_threshold=1.0,  # Disable confidence filtering (accept all)
    )
    
    print("  Testing: greedy + confidence filtering (threshold=0.5)...")
    lrc_filtered = _align_lyrics_to_segments(
        plain_lyrics.splitlines(),
        segments,
        enable_fuzzy=False,
        confidence_threshold=0.5,  # Filter out low-confidence segments
    )
    
    # Parse to tuples
    def parse_lrc_tuples(lrc_text: str) -> list[tuple[float, str]]:
        tuples = []
        for ln in lrc_text.splitlines():
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
                tuples.append((seconds, text))
            except (ValueError, IndexError):
                pass
        return tuples
    
    baseline_tuples = parse_lrc_tuples(lrc_baseline)
    filtered_tuples = parse_lrc_tuples(lrc_filtered)
    
    error_baseline = compute_error(baseline_tuples, ground_truth)
    error_filtered = compute_error(filtered_tuples, ground_truth)
    
    print(f"  Baseline:  {error_baseline}")
    print(f"  Filtered:  {error_filtered}")
    
    # Compute improvement
    if "mean_error" in error_baseline and "mean_error" in error_filtered:
        improvement = ((error_baseline["mean_error"] - error_filtered["mean_error"]) / error_baseline["mean_error"]) * 100
        print(f"  IMPROVEMENT: {improvement:+.1f}% (mean error)")
    
    return {
        "track": track_name,
        "baseline": error_baseline,
        "filtered": error_filtered,
    }


if __name__ == "__main__":
    tracks = [
        "House of Sleep",
        "Keelhauled",
        "Nancy the Tavern Wench",
        "See You in Hell (acoustic)",
        "Upside Down",
    ]
    
    results = {}
    for track in tracks:
        try:
            results[track] = benchmark_confidence_filtering(track)
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    
    total_baseline_mean = 0
    total_filtered_mean = 0
    count = 0
    
    for track, result in results.items():
        baseline = result["baseline"]
        filtered = result["filtered"]
        
        if "mean_error" in baseline and "mean_error" in filtered:
            improvement = ((baseline["mean_error"] - filtered["mean_error"]) / baseline["mean_error"]) * 100
            print(f"{track:40} baseline={baseline['mean_error']:6.2f}s -> filtered={filtered['mean_error']:6.2f}s ({improvement:+6.1f}%)")
            total_baseline_mean += baseline["mean_error"]
            total_filtered_mean += filtered["mean_error"]
            count += 1
    
    if count > 0:
        avg_baseline = total_baseline_mean / count
        avg_filtered = total_filtered_mean / count
        avg_improvement = ((avg_baseline - avg_filtered) / avg_baseline) * 100
        print(f"\n{'AVERAGE':40} baseline={avg_baseline:6.2f}s -> filtered={avg_filtered:6.2f}s ({avg_improvement:+6.1f}%)")
    
    # Save results
    output_path = Path(__file__).parent / "whisperx_test_output" / "confidence_filtering_test.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {output_path}")
