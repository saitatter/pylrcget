#!/usr/bin/env python3
"""
Investigation 3: Test WITH vs WITHOUT Demucs vocal separation.

Goal: Understand if Demucs vocal separation helps or hurts timestamp reliability.
"""
import json
import sys
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


def separate_vocals_demucs(audio: "np.ndarray", sr: int = 16000) -> tuple["np.ndarray", str]:
    """Separate vocals using Demucs. Returns (vocals_audio, temp_path)."""
    try:
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
        import numpy as np
        from pathlib import Path
        import tempfile
        import torch
        
        # Save audio to temp file
        temp_dir = Path(tempfile.gettempdir()) / "demucs_temp"
        temp_dir.mkdir(exist_ok=True)
        temp_wav = temp_dir / "temp.wav"
        
        import soundfile as sf
        sf.write(str(temp_wav), audio, sr)
        
        # Load model
        print("    Loading Demucs model...")
        model = get_model('htdemucs')
        model.eval()
        
        # Convert to torch tensor: Demucs expects stereo (2, samples)
        # For mono, duplicate to create stereo
        print("    Separating audio...")
        if len(audio.shape) == 1:
            # Mono -> stereo
            wav_stereo = np.stack([audio, audio], axis=0)
        else:
            wav_stereo = audio
        
        wav_tensor = torch.from_numpy(wav_stereo).float()[None, :, :]  # Add batch: (1, 2, samples)
        
        with torch.no_grad():
            wav_separated = apply_model(model, wav_tensor)  # Returns (batch, stems, channels, samples)
        
        # Extract vocals (stem 3 is vocals in htdemucs), take first channel
        vocals_stereo = wav_separated[0, 3, :, :].cpu().numpy()  # (2, samples)
        vocals = vocals_stereo[0, :]  # Take first channel, convert to mono
        
        return vocals.astype(np.float32), str(temp_wav)
    except Exception as e:
        print(f"    Demucs separation failed: {e}")
        return None, None


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


def benchmark_demucs(track_name: str) -> dict:
    """Benchmark WITH vs WITHOUT Demucs."""
    print(f"\n{'='*70}")
    print(f"Testing: {track_name}")
    print(f"{'='*70}")
    
    audio_path, plain_lyrics, ground_truth = load_test_data(track_name)
    
    print("  Loading audio...")
    audio = load_audio_as_numpy(audio_path)
    
    print("  Loading Whisper base model...")
    model = whisper.load_model("base")
    
    results = {}
    
    # Test 1: WITHOUT Demucs (full audio mix)
    print("  Test 1: Transcribing FULL MIX (no separation)...")
    result_full = model.transcribe(audio, word_timestamps=True)
    segments_full = result_full.get("segments", [])
    
    lrc_full = _align_lyrics_to_segments(plain_lyrics.splitlines(), segments_full, enable_fuzzy=False)
    pred_full = parse_lrc_tuples(lrc_full)
    error_full = compute_error(pred_full, ground_truth)
    
    results["full_mix"] = error_full
    print(f"  Full mix: {error_full}")
    
    # Test 2: WITH Demucs (vocals only)
    print("  Test 2: Separating vocals with Demucs...")
    vocals, temp_wav = separate_vocals_demucs(audio, 16000)
    
    if vocals is not None:
        print("  Transcribing VOCALS ONLY (with Demucs)...")
        result_vocals = model.transcribe(vocals, word_timestamps=True)
        segments_vocals = result_vocals.get("segments", [])
        
        lrc_vocals = _align_lyrics_to_segments(plain_lyrics.splitlines(), segments_vocals, enable_fuzzy=False)
        pred_vocals = parse_lrc_tuples(lrc_vocals)
        error_vocals = compute_error(pred_vocals, ground_truth)
        
        results["vocals_only"] = error_vocals
        print(f"  Vocals only: {error_vocals}")
        
        # Compare
        if "mean_error" in error_full and "mean_error" in error_vocals:
            improvement = ((error_full["mean_error"] - error_vocals["mean_error"]) / error_full["mean_error"]) * 100
            print(f"\n  COMPARISON:")
            print(f"    Full mix:     {error_full['mean_error']:6.2f}s mean error")
            print(f"    Vocals only:  {error_vocals['mean_error']:6.2f}s mean error")
            print(f"    Change: {improvement:+.1f}%")
    else:
        print("  Demucs separation failed, skipping vocals-only test")
    
    return {
        "track": track_name,
        "results": results,
    }


if __name__ == "__main__":
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
            all_results[track] = benchmark_demucs(track)
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY - Full Mix vs Vocals Only (Demucs)")
    print(f"{'='*70}")
    
    for track, result in all_results.items():
        full = result["results"].get("full_mix")
        vocals = result["results"].get("vocals_only")
        
        if full and vocals and "mean_error" in full and "mean_error" in vocals:
            improvement = ((full["mean_error"] - vocals["mean_error"]) / full["mean_error"]) * 100
            print(f"{track:40} full={full['mean_error']:6.2f}s vs vocals={vocals['mean_error']:6.2f}s ({improvement:+6.1f}%)")
        elif full:
            print(f"{track:40} full={full['mean_error']:6.2f}s [no demucs result]")
    
    # Save results
    output_path = Path(__file__).parent / "whisperx_test_output" / "demucs_comparison.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to {output_path}")
