#!/usr/bin/env python3
"""Test repeat-aware alignment on test set."""

import json
import sys
from pathlib import Path
import importlib.util
import statistics

worker_path = Path('src') / 'ui' / 'workers' / 'ai_sync_worker.py'
spec = importlib.util.spec_from_file_location('ai_sync_worker', str(worker_path))
ai_module = importlib.util.module_from_spec(spec)

import types
if 'PySide6' not in sys.modules:
    pyside = types.ModuleType('PySide6')
    qtcore = types.ModuleType('PySide6.QtCore')
    qtcore.QThread = type('QThread', (), {})
    qtcore.Signal = lambda *a, **k: None
    pyside.QtCore = qtcore
    sys.modules['PySide6'] = pyside
    sys.modules['PySide6.QtCore'] = qtcore

spec.loader.exec_module(ai_module)
_align = getattr(ai_module, '_align_lyrics_to_segments')

import soundfile as sf
import torch
import torchaudio.functional as F
import whisper
from rapidfuzz import fuzz as rf

def load_audio(path: str):
    data, sr = sf.read(path, dtype='float32')
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        tensor = torch.from_numpy(data).unsqueeze(0)
        tensor = F.resample(tensor, sr, 16000)
        data = tensor.squeeze(0).numpy()
    return data

def parse_lrc(path: str):
    lines = []
    for ln in Path(path).read_text(encoding='utf-8', errors='ignore').splitlines():
        ln = ln.strip()
        if not ln or not ln.startswith('['):
            continue
        try:
            ts_end = ln.index(']')
            ts = ln[1:ts_end]
            mm, rest = ts.split(':')
            ss, cs = rest.split('.')
            seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
            text = ln[ts_end+1:].strip()
            if text:
                lines.append((seconds, text))
        except Exception:
            continue
    return lines

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

def parse_lrc_output(raw_lrc: str):
    pred = []
    for ln in raw_lrc.splitlines():
        ln = ln.strip()
        if not ln or not ln.startswith('['):
            continue
        try:
            end = ln.index(']')
            ts = ln[1:end]
            mm, rest = ts.split(':')
            ss, cs = rest.split('.')
            seconds = int(mm) * 60 + int(ss) + int(cs) / 100.0
            text = ln[end+1:].strip()
            pred.append((seconds, text))
        except:
            pass
    return pred

def evaluate(gt, pred):
    matched = 0
    time_diffs = []
    for gt_t, gt_text in gt:
        best_score = -1
        best_time = None
        for p_t, p_text in pred:
            score = rf.token_sort_ratio(gt_text, p_text)
            if score > best_score:
                best_score = score
                best_time = p_t
        if best_score >= 70 and best_time is not None:
            matched += 1
            time_diffs.append(abs(gt_t - best_time))
    coverage = matched / len(gt) * 100.0 if gt else 0.0
    mean = float(statistics.mean(time_diffs)) if time_diffs else None
    median = float(statistics.median(time_diffs)) if time_diffs else None
    if time_diffs:
        srt = sorted(time_diffs)
        p95 = float(srt[int(round((len(srt) - 1) * 0.95))])
    else:
        p95 = None
    return {
        'mean_abs_s': mean,
        'median_abs_s': median,
        'p95_abs_s': p95,
    }

test_dir = Path('C:\\Users\\andrvoicu\\Downloads\\music_test')
tracks = []
for flac_file in test_dir.glob('*.flac'):
    stem = flac_file.stem
    lrc_file = test_dir / f'{stem}.lrc'
    if lrc_file.exists():
        tracks.append({
            'name': stem,
            'audio': str(flac_file),
            'lrc': str(lrc_file),
            'txt': str(test_dir / f'{stem}.txt') if (test_dir / f'{stem}.txt').exists() else None,
        })

print(f'Found {len(tracks)} tracks')
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f'Using device: {device}')

results = {}
for track_info in tracks:
    name = track_info['name']
    print(f'\n===== {name} =====')
    
    gt = parse_lrc(track_info['lrc'])
    audio_np = load_audio(track_info['audio'])
    
    if track_info['txt']:
        plain_lines = [l.strip() for l in Path(track_info['txt']).read_text(encoding='utf-8', errors='ignore').splitlines() if l.strip()]
    else:
        plain_lines = extract_plain_from_lrc(track_info['lrc'])
    
    if not plain_lines:
        print(f'  No plain lyrics, skipping')
        continue
    
    print(f'  Loading Whisper...')
    model = whisper.load_model('base', device=device)
    result = model.transcribe(audio_np, word_timestamps=True)
    segments = result.get('segments', [])
    
    # Test: greedy only
    print(f'  Testing: greedy (no fuzzy, no repeat-aware)...')
    raw_greedy = _align(plain_lines, segments, enable_fuzzy=False, enable_repeat_aware=False)
    pred_greedy = parse_lrc_output(raw_greedy)
    eval_greedy = evaluate(gt, pred_greedy)
    
    # Test: greedy + fuzzy
    print(f'  Testing: greedy + fuzzy...')
    raw_fuzzy = _align(plain_lines, segments, enable_fuzzy=True, fuzzy_threshold=60, fuzzy_window_words=12, enable_repeat_aware=False)
    pred_fuzzy = parse_lrc_output(raw_fuzzy)
    eval_fuzzy = evaluate(gt, pred_fuzzy)
    
    # Test: greedy + repeat-aware
    print(f'  Testing: greedy + fuzzy + repeat-aware...')
    raw_repeat = _align(plain_lines, segments, enable_fuzzy=True, fuzzy_threshold=60, fuzzy_window_words=12, enable_repeat_aware=True)
    pred_repeat = parse_lrc_output(raw_repeat)
    eval_repeat = evaluate(gt, pred_repeat)
    
    results[name] = {
        'greedy': eval_greedy,
        'fuzzy': eval_fuzzy,
        'repeat_aware': eval_repeat,
    }
    
    print(f'  Greedy:       mean={eval_greedy["mean_abs_s"]:.2f}s, median={eval_greedy["median_abs_s"]:.2f}s, p95={eval_greedy["p95_abs_s"]:.2f}s')
    print(f'  Fuzzy:        mean={eval_fuzzy["mean_abs_s"]:.2f}s, median={eval_fuzzy["median_abs_s"]:.2f}s, p95={eval_fuzzy["p95_abs_s"]:.2f}s')
    print(f'  Repeat-aware: mean={eval_repeat["mean_abs_s"]:.2f}s, median={eval_repeat["median_abs_s"]:.2f}s, p95={eval_repeat["p95_abs_s"]:.2f}s')
    
    del model

out_file = Path('tools/whisperx_test_output/benchmark_repeat_aware.json')
out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text(json.dumps(results, indent=2))
print(f'\nSaved to {out_file}')
