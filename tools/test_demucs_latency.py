#!/usr/bin/env python3
"""
Investigation 4: Measure Demucs separation latency.

Goal: Detect if Demucs introduces consistent delay in timestamps.
If yes, compute compensation offset and test if it improves alignment.
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


def separate_vocals_demucs(audio, sr=16000, device="cuda"):
    """Separate vocals using Demucs. Returns vocals audio."""
    try:
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
        import torch
        import numpy as np
        
        model = get_model('htdemucs')
        model.to(device)
        model.eval()
        
        # Convert to torch tensor: stereo (2, samples)
        if len(audio.shape) == 1:
            wav_stereo = np.stack([audio, audio], axis=0)
        else:
            wav_stereo = audio
        
        wav_tensor = torch.from_numpy(wav_stereo).float()[None, :, :]  # (1, 2, samples)
        
        with torch.no_grad():
            wav_separated = apply_model(model, wav_tensor)  # (batch, stems, channels, samples)
        
        # Extract vocals (stem 3 is vocals)
        vocals_stereo = wav_separated[0, 3, :, :].cpu().numpy()  # (2, samples)
        vocals = vocals_stereo[0, :]  # Take first channel
        
        return vocals.astype(np.float32)
    except Exception as e:
        print(f"  Demucs separation failed: {e}")
        return None


def extract_word_timings(segments: list[dict]) -> list[tuple[str, float]]:
    """Extract (word, timestamp_start) from segments."""
    words = []
    for seg in segments:
        for w in seg.get("words", []):
            if "start" in w and w.get("word", "").strip():
                words.append((w["word"].lower().strip(), w["start"]))
    return words


def compute_delay(words_full: list[tuple[str, float]], 
                  words_vocals: list[tuple[str, float]]) -> tuple[float, int]:
    """
    Measure delay between full mix and separated vocals word timestamps.
    Returns (mean_delay, num_matches).
    
    Assumes same transcription text but different timestamps due to latency.
    """
    import numpy as np
    
    delays = []
    matched = 0
    
    # Build text-based lookup for vocals
    vocals_by_idx = {i: (word, ts) for i, (word, ts) in enumerate(words_vocals)}
    
    # For each word in full mix, find corresponding word in vocals
    for i, (word_full, ts_full) in enumerate(words_full):
        if i in vocals_by_idx:
            word_vocals, ts_vocals = vocals_by_idx[i]
            if word_full == word_vocals or (word_full and word_vocals and word_full[0] == word_vocals[0]):
                delay = ts_vocals - ts_full  # positive = vocals delayed
                delays.append(delay)
                matched += 1
    
    if delays:
        mean_delay = float(np.mean(delays))
        std_delay = float(np.std(delays))
        return mean_delay, std_delay, matched
    
    return 0.0, 0.0, 0


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


def benchmark_demucs_latency(track_name: str) -> dict:
    """Measure Demucs latency and test compensation."""
    print(f"\n{'='*70}")
    print(f"Testing: {track_name}")
    print(f"{'='*70}")
    
    audio_path, plain_lyrics, ground_truth = load_test_data(track_name)
    
    print("  Loading audio...")
    audio = load_audio_as_numpy(audio_path)
    
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Device: {device}")
    
    print("  Loading Whisper base...")
    model = whisper.load_model("base", device=device)
    
    # Test 1: Full mix transcription
    print("  Transcribing FULL MIX...")
    result_full = model.transcribe(audio, word_timestamps=True)
    segments_full = result_full.get("segments", [])
    words_full = extract_word_timings(segments_full)
    
    # Test 2: Separated vocals transcription
    print("  Separating vocals with Demucs...")
    vocals = separate_vocals_demucs(audio, sr=16000, device=device)
    
    if vocals is None:
        return {"track": track_name, "error": "demucs_failed"}
    
    print("  Transcribing SEPARATED VOCALS...")
    result_vocals = model.transcribe(vocals, word_timestamps=True)
    segments_vocals = result_vocals.get("segments", [])
    words_vocals = extract_word_timings(segments_vocals)
    
    # Measure delay
    print("  Measuring latency...")
    mean_delay, std_delay, matched = compute_delay(words_full, words_vocals)
    
    print(f"  Latency analysis:")
    print(f"    Matched words: {matched}")
    print(f"    Mean delay: {mean_delay:+.3f}s")
    print(f"    Std dev: {std_delay:.3f}s")
    
    # Test 3: Alignment without compensation
    print("  Aligning WITHOUT latency compensation...")
    lrc_vocals = _align_lyrics_to_segments(plain_lyrics.splitlines(), segments_vocals, enable_fuzzy=False)
    pred_vocals = parse_lrc_tuples(lrc_vocals)
    error_vocals = compute_error(pred_vocals, ground_truth)
    
    # Test 4: Alignment WITH compensation (subtract delay from timestamps)
    print("  Aligning WITH latency compensation...")
    # Manually adjust segments
    segments_vocals_comp = json.loads(json.dumps(segments_vocals))  # Deep copy
    for seg in segments_vocals_comp:
        seg["start"] -= mean_delay
        seg["end"] -= mean_delay
        for w in seg.get("words", []):
            if "start" in w:
                w["start"] -= mean_delay
            if "end" in w:
                w["end"] -= mean_delay
    
    lrc_vocals_comp = _align_lyrics_to_segments(plain_lyrics.splitlines(), segments_vocals_comp, enable_fuzzy=False)
    pred_vocals_comp = parse_lrc_tuples(lrc_vocals_comp)
    error_vocals_comp = compute_error(pred_vocals_comp, ground_truth)
    
    # Compare all three
    lrc_full = _align_lyrics_to_segments(plain_lyrics.splitlines(), segments_full, enable_fuzzy=False)
    pred_full = parse_lrc_tuples(lrc_full)
    error_full = compute_error(pred_full, ground_truth)
    
    print(f"\n  RESULTS:")
    print(f"    Full mix:                {error_full['mean_error']:6.2f}s mean")
    print(f"    Vocals (no comp):        {error_vocals['mean_error']:6.2f}s mean")
    print(f"    Vocals (latency comp):   {error_vocals_comp['mean_error']:6.2f}s mean")
    
    # Compute improvements
    if "mean_error" in error_full:
        imp_vocals = ((error_full["mean_error"] - error_vocals["mean_error"]) / error_full["mean_error"]) * 100
        imp_comp = ((error_full["mean_error"] - error_vocals_comp["mean_error"]) / error_full["mean_error"]) * 100
        print(f"\n  IMPROVEMENT vs Full Mix:")
        print(f"    Vocals (no comp): {imp_vocals:+.1f}%")
        print(f"    Vocals (latency): {imp_comp:+.1f}%")
    
    del model
    torch.cuda.empty_cache()
    
    return {
        "track": track_name,
        "latency": {
            "mean_delay": mean_delay,
            "std_delay": std_delay,
            "matched_words": matched,
        },
        "errors": {
            "full_mix": error_full,
            "vocals_no_compensation": error_vocals,
            "vocals_with_compensation": error_vocals_comp,
        },
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
            all_results[track] = benchmark_demucs_latency(track)
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY - Demucs Latency Analysis")
    print(f"{'='*70}")
    
    latencies = []
    improvements = []
    
    for track, result in all_results.items():
        if "error" in result:
            print(f"{track:40} ERROR: {result['error']}")
            continue
        
        latency = result["latency"]["mean_delay"]
        latencies.append(latency)
        
        full = result["errors"]["full_mix"]["mean_error"]
        comp = result["errors"]["vocals_with_compensation"]["mean_error"]
        
        if full and comp:
            improvement = ((full - comp) / full) * 100
            improvements.append(improvement)
            print(f"{track:40} latency={latency:+.3f}s, comp_error={comp:6.2f}s ({improvement:+6.1f}%)")
    
    if latencies:
        import numpy as np
        avg_latency = np.mean(latencies)
        avg_improvement = np.mean(improvements) if improvements else 0
        print(f"\nAVERAGE LATENCY:   {avg_latency:+.3f}s")
        print(f"AVERAGE IMPROVEMENT (with compensation): {avg_improvement:+.1f}%")
    
    # Save results
    output_path = Path(__file__).parent / "whisperx_test_output" / "demucs_latency_analysis.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to {output_path}")
