#!/usr/bin/env python3
"""
Investigation 2 (retry): Test Whisper base vs large-v3 on CUDA.

Now with CUDA available, test if larger model = better timestamps.
"""
import json
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import whisper
from ui.workers.ai_sync_worker import _align_lyrics_to_segments


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


def load_test_data(track_name: str) -> tuple[str, str, list[tuple[float, str]]]:
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
        raise FileNotFoundError(f"No audio file for {track_name}")
    
    # Load ground truth LRC
    lrc_path = test_dir / f"{track_name}.lrc"
    if not lrc_path.exists():
        raise FileNotFoundError(f"No LRC file for {track_name}")
    
    ground_truth = parse_lrc_file(str(lrc_path))
    
    # Load plain lyrics
    txt_path = test_dir / f"{track_name}.txt"
    if not txt_path.exists():
        plain_lines = [text for _, text in ground_truth]
    else:
        plain_lines = [l.strip() for l in txt_path.read_text().splitlines() if l.strip()]
    
    return audio_path, "\n".join(plain_lines), ground_truth


def load_audio_as_numpy(audio_path: str):
    """Load audio file to numpy array."""
    import soundfile as sf
    from scipy import signal
    import numpy as np
    
    audio, sr = sf.read(audio_path)
    if sr != 16000:
        num_samples = int(len(audio) * 16000 / sr)
        audio = signal.resample(audio, num_samples)
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    return audio.astype(np.float32)


def compute_error(predicted: list[tuple[float, str]], ground_truth: list[tuple[float, str]]) -> dict:
    """Compute alignment error metrics."""
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


def parse_lrc_tuples(lrc_text: str) -> list[tuple[float, str]]:
    """Parse LRC text into tuples."""
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


def benchmark_models_cuda(track_name: str) -> dict:
    """Benchmark Whisper base vs large-v3 on CUDA."""
    print(f"\n{'='*70}")
    print(f"Testing: {track_name}")
    print(f"{'='*70}")
    
    audio_path, plain_lyrics, ground_truth = load_test_data(track_name)
    
    print("  Loading audio...")
    audio = load_audio_as_numpy(audio_path)
    
    import torch
    if not torch.cuda.is_available():
        print("ERROR: CUDA not available!")
        return {"error": "no_cuda"}
    
    print(f"  CUDA available: {torch.cuda.get_device_name(0)}")
    
    results = {}
    
    for model_name in ["base", "large-v3"]:
        print(f"  Loading Whisper {model_name}...")
        start = time.time()
        model = whisper.load_model(model_name, device="cuda")
        load_time = time.time() - start
        
        print(f"  Transcribing with {model_name}...")
        start = time.time()
        result = model.transcribe(audio, word_timestamps=True)
        transcribe_time = time.time() - start
        
        segments = result.get("segments", [])
        
        print(f"  Aligning with {model_name}...")
        lrc_text = _align_lyrics_to_segments(
            plain_lyrics.splitlines(),
            segments,
            enable_fuzzy=False,
        )
        
        pred_tuples = parse_lrc_tuples(lrc_text)
        error = compute_error(pred_tuples, ground_truth)
        
        results[model_name] = {
            "load_time": load_time,
            "transcribe_time": transcribe_time,
            "segments": len(segments),
            "words": sum(len(s.get("words", [])) for s in segments),
            "alignment_error": error,
        }
        
        print(f"  {model_name}: {error}")
        print(f"    Load: {load_time:.1f}s, Transcribe: {transcribe_time:.1f}s")
        
        # Free GPU memory
        del model
        torch.cuda.empty_cache()
    
    # Compare
    base_error = results["base"]["alignment_error"]
    large_error = results["large-v3"]["alignment_error"]
    
    if "mean_error" in base_error and "mean_error" in large_error:
        improvement = ((base_error["mean_error"] - large_error["mean_error"]) / base_error["mean_error"]) * 100
        print(f"\n  COMPARISON:")
        print(f"    Base:      {base_error['mean_error']:6.2f}s mean error")
        print(f"    Large-v3:  {large_error['mean_error']:6.2f}s mean error")
        print(f"    Change: {improvement:+.1f}%")
    
    return {
        "track": track_name,
        "results": results,
    }


if __name__ == "__main__":
    import torch
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"CUDA device: {torch.cuda.get_device_name(0)}")
    
    tracks = [
        "House of Sleep",
        "Keelhauled",
        "Nancy the Tavern Wench",
        "See You in Hell (acoustic)",
        "Upside Down",
    ]
    
    all_results = {}
    
    for track in tracks:
        try:
            all_results[track] = benchmark_models_cuda(track)
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY - Base vs Large-v3 (CUDA)")
    print(f"{'='*70}")
    
    base_mean_errors = []
    large_mean_errors = []
    
    for track, result in all_results.items():
        if "error" in result:
            print(f"{track:40} ERROR: {result['error']}")
            continue
        
        base = result["results"]["base"]["alignment_error"]
        large = result["results"]["large-v3"]["alignment_error"]
        
        if "mean_error" in base and "mean_error" in large:
            improvement = ((base["mean_error"] - large["mean_error"]) / base["mean_error"]) * 100
            print(f"{track:40} base={base['mean_error']:6.2f}s vs large={large['mean_error']:6.2f}s ({improvement:+6.1f}%)")
            base_mean_errors.append(base["mean_error"])
            large_mean_errors.append(large["mean_error"])
    
    if base_mean_errors and large_mean_errors:
        import numpy as np
        base_avg = np.mean(base_mean_errors)
        large_avg = np.mean(large_mean_errors)
        avg_improvement = ((base_avg - large_avg) / base_avg) * 100
        print(f"\nAVERAGE:                                 base={base_avg:6.2f}s vs large={large_avg:6.2f}s ({avg_improvement:+6.1f}%)")
    
    # Save results
    output_path = Path(__file__).parent / "whisperx_test_output" / "model_comparison_cuda.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to {output_path}")
