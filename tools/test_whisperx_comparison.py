#!/usr/bin/env python3
"""
Investigation 5: Whisper base vs WhisperX.

Goal: Compare base Whisper vs WhisperX (forced alignment) on:
- Speed (load, transcribe, total)
- Alignment accuracy
- Practicality for real-time use
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


def benchmark_whisperx(track_name: str) -> dict:
    """Compare Whisper base vs WhisperX."""
    print(f"\n{'='*70}")
    print(f"Testing: {track_name}")
    print(f"{'='*70}")
    
    audio_path, plain_lyrics, ground_truth = load_test_data(track_name)
    
    print("  Loading audio...")
    audio = load_audio_as_numpy(audio_path)
    
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Device: {device}")
    
    results = {}
    
    # Test 1: Whisper base
    print("  Test 1: Whisper base...")
    start = time.time()
    model_base = whisper.load_model("base", device=device)
    load_time_base = time.time() - start
    
    start = time.time()
    result_base = model_base.transcribe(audio, word_timestamps=True)
    transcribe_time_base = time.time() - start
    total_time_base = load_time_base + transcribe_time_base
    
    segments_base = result_base.get("segments", [])
    
    lrc_base = _align_lyrics_to_segments(plain_lyrics.splitlines(), segments_base, enable_fuzzy=False)
    pred_base = parse_lrc_tuples(lrc_base)
    error_base = compute_error(pred_base, ground_truth)
    
    results["base"] = {
        "load_time": load_time_base,
        "transcribe_time": transcribe_time_base,
        "total_time": total_time_base,
        "segments": len(segments_base),
        "words": sum(len(s.get("words", [])) for s in segments_base),
        "alignment_error": error_base,
    }
    
    print(f"    Base: load={load_time_base:.1f}s, transcribe={transcribe_time_base:.1f}s, total={total_time_base:.1f}s")
    print(f"           error={error_base['mean_error']:.2f}s")
    
    del model_base
    torch.cuda.empty_cache()
    
    # Test 2: WhisperX
    print("  Test 2: WhisperX (with forced alignment)...")
    try:
        import whisperx
        
        start = time.time()
        # Load WhisperX model
        model_wx = whisperx.load_model("base", device=device, compute_type="float32")
        load_time_wx = time.time() - start
        
        start = time.time()
        # Transcribe
        result_wx = model_wx.transcribe(audio, language="en")
        
        # Align (forced alignment)
        language = result_wx.get("language", "en")
        align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
        result_wx = whisperx.align(result_wx["segments"], align_model, metadata, audio, device, return_char_alignments=False)
        
        transcribe_time_wx = time.time() - start
        total_time_wx = load_time_wx + transcribe_time_wx
        
        segments_wx = result_wx.get("segments", []) or result_wx
        
        lrc_wx = _align_lyrics_to_segments(plain_lyrics.splitlines(), segments_wx, enable_fuzzy=False)
        pred_wx = parse_lrc_tuples(lrc_wx)
        error_wx = compute_error(pred_wx, ground_truth)
        
        results["whisperx"] = {
            "load_time": load_time_wx,
            "transcribe_time": transcribe_time_wx,
            "total_time": total_time_wx,
            "segments": len(segments_wx),
            "words": sum(len(s.get("words", [])) for s in segments_wx),
            "alignment_error": error_wx,
        }
        
        print(f"    WhisperX: load={load_time_wx:.1f}s, transcribe={transcribe_time_wx:.1f}s, total={total_time_wx:.1f}s")
        print(f"              error={error_wx['mean_error']:.2f}s")
        
        # Compare
        print(f"\n  COMPARISON:")
        print(f"    Load time: base={load_time_base:.1f}s vs whisperx={load_time_wx:.1f}s ({(load_time_wx-load_time_base)/load_time_base*100:+.1f}%)")
        print(f"    Transcribe: base={transcribe_time_base:.1f}s vs whisperx={transcribe_time_wx:.1f}s ({(transcribe_time_wx-transcribe_time_base)/transcribe_time_base*100:+.1f}%)")
        print(f"    Total: base={total_time_base:.1f}s vs whisperx={total_time_wx:.1f}s ({(total_time_wx-total_time_base)/total_time_base*100:+.1f}%)")
        
        if "mean_error" in error_base and "mean_error" in error_wx:
            error_improvement = ((error_base["mean_error"] - error_wx["mean_error"]) / error_base["mean_error"]) * 100
            print(f"    Accuracy: base={error_base['mean_error']:.2f}s vs whisperx={error_wx['mean_error']:.2f}s ({error_improvement:+.1f}%)")
        
        del model_wx, align_model
        torch.cuda.empty_cache()
        
    except Exception as e:
        print(f"    WhisperX failed: {e}")
        results["whisperx"] = {"error": str(e)}
    
    return {
        "track": track_name,
        "results": results,
    }


if __name__ == "__main__":
    import torch
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA: {torch.cuda.is_available()}")
    
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
            all_results[track] = benchmark_whisperx(track)
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY - Whisper Base vs WhisperX")
    print(f"{'='*70}")
    
    base_times = []
    wx_times = []
    base_errors = []
    wx_errors = []
    
    for track, result in all_results.items():
        if "error" in result:
            print(f"{track:40} ERROR")
            continue
        
        base = result["results"].get("base")
        wx = result["results"].get("whisperx")
        
        if base and not "error" in base and wx and not "error" in wx:
            base_times.append(base["total_time"])
            wx_times.append(wx["total_time"])
            base_errors.append(base["alignment_error"]["mean_error"])
            wx_errors.append(wx["alignment_error"]["mean_error"])
            
            time_diff = (wx["total_time"] - base["total_time"]) / base["total_time"] * 100
            error_diff = (wx["alignment_error"]["mean_error"] - base["alignment_error"]["mean_error"]) / base["alignment_error"]["mean_error"] * 100
            
            print(f"{track:40} time={wx['total_time']:6.1f}s ({time_diff:+5.1f}%), error={wx['alignment_error']['mean_error']:6.2f}s ({error_diff:+6.1f}%)")
    
    if base_times:
        import numpy as np
        avg_base_time = np.mean(base_times)
        avg_wx_time = np.mean(wx_times)
        avg_base_error = np.mean(base_errors)
        avg_wx_error = np.mean(wx_errors)
        
        time_improvement = (avg_wx_time - avg_base_time) / avg_base_time * 100
        error_improvement = (avg_wx_error - avg_base_error) / avg_base_error * 100
        
        print(f"\nAVERAGE:")
        print(f"  Time:  base={avg_base_time:6.1f}s vs whisperx={avg_wx_time:6.1f}s ({time_improvement:+6.1f}%)")
        print(f"  Error: base={avg_base_error:6.2f}s vs whisperx={avg_wx_error:6.2f}s ({error_improvement:+6.1f}%)")
    
    # Save results
    output_path = Path(__file__).parent / "whisperx_test_output" / "whisperx_comparison.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to {output_path}")
