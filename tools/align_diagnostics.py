from pathlib import Path
import sys
import json

if len(sys.argv) < 4:
    print("Usage: python align_diagnostics.py <audio> <ground_truth.lrc> <plain.txt>")
    sys.exit(2)

audio_path = sys.argv[1]
lrc_path = sys.argv[2]
plain_txt = sys.argv[3]

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


def _collect_words(segments):
    words = []
    for seg in segments:
        for w in seg.get('words', []):
            if 'start' in w and w.get('word', '').strip():
                words.append({'word': w.get('word',''), 'start': w.get('start')})
    return words


def _build_lrc_from_segments(segments):
    lines = []
    for seg in segments:
        start = seg.get('start', 0.0)
        text = seg.get('text', '').strip()
        if not text:
            continue
        lines.append((start, text))
    return lines


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
        for i in range(word_idx, min(len(words), word_idx + len(words)//max(1,len(plain_lines)) + 50)):
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
            if word_idx < len(words):
                start = words[word_idx]['start']
            else:
                start = words[-1]['start'] if words else 0.0
            lrc_lines.append((start, ls))
    return lrc_lines


def eval_per_line(gt_lines, pred_lines):
    # returns list of per-gt-line dicts with best match info
    per = []
    for gt_t, gt_text in gt_lines:
        best_score = -1
        best_time = None
        best_pred_text = None
        for p_t, p_text in pred_lines:
            score = fuzz.token_sort_ratio(gt_text, p_text)
            if score > best_score:
                best_score = score
                best_time = p_t
                best_pred_text = p_text
        time_diff = abs(gt_t - best_time) if best_time is not None else None
        per.append({'gt_t': gt_t, 'gt_text': gt_text, 'best_pred_text': best_pred_text, 'best_pred_t': best_time, 'score': best_score, 'time_diff': time_diff})
    return per


def postprocess_pred_lines(pred_lines, *, max_shift: float = 6.0, median_cutoff: float = 20.0):
    if not pred_lines:
        return pred_lines
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

# Load inputs
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

# Build preds
baseline_pred = greedy_align(plain_lines, segments)
fuzzy_pred = fuzzy_align(plain_lines, segments)

refined_segments = None
refined_pred = None
refined_fuzzy_pred = None
whisperx_warnings = []
try:
    import whisperx
    import whisperx.alignment as wa
    print('Running WhisperX align...')
    align_model, metadata = whisperx.load_align_model(language_code=result.get('language','en'), device='cpu')
    # Capture warnings by running and catching
    align_result = wa.align(segments, align_model, metadata, audio_np, 'cpu')
    if isinstance(align_result, dict) and 'segments' in align_result:
        refined_segments = align_result['segments']
    else:
        refined_segments = getattr(align_result, 'segments', None) or align_result
    refined_pred = greedy_align(plain_lines, refined_segments)
    refined_fuzzy_pred = fuzzy_align(plain_lines, refined_segments)
except Exception as e:
    whisperx_warnings.append(str(e))

# Postprocess
baseline_post = postprocess_pred_lines(baseline_pred)
fuzzy_post = postprocess_pred_lines(fuzzy_pred)
refined_post = postprocess_pred_lines(refined_pred) if refined_pred else None
refined_fuzzy_post = postprocess_pred_lines(refined_fuzzy_pred) if refined_fuzzy_pred else None

# Per-line evaluations
diag = {
    'audio': audio_path,
    'lrc': lrc_path,
    'per_line': []
}

for idx, (gt_t, gt_text) in enumerate(gt):
    entry = {'index': idx, 'gt_t': gt_t, 'gt_text': gt_text}
    entry['baseline'] = eval_per_line([(gt_t, gt_text)], baseline_post)[0]
    entry['fuzzy'] = eval_per_line([(gt_t, gt_text)], fuzzy_post)[0]
    if refined_post is not None:
        entry['whisperx'] = eval_per_line([(gt_t, gt_text)], refined_post)[0]
    else:
        entry['whisperx'] = None
    if refined_fuzzy_post is not None:
        entry['whisperx_fuzzy'] = eval_per_line([(gt_t, gt_text)], refined_fuzzy_post)[0]
    else:
        entry['whisperx_fuzzy'] = None
    diag['per_line'].append(entry)

out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_diagnostics.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(diag, indent=2), encoding='utf-8')
print('Saved diagnostics to', out)
