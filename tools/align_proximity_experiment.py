from pathlib import Path
import sys
import json

if len(sys.argv) < 4:
    print("Usage: python align_proximity_experiment.py <audio> <ground_truth.lrc> <plain.txt>")
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


def proximity_fuzzy_align(plain_lines, segments, score_thresh=45, window_words=12, penalty_coeff=2.0, max_backtrack=0.5):
    words = _collect_words(segments)
    if not words:
        # fallback
        return [(seg.get('start',0.0), seg.get('text','').strip()) for seg in segments if seg.get('text','').strip()]

    # compute median inter-word gap as expected_gap
    gaps = []
    for i in range(1, len(words)):
        gaps.append(max(0.01, words[i]['start'] - words[i-1]['start']))
    import statistics
    expected_gap = statistics.median(gaps) if gaps else 0.5
    # clamp expected_gap
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
            # monotonic constraint: no large backtrack
            if last_start > -900 and wstart < last_start - max_backtrack:
                continue
            window_end = min(len(words), i + max(window_words, len(lwords)*2))
            wtext = ' '.join(w['word'] for w in words[i:window_end])
            text_score = fuzz.partial_ratio(ls, wtext)
            # expected time for this line is last_start + expected_gap, if last_start known
            if last_start > -900:
                time_diff = abs(wstart - (last_start + expected_gap))
            else:
                # penalize far-away positions from start
                time_diff = wstart
            time_penalty = penalty_coeff * time_diff
            final_score = text_score - time_penalty
            # small bonus for closer indices (prefer near current word_idx)
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
            # fallback greedy
            if word_idx < len(words):
                start = words[word_idx]['start']
            else:
                start = words[-1]['start'] if words else 0.0
            lrc_lines.append((start, ls))
            last_start = start
            word_idx = min(word_idx + len(lwords), len(words))
    return lrc_lines


def _format_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total_cs = int(round(seconds * 100))
    m = total_cs // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{m:02d}:{s:02d}.{cs:02d}"


def eval_pred(gt_lines, pred_lines, fuzzy_match_thresh=70):
    import statistics
    from rapidfuzz import fuzz as rfuzz
    matched = 0
    time_diffs = []
    for gt_t, gt_text in gt_lines:
        best_score = -1
        best_time = None
        for p_t, p_text in pred_lines:
            score = rfuzz.token_sort_ratio(gt_text, p_text)
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

print('Loading Whisper model...')
model = whisper.load_model('base', device='cpu')
print('Loading audio...')
audio_np = _load_audio_as_numpy(audio_path)
print('Transcribing with Whisper...')
result = model.transcribe(audio_np, word_timestamps=True)
segments = result.get('segments', [])
print('Whisper segments:', len(segments))

# Run proximity fuzzy align
print('\nRunning proximity-weighted fuzzy align (monotonic) ...')
prox_pred = proximity_fuzzy_align(plain_lines, segments)
prox_eval = eval_pred(gt, prox_pred)
print('Proximity fuzzy:', prox_eval)

# Also run WhisperX refined + proximity fuzzy if available
refined_segments = None
try:
    import whisperx
    import whisperx.alignment as wa
    print('\nAttempting WhisperX refinement...')
    align_model, metadata = whisperx.load_align_model(language_code=result.get('language','en'), device='cpu')
    align_result = wa.align(segments, align_model, metadata, audio_np, 'cpu')
    if isinstance(align_result, dict) and 'segments' in align_result:
        refined_segments = align_result['segments']
    else:
        refined_segments = getattr(align_result, 'segments', None) or align_result
    print('Refined segments:', len(refined_segments) if refined_segments else 0)
    prox_refined_pred = proximity_fuzzy_align(plain_lines, refined_segments)
    prox_refined_eval = eval_pred(gt, prox_refined_pred)
    print('WhisperX + Proximity fuzzy:', prox_refined_eval)
except Exception as e:
    print('WhisperX not available/failed:', e)
    prox_refined_pred = None
    prox_refined_eval = None

# Save
out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_proximity.json')
out.parent.mkdir(parents=True, exist_ok=True)
res = {
    'audio': audio_path,
    'lrc': lrc_path,
    'proximity': prox_eval,
    'proximity_whisperx': prox_refined_eval,
}
out.write_text(json.dumps(res, indent=2), encoding='utf-8')
print('Saved report to', out)
print('Done')
