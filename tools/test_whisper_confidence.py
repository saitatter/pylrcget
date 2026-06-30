#!/usr/bin/env python3
"""
Investigation 1: Check Whisper confidence scores and their correlation with alignment errors.

Goal: Understand if low-confidence words are causing the cumulative drift.
"""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import whisper
import numpy as np


def load_audio_as_numpy(audio_path: str) -> np.ndarray:
    """Load audio file to numpy array (compatible with Whisper)."""
    try:
        import soundfile as sf
        audio, sr = sf.read(audio_path)
        # Resample to 16kHz if needed
        if sr != 16000:
            from scipy import signal
            num_samples = int(len(audio) * 16000 / sr)
            audio = signal.resample(audio, num_samples)
        if len(audio.shape) > 1:
            audio = np.mean(audio, axis=1)  # Convert to mono
        return audio.astype(np.float32)
    except ImportError:
        print("ERROR: soundfile not available. Try: pip install soundfile scipy")
        raise


def extract_word_confidence(result: dict) -> list[dict]:
    """Extract words with confidence scores from Whisper result."""
    words_with_conf = []
    
    for seg in result.get("segments", []):
        segment_conf = 1.0 - seg.get("no_speech_prob", 0.5)  # segment-level confidence
        
        for w in seg.get("words", []):
            if "start" in w and w.get("word", "").strip():
                # Extract word-level confidence from logprobs if available
                word_conf = segment_conf  # fallback to segment confidence
                
                # If logprobs available, compute word confidence
                if "logprob" in w:
                    # logprob is log probability; convert to probability
                    word_conf = min(1.0, max(0.0, np.exp(w["logprob"])))
                
                words_with_conf.append({
                    "word": w["word"],
                    "start": w["start"],
                    "end": w["end"],
                    "confidence": word_conf,
                    "logprob": w.get("logprob"),
                })
    
    return words_with_conf


def test_whisper_confidence(audio_path: str):
    """Test Whisper transcription with confidence extraction."""
    print(f"Loading {audio_path}...")
    audio = load_audio_as_numpy(audio_path)
    
    print("Transcribing with base model (word_timestamps=True)...")
    result_base = whisper.load_model("base").transcribe(
        audio,
        word_timestamps=True,
    )
    
    print("Extracting word confidence from base result...")
    words_base = extract_word_confidence(result_base)
    
    # Analyze confidence distribution
    confidences = [w["confidence"] for w in words_base]
    logprobs = [w["logprob"] for w in words_base if w["logprob"] is not None]
    
    print(f"\n=== Base Model Confidence Analysis ===")
    print(f"Total words: {len(words_base)}")
    print(f"Confidence range: {min(confidences):.3f} - {max(confidences):.3f}")
    print(f"Mean confidence: {np.mean(confidences):.3f}")
    print(f"Median confidence: {np.median(confidences):.3f}")
    print(f"Stdev: {np.std(confidences):.3f}")
    
    if logprobs:
        print(f"\nLogprob range: {min(logprobs):.3f} - {max(logprobs):.3f}")
        print(f"Mean logprob: {np.mean(logprobs):.3f}")
        print(f"Median logprob: {np.median(logprobs):.3f}")
    
    # Show low-confidence words (threshold 0.7)
    low_conf = [w for w in words_base if w["confidence"] < 0.7]
    print(f"\nLow-confidence words (<0.7): {len(low_conf)} / {len(words_base)} ({100*len(low_conf)/len(words_base):.1f}%)")
    if low_conf[:10]:
        print("  First 10:")
        for w in low_conf[:10]:
            print(f"    {w['word']:20} conf={w['confidence']:.3f} logprob={w['logprob']}")
    
    # Analyze confidence trend over song duration
    print(f"\n=== Confidence Trend Over Song Duration ===")
    duration = result_base["segments"][-1]["end"] if result_base["segments"] else 0
    print(f"Total duration: {duration:.1f}s")
    
    # Bin words by time and compute mean confidence per bin
    time_bins = np.linspace(0, duration, 6)  # 5 bins
    for i in range(len(time_bins) - 1):
        bin_start, bin_end = time_bins[i], time_bins[i+1]
        words_in_bin = [w for w in words_base if bin_start <= w["start"] < bin_end]
        if words_in_bin:
            mean_conf = np.mean([w["confidence"] for w in words_in_bin])
            print(f"  [{bin_start:5.1f}s - {bin_end:5.1f}s] {len(words_in_bin):3} words, mean_conf={mean_conf:.3f}")
    
    # Check segment boundaries
    print(f"\n=== Segment Boundary Analysis ===")
    segments = result_base.get("segments", [])
    print(f"Total segments: {len(segments)}")
    for i, seg in enumerate(segments):
        words_in_seg = seg.get("words", [])
        if words_in_seg:
            seg_conf = [w for w in words_base if seg["start"] <= w["start"] < seg["end"]]
            if seg_conf:
                mean_conf = np.mean([w["confidence"] for w in seg_conf])
                print(f"  Seg {i:2}: {seg['start']:6.1f}s-{seg['end']:6.1f}s | "
                      f"{len(seg_conf):3} words | mean_conf={mean_conf:.3f} | "
                      f"no_speech_prob={seg.get('no_speech_prob', 0):.3f}")
    
    # Save detailed results
    output_path = Path(__file__).parent / "whisperx_test_output" / "whisper_confidence.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump({
            "audio_path": str(audio_path),
            "model": "base",
            "words_count": len(words_base),
            "confidence_stats": {
                "min": float(min(confidences)),
                "max": float(max(confidences)),
                "mean": float(np.mean(confidences)),
                "median": float(np.median(confidences)),
                "stdev": float(np.std(confidences)),
            },
            "low_confidence_threshold": 0.7,
            "low_confidence_count": len(low_conf),
            "low_confidence_percentage": float(100 * len(low_conf) / len(words_base)),
            "words": words_base,
        }, f, indent=2)
    
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    # Test on first track
    test_dir = Path("C:\\Users\\andrvoicu\\Downloads\\music_test")
    audio_files = sorted(test_dir.glob("*.flac")) + sorted(test_dir.glob("*.mp3"))
    
    if not audio_files:
        print(f"No audio files found in {test_dir}")
        sys.exit(1)
    
    # Test first file
    audio_file = audio_files[0]
    print(f"\n{'='*60}")
    print(f"Testing: {audio_file.name}")
    print(f"{'='*60}")
    test_whisper_confidence(str(audio_file))
