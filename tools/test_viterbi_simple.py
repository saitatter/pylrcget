#!/usr/bin/env python3
"""
Quick test: Viterbi function directly (no WhisperX).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Test data: simple example
plain_lines = [
    "the quick brown fox",
    "jumps over the lazy",
    "dog",
]

# Simulate ASR output (words with timestamps)
words = [
    {"word": "the", "start": 0.0},
    {"word": "quick", "start": 0.5},
    {"word": "brown", "start": 1.0},
    {"word": "fox", "start": 1.5},
    {"word": "jumps", "start": 2.5},
    {"word": "over", "start": 3.0},
    {"word": "the", "start": 3.5},
    {"word": "lazy", "start": 4.0},
    {"word": "dog", "start": 5.0},
]

print("=" * 80)
print("Quick Test: Viterbi Function")
print("=" * 80)
print(f"Plain lines: {plain_lines}")
print(f"Words (ASR): {[w['word'] for w in words]}\n")

try:
    from ui.workers.ai_sync_worker import _align_lyrics_to_segments_viterbi, _format_ts
    
    print("[*] Running Viterbi alignment...")
    result = _align_lyrics_to_segments_viterbi(plain_lines, [{"words": words}])
    
    print("\n[*] Result (LRC):")
    for line in result.splitlines():
        print(f"    {line}")
    
    print("\n[*] Extracted timestamps:")
    for line in result.splitlines():
        if line.startswith("["):
            try:
                end = line.index("]")
                ts_str = line[1:end]
                text = line[end+1:].strip()
                print(f"    {ts_str} -> {text}")
            except:
                pass
                
except Exception as e:
    import traceback
    print(f"ERROR: {e}")
    print(traceback.format_exc())
