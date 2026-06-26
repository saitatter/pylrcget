"""Benchmark alignment variants against ground-truth LRC.
Usage (run inside the whisperx venv):
  python tools\align_benchmark.py <audio> <ground_truth.lrc> <plain.txt>

Produces CSV and prints metrics for: baseline (Whisper greedy), fuzzy, WhisperX, WhisperX+fuzzy.
"""
from pathlib import Path
import sys
import json
import math

if len(sys.argv) < 4:
    print("Usage: python align_benchmark.py <audio> <ground_truth.lrc> <plain.txt>")
    sys.exit(2)

audio_path = sys.argv[1]
lrc_path = sys.argv[2]
plain_txt = sys.argv[3]

# Minimal helpers (copied/adapted)
import soundfile as sf
import torch
import torchaudio.functional as F

import whisper

from rapidfuzz import fuzz


def parse_lrc(path: str):
    lines = []
    for ln in Path(path).read_text(encoding='utf-8', errors='ignore').splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith('['):
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


def norm_text(s: str):
    return ''.join(ch.lower() if ch.isalnum() or ch.isspace() else ' ' for ch in s).split()


def _format_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total_cs = int(round(seconds * 100))
    m = total_cs // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{m:02d}:{s:02d}.{cs:02d}"


def _build_lrc_from_segments(segments):
    lines = []
    for seg in segments:
        start = seg.get('start', 0.0)
        text = seg.get('text', '').strip()
        if not text:
            continue
        ts = _format_ts(start)
        lines.append((start, text))
    return lines


def _collect_words(segments):
    words = []
    for seg in segments:
        for w in seg.get('words', []):
            if 'start' in w and w.get('word', '').strip():
                words.append({'word': w.get('word',''), 'start': w.get('start')})
    return words


def greedy_align(plain_lines, segments):
    words = _collect_words(segments)
    if not words:
        return _build_lrc_from_segments(segments)
    lrc_lines = []
    word_idx = 0
    for line in plain_lines:
        ls = line.strip()
        if not ls:
            continue
        lwords = ls.split()
        best_idx = word_idx
        best_score = -1
        search_end = min(len(words), word_idx + len(words) // max(1, len(plain_lines)) + len(lwords) * 3)
        for i in range(word_idx, search_end):
            score = 0
            for j, lw in enumerate(lwords[:5]):
                if i + j < len(words):
                    wt = words[i + j]['word'].strip().lower().strip('.,!?;:\"\'()-')
                    lw_clean = lw.lower().strip('.,!?;:\"\'()-')
                    if wt == lw_clean:
                        score += 2
                    elif lw_clean in wt or wt in lw_clean:
                        score += 1
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx < len(words):
            start = words[best_idx]['start']
            lrc_lines.append((start, ls))
            word_idx = min(best_idx + len(lwords), len(words))
        else:
            last_start = words[-1]['start'] if words else 0.0
            lrc_lines.append((last_start, ls))
    return lrc_lines


def fuzzy_align(plain_lines, segments, score_thresh=60, window_words=12):
    words = _collect_words(segments)
    if not words:
        return _build_lrc_from_segments(segments)
    lrc_lines = []
    word_idx = 0
    for line in plain_lines:
        ls = line.strip()
        if not ls:
            continue
        lwords = ls.split()
        best_idx = None
        best_score = -1
        # slide window from current word_idx up to +some
        max_start = len(words)
        for i in range(word_idx, min(len(words), word_idx + len(words)//max(1,len(plain_lines)) + 50)):
            # build window text
            window_end = min(len(words), i + max(window_words, len(lwords)*2))
            wtext = ' '.join(w['word'] for w in words[i:window_end])
            score = fuzz.partial_ratio(ls, wtext)
            if score > best_score:
                best_score = score
                best_idx = i
        if best_score >= score_thresh and best_idx is not None:
            start = words[best_idx]['start']
            lrc_lines.append((start, ls))
            word_idx = min(best_idx + len(lwords), len(words))
        else:
            # fallback to greedy to ensure a timestamp
            # find nearest by naive fallback
            if word_idx < len(words):
                start = words[word_idx]['start']
            else:
                start = words[-1]['start'] if words else 0.0
            lrc_lines.append((start, ls))
    return lrc_lines


def eval_pred(gt_lines, pred_lines, fuzzy_match_thresh=70):
    # gt_lines: list of (t, text)
    # pred_lines: list of (t, text)
    # For each gt line, find best matching pred by fuzzy text and compute abs time diff
    import statistics
    matched = 0
    time_diffs = []
    for gt_t, gt_text in gt_lines:
        best_score = -1
        best_time = None
        for p_t, p_text in pred_lines:
            score = fuzz.token_sort_ratio(gt_text, p_text)
            if score > best_score:
                best_score = score
                best_time = p_t
        if best_score >= fuzzy_match_thresh and best_time is not None:
            matched += 1
            time_diffs.append(abs(gt_t - best_time))
    coverage = matched / len(gt_lines) * 100.0 if gt_lines else 0.0
    mean = statistics.mean(time_diffs) if time_diffs else None
    median = statistics.median(time_diffs) if time_diffs else None
    return {'coverage_pct': coverage, 'matched': matched, 'total_gt': len(gt_lines), 'mean_abs_s': mean, 'median_abs_s': median}


def postprocess_pred_lines(pred_lines, *, max_shift: float = 6.0, median_cutoff: float = 20.0):
    # pred_lines: list of (t, text)
    if not pred_lines:
        return pred_lines
    # sort
    pred_lines = sorted(pred_lines, key=lambda x: x[0])
    starts = [float(s) for s, _ in pred_lines]
    texts = [t for _, t in pred_lines]
    diffs = []
    for i in range(1, len(starts)):
        d = starts[i] - starts[i-1]
        if 0.05 <= d <= median_cutoff:
            diffs.append(d)
    import statistics
    median_diff = statistics.median(diffs) if diffs else 3.0
    if median_diff < 0.1:
        median_diff = 0.5
    new_starts = [starts[0]]
    for i in range(1, len(starts)):
        prev = new_starts[-1]
        cur = starts[i]
        expected = prev + median_diff
        if cur - expected > max_shift:
            cur = expected
        if cur <= prev + 0.001:
            cur = prev + max(0.01, median_diff * 0.05)
        new_starts.append(cur)
    # spread near-equal runs
    final_starts = new_starts.copy()
    i = 0
    n = len(final_starts)
    while i < n:
        j = i + 1
        while j < n and abs(final_starts[j] - final_starts[j-1]) < 0.02:
            j += 1
        run_len = j - i
        if run_len > 1:
            base = final_starts[i]
            for k in range(run_len):
                final_starts[i + k] = base + k * (median_diff * 0.9)
        i = j
    return [(s, t) for s, t in zip(final_starts, texts)]


def _load_audio_as_numpy(path: str):
    data, sr = sf.read(path, dtype='float32')
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        tensor = torch.from_numpy(data).unsqueeze(0)
        tensor = F.resample(tensor, sr, 16000)
        data = tensor.squeeze(0).numpy()
    return data


# Read ground truth and plain
gt = parse_lrc(lrc_path)
plain_lines = [l.strip() for l in Path(plain_txt).read_text(encoding='utf-8', errors='ignore').splitlines() if l.strip()]

print('GT lines:', len(gt))

# Load Whisper and transcribe
print('Loading Whisper model...')
model = whisper.load_model('base', device='cpu')
print('Loading audio...')
audio_np = _load_audio_as_numpy(audio_path)
print('Transcribing with Whisper...')
result = model.transcribe(audio_np, word_timestamps=True)
segments = result.get('segments', [])
print('Whisper segments:', len(segments))

# Baseline greedy
print('\nRunning baseline greedy align...')
baseline_pred = greedy_align(plain_lines, segments)
baseline_eval = eval_pred(gt, baseline_pred)
print('Baseline:', baseline_eval)

# Fuzzy on Whisper segments
print('\nRunning fuzzy align (Whisper segments)...')
fuzzy_pred = fuzzy_align(plain_lines, segments)
fuzzy_eval = eval_pred(gt, fuzzy_pred)
print('Fuzzy:', fuzzy_eval)


# WhisperX refinement (if available)
refined_segments = None
try:
    import whisperx
    import whisperx.alignment as wa
    print('\nRunning WhisperX align...')
    align_model, metadata = whisperx.load_align_model(language_code=result.get('language','en'), device='cpu')
    align_result = wa.align(segments, align_model, metadata, audio_np, 'cpu')
    # extract segments
    if isinstance(align_result, dict) and 'segments' in align_result:
        refined_segments = align_result['segments']
    else:
        refined_segments = getattr(align_result, 'segments', None) or align_result
    print('Refined segments:', len(refined_segments) if refined_segments else 0)
    refined_pred = greedy_align(plain_lines, refined_segments)
    refined_eval = eval_pred(gt, refined_pred)
    print('WhisperX (greedy):', refined_eval)

    # WhisperX + fuzzy
    refined_fuzzy_pred = fuzzy_align(plain_lines, refined_segments)
    refined_fuzzy_eval = eval_pred(gt, refined_fuzzy_pred)
    print('WhisperX + Fuzzy:', refined_fuzzy_eval)

    # If VAD segments available, also run WhisperX on concatenated vad_segments
    if segs:
        align_result_vad = wa.align(vad_segments, align_model, metadata, audio_np, 'cpu')
        if isinstance(align_result_vad, dict) and 'segments' in align_result_vad:
            vad_refined_segments = align_result_vad['segments']
        else:
            vad_refined_segments = getattr(align_result_vad, 'segments', None) or align_result_vad
        print('VAD-refined segments:', len(vad_refined_segments) if vad_refined_segments else 0)
        vad_refined_pred = greedy_align(plain_lines, vad_refined_segments)
        vad_refined_eval = eval_pred(gt, vad_refined_pred)
        print('VAD WhisperX (greedy):', vad_refined_eval)
        vad_refined_fuzzy_pred = fuzzy_align(plain_lines, vad_refined_segments)
        vad_refined_fuzzy_eval = eval_pred(gt, vad_refined_fuzzy_pred)
        print('VAD WhisperX + Fuzzy:', vad_refined_fuzzy_eval)
except Exception as e:
    print('\nWhisperX not available/failed:', e)
    refined_eval = None
    refined_fuzzy_eval = None

# Save CSV output
out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_compare.json')
out.parent.mkdir(parents=True, exist_ok=True)
res = {
    'audio': audio_path,
    'lrc': lrc_path,
    'baseline': baseline_eval,
    'fuzzy': fuzzy_eval,
    'whisperx': refined_eval,
    'whisperx_fuzzy': refined_fuzzy_eval,
}
out.write_text(json.dumps(res, indent=2), encoding='utf-8')
print('\nSaved report to', out)
print('Done')
