#!/usr/bin/env python3
"""Benchmark all tracks in music_test folder and compare results."""

import json
import sys
from pathlib import Path
import importlib.util
import statistics

# Load ai_sync_worker
worker_path = Path(__file__).resolve().parents[1] / 'src' / 'ui' / 'workers' / 'ai_sync_worker.py'
if not worker_path.exists():
    worker_path = Path('src') / 'ui' / 'workers' / 'ai_sync_worker.py'

spec = importlib.util.spec_from_file_location('ai_sync_worker', str(worker_path))
ai_module = importlib.util.module_from_spec(spec)

# Minimal PySide6 shim
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
    """Extract unique plain text lines from LRC, preserving order and dupes."""
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
        except Exception:
            continue
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
        except Exception:
            continue
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
        p99 = float(srt[int(round((len(srt) - 1) * 0.99))])
    else:
        p95 = None
        p99 = None
    return {
        'coverage_pct': coverage,
        'matched': matched,
        'total_gt': len(gt),
        'mean_abs_s': mean,
        'median_abs_s': median,
        'p95_abs_s': p95,
        'p99_abs_s': p99,
    }


# Find all tracks
test_dir = Path('C:\\Users\\andrvoicu\\Downloads\\music_test')
tracks = []
for flac_file in test_dir.glob('*.flac'):
    stem = flac_file.stem
    lrc_file = test_dir / f'{stem}.lrc'
    txt_file = test_dir / f'{stem}.txt'
    if lrc_file.exists():
        txt_path = str(txt_file) if txt_file.exists() else None
        tracks.append({
            'name': stem,
            'audio': str(flac_file),
            'lrc': str(lrc_file),
            'txt': txt_path,
        })

if not tracks:
    print('No test tracks found in', test_dir)
    sys.exit(1)

print(f'Found {len(tracks)} tracks')
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f'Using device: {device}')

results = {}
for track_info in tracks:
    name = track_info['name']
    print(f'\n===== {name} =====')
    
    # Load data
    gt = parse_lrc(track_info['lrc'])
    audio_np = load_audio(track_info['audio'])
    
    # Get plain text
    if track_info['txt']:
        plain_lines = [l.strip() for l in Path(track_info['txt']).read_text(encoding='utf-8', errors='ignore').splitlines() if l.strip()]
    else:
        plain_lines = extract_plain_from_lrc(track_info['lrc'])
    
    if not plain_lines:
        print(f'  No plain lyrics, skipping')
        continue
    
    print(f'  GT: {len(gt)} lines, plain: {len(plain_lines)} lines')
    
    # Load Whisper
    print(f'  Loading Whisper model...')
    model = whisper.load_model('base', device=device)
    result = model.transcribe(audio_np, word_timestamps=True)
    segments = result.get('segments', [])
    section_anchors = _worker_cls._detect_audio_section_anchors(audio_np, 16000)
    
    # Run all strategies
    print(f'  Running Fuzzy local alignment (enable_viterbi=False)...')
    raw_fuzzy = _align(
        plain_lines,
        segments,
        enable_fuzzy=True,
        fuzzy_threshold=60,
        fuzzy_window_words=12,
        repeat_penalty=50.0,
        max_backtrack=0.5,
        enable_viterbi=False,
        min_repeat_gap=4,
        section_anchors=section_anchors,
    )
    pred_fuzzy = parse_lrc_output(raw_fuzzy)
    eval_fuzzy = evaluate(gt, pred_fuzzy)
    
    print(f'  Running Auto-selector with Viterbi (enable_viterbi=True)...')
    raw_auto = _align(
        plain_lines,
        segments,
        enable_fuzzy=True,
        fuzzy_threshold=60,
        fuzzy_window_words=12,
        repeat_penalty=50.0,
        max_backtrack=0.5,
        enable_viterbi=True,
        min_repeat_gap=4,
        section_anchors=section_anchors,
    )
    pred_auto = parse_lrc_output(raw_auto)
    eval_auto = evaluate(gt, pred_auto)
    
    results[name] = {
        'gt_count': len(gt),
        'fuzzy_local': eval_fuzzy,
        'auto_viterbi': eval_auto,
    }
    
    print(f'  Fuzzy local:     mean={eval_fuzzy["mean_abs_s"]:.2f}s, median={eval_fuzzy["median_abs_s"]:.2f}s, p95={eval_fuzzy["p95_abs_s"]:.2f}s')
    print(f'  Auto+Viterbi:    mean={eval_auto["mean_abs_s"]:.2f}s, median={eval_auto["median_abs_s"]:.2f}s, p95={eval_auto["p95_abs_s"]:.2f}s')
    
    # Cleanup
    del model

# Save aggregated report
out_file = Path('tools') / 'whisperx_test_output' / 'benchmark_all_tracks.json'
out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text(json.dumps(results, indent=2), encoding='utf-8')
print(f'\n\nReport saved to {out_file}')

# Print summary
print('\n===== SUMMARY =====')
for name, res in results.items():
    f_mean = res['fuzzy_local']['mean_abs_s'] or 999
    v_mean = res['viterbi']['mean_abs_s'] or 999
    improvement = ((f_mean - v_mean) / f_mean * 100) if f_mean > 0 else 0
    print(f'{name:40s} fuzzy={f_mean:6.2f}s -> viterbi={v_mean:6.2f}s ({improvement:+6.1f}%)')

