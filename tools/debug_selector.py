#!/usr/bin/env python3
"""Debug: see what strategy auto-selector chooses for each track."""

import sys
from pathlib import Path
import importlib.util

worker_path = Path('src') / 'ui' / 'workers' / 'ai_sync_worker.py'
spec = importlib.util.spec_from_file_location('ai_sync_worker', str(worker_path))
ai_module = importlib.util.module_from_spec(spec)

import types
if 'PySide6' not in sys.modules:
    pyside = types.ModuleType('PySide6')
    qtcore = types.ModuleType('PySide6.QtCore')
    class _QThread:
        pass
    def _Signal(*args, **kwargs):
        return None
    qtcore.QThread = _QThread
    qtcore.Signal = _Signal
    pyside.QtCore = qtcore
    sys.modules['PySide6'] = pyside
    sys.modules['PySide6.QtCore'] = qtcore

spec.loader.exec_module(ai_module)
_align = getattr(ai_module, '_align_lyrics_to_segments')
_worker_cls = getattr(ai_module, 'AiSyncWorker')

import soundfile as sf
import torch
import whisper

def load_audio(path: str):
    data, sr = sf.read(path, dtype='float32')
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        import torchaudio.functional as F
        tensor = torch.from_numpy(data).unsqueeze(0)
        tensor = F.resample(tensor, sr, 16000)
        data = tensor.squeeze(0).numpy()
    return data

def extract_plain_from_lrc(path: str):
    lines = []
    for ln in Path(path).read_text(encoding='utf-8', errors='ignore').splitlines():
        ln = ln.strip()
        if not ln or not ln.startswith('['):
            continue
        try:
            ts_end = ln.index(']')
            text = ln[ts_end+1:].strip()
            if text:
                lines.append(text)
        except:
            pass
    return lines

test_dir = Path('C:\\Users\\andrvoicu\\Downloads\\music_test')
track_name = 'Nancy the Tavern Wench'

lrc_file = test_dir / f'{track_name}.lrc'
audio_file = test_dir / f'{track_name}.flac'

plain_lines = extract_plain_from_lrc(str(lrc_file))
audio_np = load_audio(str(audio_file))

print(f"[*] Loading Whisper...")
model = whisper.load_model('base', device='cuda' if torch.cuda.is_available() else 'cpu')
result = model.transcribe(audio_np, word_timestamps=True)
segments = result.get('segments', [])

print(f"[*] Running alignment (auto-selector should choose best strategy)...")

# Add some debugging to see which strategy wins
# We'll monkey-patch the scorer to log decisions
import json

raw_lrc = _align(
    plain_lines,
    segments,
    enable_fuzzy=True,
    fuzzy_threshold=60,
    fuzzy_window_words=12,
    repeat_penalty=50.0,
    max_backtrack=0.5,
    enable_viterbi=True,
    min_repeat_gap=4,
    section_anchors=_worker_cls._detect_audio_section_anchors(audio_np, 16000),
)

print("\nResulting LRC (first 20 lines):")
for line in raw_lrc.split('\n')[:20]:
    print(line)

print(f"\n[*] Check: search for logs or strategy info in the implementation...")
print("Current version auto-selector picks: fuzzy_local, forced_external, forced_whisperx, or viterbi")
print("Based on: evidence_score, monotonicity, repeat-chronology, catastrophic snap veto")
