import sys
import os
from pathlib import Path

if len(sys.argv) < 3:
    print("Usage: python whisperx_test_standalone.py <audio_path> <lyrics_txt_path>")
    sys.exit(2)

audio_path = sys.argv[1]
lyrics_path = sys.argv[2]

# Minimal local helpers (copied/adapted from ai_sync_worker) to avoid PySide6 import
import math

def _format_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total_cs = int(round(seconds * 100))
    m = total_cs // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{m:02d}:{s:02d}.{cs:02d}"


def _build_lrc_from_segments(segments: list) -> str:
    lines = []
    for seg in segments:
        start = seg.get('start', 0.0)
        text = seg.get('text', '').strip()
        if not text:
            continue
        ts = _format_ts(start)
        lines.append(f'[{ts}] {text}')
    return '\n'.join(lines)


def _align_lyrics_to_segments(plain_lines: list, segments: list) -> str:
    if not segments:
        return _build_lrc_from_segments(segments)
    words = []
    for seg in segments:
        for w in seg.get('words', []):
            if 'start' in w and w.get('word', '').strip():
                words.append(w)
    if not words:
        return _build_lrc_from_segments(segments)
    lrc_lines = []
    word_idx = 0
    for line in plain_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        line_words = line_stripped.split()
        if not line_words:
            continue
        best_idx = word_idx
        best_score = -1
        search_end = min(len(words), word_idx + len(words) // max(1, len(plain_lines)) + len(line_words) * 3)
        for i in range(word_idx, search_end):
            score = 0
            for j, lw in enumerate(line_words[:5]):
                if i + j < len(words):
                    wt = words[i + j].get('word', '').strip().lower()
                    wt = wt.strip('.,!?;:\"\'()-')
                    lw_clean = lw.lower().strip('.,!?;:\"\'()-')
                    if wt == lw_clean:
                        score += 2
                    elif lw_clean in wt or wt in lw_clean:
                        score += 1
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx < len(words):
            start = words[best_idx].get('start', 0.0)
            ts = _format_ts(start)
            lrc_lines.append(f'[{ts}] {line_stripped}')
            word_idx = min(best_idx + len(line_words), len(words))
        else:
            last_start = words[-1].get('start', 0.0) if words else 0.0
            ts = _format_ts(last_start)
            lrc_lines.append(f'[{ts}] {line_stripped}')
    return '\n'.join(lrc_lines)


def _load_audio_as_numpy(path: str):
    import soundfile as sf
    import torch
    import torchaudio.functional as F
    data, sr = sf.read(path, dtype='float32')
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        tensor = torch.from_numpy(data).unsqueeze(0)
        tensor = F.resample(tensor, sr, 16000)
        data = tensor.squeeze(0).numpy()
    return data


# Read lyrics
with open(lyrics_path, 'r', encoding='utf-8', errors='ignore') as f:
    plain_lines = [l.strip() for l in f.readlines() if l.strip()]

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

print('Loading Whisper model (base)...')
model = whisper.load_model('base', device=device)
print('Transcribing...')
audio_np = _load_audio_as_numpy(audio_path)
result = model.transcribe(audio_np, word_timestamps=True)
segments = result.get('segments', [])
print('Whisper segments:', len(segments))

baseline_lrc = _align_lyrics_to_segments(plain_lines, segments)

refined_lrc = None
refined_segments = None
try:
    import whisperx
    import whisperx.alignment as wa
    print('Running WhisperX refinement...')
    language = result.get('language', 'en')
    align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    align_result = wa.align(segments, align_model, metadata, audio_np, device)
    # align_result may be dict-like; extract segments in a compatible form
    if isinstance(align_result, dict) and 'segments' in align_result:
        refined_segments = align_result['segments']
    else:
        refined_segments = getattr(align_result, 'segments', None) or align_result
    print('Refined segments length:', len(refined_segments) if refined_segments else 0)
    if refined_segments:
        refined_lrc = _align_lyrics_to_segments(plain_lines, refined_segments)
except Exception as e:
    print('WhisperX not available/failed:', e)

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

print('\n--- REPORT ---')
print('Audio:', audio_path)
print('Lyrics:', lyrics_path)
print('Whisper segments:', len(segments))
print('Baseline LRC lines:', len([l for l in baseline_lrc.splitlines() if l.strip()]))
if refined_lrc:
    print('Refined segments:', len(refined_segments))
    print('Refined LRC lines:', len([l for l in refined_lrc.splitlines() if l.strip()]))

print('\nBaseline LRC (first 12):')
for i, l in enumerate(baseline_lrc.splitlines()[:12], 1):
    print(f'{i:02d}.', l)

if refined_lrc:
    print('\nRefined LRC (first 12):')
    for i, l in enumerate(refined_lrc.splitlines()[:12], 1):
        print(f'{i:02d}.', l)

print('\nOutputs saved to:', out_dir)
print('Done')
