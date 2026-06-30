import sys
import os
from pathlib import Path

if len(sys.argv) < 3:
    print("Usage: python whisperx_test.py <audio_path> <lyrics_txt_path>")
    sys.exit(2)

audio_path = sys.argv[1]
lyrics_path = sys.argv[2]

# Ensure src is on PYTHONPATH when running; caller should set PYTHONPATH=src
try:
    from ui.workers import ai_sync_worker as worker
except Exception as e:
    print("Failed to import ai_sync_worker:", e)
    raise

import whisper
import torch

print('Device detection...')
if torch.cuda.is_available():
    device = 'cuda'
elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    device = 'mps'
else:
    device = 'cpu'
print('Using device:', device)

# Read plain lyrics
with open(lyrics_path, 'r', encoding='utf-8', errors='ignore') as f:
    plain_lines = [l.strip() for l in f.readlines() if l.strip()]

print('Loading Whisper model (base)...')
model = whisper.load_model('base', device=device)

print('Transcribing (this can take a while)...')
# Use worker helper to load/resample audio to 16k numpy
audio_np = worker.AiSyncWorker._load_audio_as_numpy(audio_path)
result = model.transcribe(audio_np, word_timestamps=True)
segments = result.get('segments', [])
print('Segments from Whisper:', len(segments))

# Baseline LRC using existing greedy align
baseline_lrc = worker._align_lyrics_to_segments(plain_lines, segments)

# Try WhisperX refinement
refined_lrc = None
try:
    import whisperx
    print('Refining with WhisperX...')
    language = result.get('language', 'en')
    align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    refined_segments = whisperx.align_segments(segments, align_model, metadata, audio_path, device)
    print('Refined segments from WhisperX:', len(refined_segments))
    refined_lrc = worker._align_lyrics_to_segments(plain_lines, refined_segments)
except Exception as e:
    print('WhisperX not available or failed:', e)

# Prepare output
out_dir = Path('tools') / 'whisperx_test_output'
out_dir.mkdir(parents=True, exist_ok=True)

baseline_path = out_dir / (Path(audio_path).stem + '_baseline.lrc')
with open(baseline_path, 'w', encoding='utf-8') as f:
    f.write(baseline_lrc)

if refined_lrc:
    refined_path = out_dir / (Path(audio_path).stem + '_whisperx.lrc')
    with open(refined_path, 'w', encoding='utf-8') as f:
        f.write(refined_lrc)
else:
    refined_path = None

# Print short report
print('\n--- REPORT ---')
print('Audio:', audio_path)
print('Lyrics:', lyrics_path)
print('Whisper segments:', len(segments))
print('Baseline LRC lines:', len([l for l in baseline_lrc.splitlines() if l.strip()]))
if refined_lrc:
    print('WhisperX refined segments:', len(refined_segments))
    print('Refined LRC lines:', len([l for l in refined_lrc.splitlines() if l.strip()]))

print('\nBaseline LRC (first 12 lines):')
for i, l in enumerate(baseline_lrc.splitlines()[:12], 1):
    print(f'{i:02d}.', l)

if refined_lrc:
    print('\nWhisperX LRC (first 12 lines):')
    for i, l in enumerate(refined_lrc.splitlines()[:12], 1):
        print(f'{i:02d}.', l)

print('\nOutputs saved to:', out_dir)
if refined_path:
    print('  ', baseline_path)
    print('  ', refined_path)
else:
    print('  ', baseline_path)

print('\nDone')
