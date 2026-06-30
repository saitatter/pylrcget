from pathlib import Path
import sys
import json

if len(sys.argv) < 4:
    print("Usage: python align_full_experiments.py <audio> <ground_truth.lrc> <plain.txt> [whisper_model]")
    sys.exit(2)

audio_path = sys.argv[1]
lrc_path = sys.argv[2]
plain_txt = sys.argv[3]
whisper_model = sys.argv[4] if len(sys.argv) > 4 else "base"

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


def proximity_fuzzy_align(plain_lines, segments, score_thresh=45, window_words=12, penalty_coeff=2.0, max_backtrack=0.5):
    words = _collect_words(segments)
    if not words:
        return [(seg.get('start',0.0), seg.get('text','').strip()) for seg in segments if seg.get('text','').strip()]

    gaps = []
    for i in range(1, len(words)):
        gaps.append(max(0.01, words[i]['start'] - words[i-1]['start']))
    import statistics
    expected_gap = statistics.median(gaps) if gaps else 0.5
    if expected_gap < 0.1:
        expected_gap = 0.5

    lrc_lines = []
    word_idx = 0
    last_start = -999.0
    for line in plain_lines:
        ls = line.strip()
        if not ls:
            continue
        lwords = ls.split()
        best_idx = None
        best_score = -1e9
        search_end = min(len(words), word_idx + len(words)//max(1,len(plain_lines)) + 50)
        for i in range(word_idx, search_end):
            wstart = words[i]['start']
            if last_start > -900 and wstart < last_start - max_backtrack:
                continue
            window_end = min(len(words), i + max(window_words, len(lwords)*2))
            wtext = ' '.join(w['word'] for w in words[i:window_end])
            text_score = fuzz.partial_ratio(ls, wtext)
            if last_start > -900:
                time_diff = abs(wstart - (last_start + expected_gap))
            else:
                time_diff = wstart
            time_penalty = penalty_coeff * time_diff
            final_score = text_score - time_penalty
            idx_bonus = max(0, (1.0 - (i - word_idx)/50.0)) * 2.0
            final_score += idx_bonus
            if final_score > best_score:
                best_score = final_score
                best_idx = i
        if best_idx is not None and best_score >= score_thresh:
            start = words[best_idx]['start']
            lrc_lines.append((start, ls))
            last_start = start
            word_idx = min(best_idx + len(lwords), len(words))
        else:
            if word_idx < len(words):
                start = words[word_idx]['start']
            else:
                start = words[-1]['start'] if words else 0.0
            lrc_lines.append((start, ls))
            last_start = start
            word_idx = min(word_idx + len(lwords), len(words))
    return lrc_lines


def clamp_times(pred_lines, max_jump=15.0):
    if not pred_lines:
        return pred_lines
    out = [list(pred_lines[0])]
    for start, text in pred_lines[1:]:
        prev = out[-1][0]
        if start - prev > max_jump:
            start = prev + max_jump
        if start <= prev:
            start = prev + 0.01
        out.append([start, text])
    return [(s, t) for s, t in out]


def clamp_times_smart(pred_lines, expected_gap=3.0, max_shift=10.0):
    if not pred_lines:
        return pred_lines
    out = [list(pred_lines[0])]
    for start, text in pred_lines[1:]:
        prev = out[-1][0]
        expected = prev + expected_gap
        if start - expected > max_shift:
            start = expected + max_shift
        if start <= prev:
            start = prev + max(0.01, expected_gap*0.1)
        out.append([start, text])
    return [(s, t) for s, t in out]


def greedy_align(plain_lines, segments):
    words = _collect_words(segments)
    if not words:
        return [(seg.get('start',0.0), seg.get('text','').strip()) for seg in segments if seg.get('text','').strip()]
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


def viterbi_align(plain_lines, segments, window_words=12, penalty_coeff=2.0, max_backtrack=0.5):
    words = _collect_words(segments)
    if not words:
        return greedy_align(plain_lines, segments)
    n = len(words)
    m = len(plain_lines)
    # candidate windows per line
    avg_words_per_line = max(1, n // max(1, m))
    max_span = max(50, avg_words_per_line * 4)
    # precompute text scores for each line and candidate start
    import math
    text_scores = [dict() for _ in range(m)]
    for j, line in enumerate(plain_lines):
        ls = line.strip()
        if not ls:
            continue
        for i in range(0, n):
            window_end = min(n, i + max(window_words, len(ls.split())*2))
            wtext = ' '.join(words[k]['word'] for k in range(i, window_end))
            text_scores[j][i] = fuzz.partial_ratio(ls, wtext)
    # DP: dp[j][i] = best score up to line j ending at word i
    dp = [dict() for _ in range(m)]
    back = [dict() for _ in range(m)]
    for i in range(0, n):
        # cost for first line
        score = text_scores[0].get(i, 0)
        dp[0][i] = score
        back[0][i] = None
    for j in range(1, m):
        for i in range(0, n):
            if i not in text_scores[j]:
                continue
            best_prev = None
            best_score = -1e9
            # consider prev indices < i, but limit lookback
            lookback_start = max(0, i - max_span)
            for pi, prev_score in dp[j-1].items():
                if pi < lookback_start or pi >= i:
                    continue
                # monotonic and limited backtrack (time-based)
                prev_t = words[pi]['start']
                cur_t = words[i]['start']
                if cur_t < prev_t - max_backtrack:
                    continue
                expected = prev_t + (words[i]['start'] - prev_t)  # naive
                time_penalty = penalty_coeff * abs(cur_t - prev_t)
                s = prev_score + text_scores[j].get(i, 0) - time_penalty
                if s > best_score:
                    best_score = s
                    best_prev = pi
            if best_prev is not None:
                dp[j][i] = best_score
                back[j][i] = best_prev
    # find best end
    if not dp[m-1]:
        return greedy_align(plain_lines, segments)
    best_i = max(dp[m-1].keys(), key=lambda k: dp[m-1][k])
    path = [best_i]
    for j in range(m-1, 0, -1):
        best_i = back[j][best_i]
        path.append(best_i)
    path = list(reversed(path))
    # build lrc_lines
    lrc_lines = []
    for j, idx in enumerate(path):
        start = words[idx]['start']
        lrc_lines.append((start, plain_lines[j]))
    return lrc_lines


def eval_pred(gt_lines, pred_lines, fuzzy_match_thresh=70):
    import statistics
    from rapidfuzz import fuzz as rfuzz
    matched = 0
    time_diffs = []
    per = []
    for gt_t, gt_text in gt_lines:
        best_score = -1
        best_time = None
        best_pred = None
        for p_t, p_text in pred_lines:
            score = rfuzz.token_sort_ratio(gt_text, p_text)
            if score > best_score:
                best_score = score
                best_time = p_t
                best_pred = p_text
        td = abs(gt_t - best_time) if best_time is not None else None
        per.append({'gt_t': gt_t, 'gt_text': gt_text, 'pred_text': best_pred, 'pred_t': best_time, 'score': best_score, 'time_diff': td})
        if best_score >= fuzzy_match_thresh and best_time is not None:
            matched += 1
            time_diffs.append(td)
    coverage = matched / len(gt_lines) * 100.0 if gt_lines else 0.0
    mean = float(statistics.mean(time_diffs)) if time_diffs else None
    median = float(statistics.median(time_diffs)) if time_diffs else None
    return {'coverage_pct': coverage, 'matched': matched, 'total_gt': len(gt_lines), 'mean_abs_s': mean, 'median_abs_s': median}, per


def _load_audio_as_numpy(path: str):
    data, sr = sf.read(path, dtype='float32')
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        tensor = torch.from_numpy(data).unsqueeze(0)
        tensor = F.resample(tensor, sr, 16000)
        data = tensor.squeeze(0).numpy()
    return data

# Load
gt = parse_lrc(lrc_path)
plain_lines = [l.strip() for l in Path(plain_txt).read_text(encoding='utf-8', errors='ignore').splitlines() if l.strip()]
print('GT lines:', len(gt))

print(f'Loading Whisper model: {whisper_model} ...')
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f'Using device: {device}')
model = whisper.load_model(whisper_model, device=device)
print('Loading audio...')
audio_np = _load_audio_as_numpy(audio_path)
print('Transcribing with Whisper...')
result = model.transcribe(audio_np, word_timestamps=True)
segments = result.get('segments', [])
print('Whisper segments:', len(segments))

# Baseline/fuzzy/proximity
print('\nRunning baseline/fuzzy/proximity...')
baseline = greedy_align(plain_lines, segments)
baseline_eval, baseline_per = eval_pred(gt, baseline)

from rapidfuzz import fuzz as rf
fuzzy = None
try:
    # reuse existing fuzzy_align from previous scripts? implement quick approx
    def fuzzy_align_simple(plain_lines, segments, score_thresh=60):
        words = _collect_words(segments)
        if not words:
            return [(seg.get('start',0.0), seg.get('text','').strip()) for seg in segments if seg.get('text','').strip()]
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
                window_end = min(len(words), i + max(12, len(lwords)*2))
                wtext = ' '.join(w['word'] for w in words[i:window_end])
                score = rf.partial_ratio(ls, wtext)
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_score >= 50 and best_idx is not None:
                start = words[best_idx]['start']
                lrc_lines.append((start, ls))
                word_idx = min(best_idx + len(lwords), len(words))
            else:
                start = words[word_idx]['start'] if word_idx < len(words) else (words[-1]['start'] if words else 0.0)
                lrc_lines.append((start, ls))
        return lrc_lines
    fuzzy = fuzzy_align_simple(plain_lines, segments)
    fuzzy_eval, fuzzy_per = eval_pred(gt, fuzzy)
except Exception as e:
    fuzzy = baseline
    fuzzy_eval, fuzzy_per = baseline_eval, baseline_per

prox = proximity_fuzzy_align(plain_lines, segments)
prox_eval, prox_per = eval_pred(gt, prox)

# Clamping experiments
clamped = clamp_times(prox, max_jump=15.0)
clamped_eval, clamped_per = eval_pred(gt, clamped)
clamped_smart = clamp_times_smart(prox, expected_gap=3.0, max_shift=10.0)
clamped_smart_eval, clamped_smart_per = eval_pred(gt, clamped_smart)

# Viterbi
print('\nRunning Viterbi align...')
viterbi = viterbi_align(plain_lines, segments)
viterbi_eval, viterbi_per = eval_pred(gt, viterbi)

# Grid tuning (restricted)
print('\nRunning grid tuning (36 runs)...')
best = {'score': 1e9}
results_grid = []
penalties = [1.0, 2.0, 4.0]
thresholds = [45, 55, 65]
windows = [8, 16]
smooth_shifts = [3, 6]
for p in penalties:
    for th in thresholds:
        for w in windows:
            for s in smooth_shifts:
                pred = proximity_fuzzy_align(plain_lines, segments, score_thresh=th, window_words=w, penalty_coeff=p)
                pred_s = clamp_times_smart(pred, expected_gap=3.0, max_shift=s)
                evalr, _ = eval_pred(gt, pred_s)
                results_grid.append({'penalty': p, 'th': th, 'window': w, 'smooth_max_shift': s, 'eval': evalr})
                # use mean as objective (lower better)
                mean = evalr.get('mean_abs_s') or 1e9
                if mean < best.get('mean', 1e9):
                    best = {'penalty': p, 'th': th, 'window': w, 'smooth_max_shift': s, 'mean': mean, 'eval': evalr}
print('Grid done')

# Inspect worst lines for best run and Viterbi
# For best run compute per-line and pick top 10 worst by time_diff
best_pred = proximity_fuzzy_align(plain_lines, segments, score_thresh=best['th'], window_words=best['window'], penalty_coeff=best['penalty'])
best_pred = clamp_times_smart(best_pred, expected_gap=3.0, max_shift=best['smooth_max_shift'])
best_eval, best_per = eval_pred(gt, best_pred)

# worst lines
def worst_lines(per_list, top_n=10):
    arr = [p for p in per_list if p.get('time_diff') is not None]
    arr.sort(key=lambda x: x['time_diff'], reverse=True)
    return arr[:top_n]

worst_best = worst_lines(best_per, 10)
worst_viterbi = worst_lines(viterbi_per, 10)

# Save
out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_full_experiments.json')
out.parent.mkdir(parents=True, exist_ok=True)
res = {
    'audio': audio_path,
    'lrc': lrc_path,
    'baseline': baseline_eval,
    'fuzzy': fuzzy_eval,
    'proximity': prox_eval,
    'clamped': clamped_eval,
    'clamped_smart': clamped_smart_eval,
    'viterbi': viterbi_eval,
    'grid_best': best,
    'grid_results_count': len(results_grid),
    'worst_best': worst_best,
    'worst_viterbi': worst_viterbi,
}
out.write_text(json.dumps(res, indent=2), encoding='utf-8')
print('Saved full experiments to', out)
print('Done')
