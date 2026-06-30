from pathlib import Path
import sys
import json
import importlib.util

if len(sys.argv) < 4:
    print("Usage: python align_worker_experiment.py <audio> <ground_truth.lrc> <plain.txt> [mode] [whisper_model]")
    sys.exit(2)

audio_path = sys.argv[1]
lrc_path = sys.argv[2]
plain_txt = sys.argv[3]
mode = (sys.argv[4] if len(sys.argv) > 4 else "grid").strip().lower()
whisper_model = (sys.argv[5] if len(sys.argv) > 5 else "base").strip()

# Load ai_sync_worker from src path
worker_path = Path(__file__).resolve().parents[1] / 'src' / 'ui' / 'workers' / 'ai_sync_worker.py'
if not worker_path.exists():
    worker_path = Path('src') / 'ui' / 'workers' / 'ai_sync_worker.py'

spec = importlib.util.spec_from_file_location('ai_sync_worker', str(worker_path))
ai_module = importlib.util.module_from_spec(spec)
# Provide a minimal PySide6 shim so module can be loaded outside the app env
import types, sys
if 'PySide6' not in sys.modules:
    pyside = types.ModuleType('PySide6')
    qtcore = types.ModuleType('PySide6.QtCore')
    # Minimal stand-ins
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
print('Loading Whisper model...')
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f'Using device: {device} | model: {whisper_model}')
model = whisper.load_model(whisper_model, device=device)
print('Loading audio...')
audio_np = _load_audio_as_numpy(audio_path)
print('Transcribing with Whisper...')
result = model.transcribe(audio_np, word_timestamps=True)
segments = result.get('segments', [])
print('Whisper segments:', len(segments))

plain_lines = [l.strip() for l in Path(plain_txt).read_text(encoding='utf-8', errors='ignore').splitlines() if l.strip()]

from rapidfuzz import fuzz as rf
import statistics


def _parse_lrc_output(raw_lrc: str):
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


def _evaluate(gt, pred):
    matched = 0
    time_diffs = []
    per = []
    for gt_t, gt_text in gt:
        best_score = -1
        best_time = None
        best_pred = None
        for p_t, p_text in pred:
            score = rf.token_sort_ratio(gt_text, p_text)
            if score > best_score:
                best_score = score
                best_time = p_t
                best_pred = p_text
        td = abs(gt_t - best_time) if best_time is not None else None
        per.append({
            'gt_t': gt_t,
            'gt_text': gt_text,
            'pred_text': best_pred,
            'pred_t': best_time,
            'score': best_score,
            'time_diff': td,
        })
        if best_score >= 70 and best_time is not None:
            matched += 1
            time_diffs.append(td)
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
    res = {
        'coverage_pct': coverage,
        'matched': matched,
        'total_gt': len(gt),
        'mean_abs_s': mean,
        'median_abs_s': median,
        'p95_abs_s': p95,
        'p99_abs_s': p99,
    }
    return res, per


gt = parse_lrc(lrc_path)

if mode == "viterbi":
    print("Running worker align in Viterbi mode...")
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
    )
    pred = _parse_lrc_output(raw_lrc)
    eval_res, per = _evaluate(gt, pred)
    print("Viterbi eval:", eval_res)
    out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_worker_viterbi.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'eval': eval_res, 'per': per}, indent=2), encoding='utf-8')
    print('Saved report to', out)
elif mode == "forced":
    print("Running worker forced-align mode...")
    raw_lrc = _worker_cls._forced_align_plain_lyrics_whisperx(
        audio_np=audio_np,
        plain_lines=plain_lines,
        language=result.get('language', 'en'),
        device=device,
    )
    pred = _parse_lrc_output(raw_lrc)
    eval_res, per = _evaluate(gt, pred)
    print("Forced-align eval:", eval_res)
    out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_worker_forced.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'eval': eval_res, 'per': per}, indent=2), encoding='utf-8')
    print('Saved report to', out)
elif mode == "auto":
    print("Running worker auto strategy selector mode...")
    section_anchors = _worker_cls._detect_audio_section_anchors(audio_np, 16000)
    candidates = []
    raw_ext = _worker_cls._forced_align_plain_lyrics_external(
        audio_path=audio_path,
        plain_lines=plain_lines,
        language=result.get('language', 'en'),
    )
    if raw_ext:
        candidates.append(("forced_external", raw_ext))
    raw_forced = _worker_cls._forced_align_plain_lyrics_whisperx(
        audio_np=audio_np,
        plain_lines=plain_lines,
        language=result.get('language', 'en'),
        device=device,
    )
    if raw_forced:
        candidates.append(("forced_whisperx", raw_forced))
    raw_viterbi = _align(
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
    if raw_viterbi:
        candidates.append(("viterbi", raw_viterbi))
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
    if raw_fuzzy:
        candidates.append(("fuzzy_local", raw_fuzzy))
    if not candidates:
        candidates.append(("segment_fallback", ""))

    scored = []
    score_map = {}
    raw_map = {}
    tuple_map = {}
    score_words = []
    for seg in segments:
        for w in seg.get("words", []):
            if w.get("word", "").strip() and w.get("start") is not None:
                score_words.append({"start": float(w.get("start")), "word": str(w.get("word", ""))})
    best_name = None
    best_raw = ""
    best_score = -1e18
    for name, raw in candidates:
        tuples = _worker_cls._parse_lrc_to_tuples(raw)
        tuples = _worker_cls._repair_local_outliers(tuples, plain_lines=plain_lines, section_anchors=section_anchors)
        tuple_map[name] = tuples
        score = _worker_cls._score_alignment_candidate(
            plain_lines,
            tuples,
            section_anchors=section_anchors,
            words=score_words,
        )
        score_map[name] = score
        raw_map[name] = "\n".join([f"[{ai_module._format_ts(float(s))}] {t}" for s, t in tuples])
        scored.append({"name": name, "score": score, "count": len(tuples)})
        if score > best_score:
            best_score = score
            best_name = name
            best_raw = raw_map[name]
    viterbi_score = score_map.get("viterbi")
    best_tuples = tuple_map.get(best_name, [])
    viterbi_tuples = tuple_map.get("viterbi", [])
    best_has_snap = _worker_cls._has_catastrophic_repeat_snap(best_tuples)
    viterbi_has_snap = _worker_cls._has_catastrophic_repeat_snap(viterbi_tuples)
    best_has_chrono = _worker_cls._has_repeat_chronology_violation(best_tuples)
    viterbi_has_chrono = _worker_cls._has_repeat_chronology_violation(viterbi_tuples)
    best_local_ev = _worker_cls._local_evidence_score(plain_lines, best_tuples, score_words)
    viterbi_local_ev = _worker_cls._local_evidence_score(plain_lines, viterbi_tuples, score_words)
    if (
        (best_name or "").startswith("forced")
        and viterbi_score is not None
        and (best_local_ev <= (viterbi_local_ev + 3.0) or best_has_snap or best_has_chrono)
    ):
        best_name = "viterbi"
        best_score = viterbi_score
        best_raw = raw_map.get("viterbi", best_raw)
    elif viterbi_score is not None and (best_has_snap or best_has_chrono) and not (viterbi_has_snap or viterbi_has_chrono):
        best_name = "viterbi"
        best_score = viterbi_score
        best_raw = raw_map.get("viterbi", best_raw)
    pred = _parse_lrc_output(best_raw)
    eval_res, per = _evaluate(gt, pred)
    print("Auto selected:", best_name, "score=", best_score)
    print("Auto eval:", eval_res)
    out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_worker_auto.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'selected': best_name, 'score': best_score, 'candidates': scored, 'eval': eval_res, 'per': per}, indent=2), encoding='utf-8')
    print('Saved report to', out)
elif mode == "viterbi-grid":
    time_weights = [2.0, 4.0, 6.0]
    step_weights = [0.2, 0.35]
    pos_weights = [10.0, 25.0, 40.0]
    repeat_weights = [0.5, 1.0, 1.5]
    band_factors = [6.0, 8.0]
    print(
        f"Running Viterbi grid: {len(time_weights) * len(step_weights) * len(pos_weights) * len(repeat_weights) * len(band_factors)} configs..."
    )
    rows = []
    for tw in time_weights:
        for sw in step_weights:
            for pw in pos_weights:
                for rw in repeat_weights:
                    for bf in band_factors:
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
                            viterbi_time_weight=tw,
                            viterbi_step_weight=sw,
                            viterbi_pos_weight=pw,
                            viterbi_init_pos_weight=30.0,
                            viterbi_band_factor=bf,
                            viterbi_prev_window_factor=10.0,
                            viterbi_repeat_weight=rw,
                        )
                        pred = _parse_lrc_output(raw_lrc)
                        eval_res, _ = _evaluate(gt, pred)
                        rows.append(
                            {
                                "time_weight": tw,
                                "step_weight": sw,
                                "pos_weight": pw,
                                "repeat_weight": rw,
                                "band_factor": bf,
                                "eval": eval_res,
                            }
                        )
    rows_sorted = sorted(
        rows,
        key=lambda x: (
            x["eval"]["mean_abs_s"] if x["eval"]["mean_abs_s"] is not None else 1e9,
            x["eval"]["p95_abs_s"] if x["eval"]["p95_abs_s"] is not None else 1e9,
            x["eval"]["p99_abs_s"] if x["eval"]["p99_abs_s"] is not None else 1e9,
            x["eval"]["median_abs_s"] if x["eval"]["median_abs_s"] is not None else 1e9,
        ),
    )
    best = rows_sorted[0]
    print("Best Viterbi config:", best)
    print("Top 10 Viterbi configs:")
    for i, row in enumerate(rows_sorted[:10], start=1):
        e = row["eval"]
        print(
            f"{i:02d}. tw={row['time_weight']}, sw={row['step_weight']}, pw={row['pos_weight']}, "
            f"rw={row['repeat_weight']}, bf={row['band_factor']} | "
            f"mean={e['mean_abs_s']:.3f}, median={e['median_abs_s']:.3f}, p95={e['p95_abs_s']:.3f}, p99={e['p99_abs_s']:.3f}"
        )
    out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_worker_viterbi_grid.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"best": best, "top10": rows_sorted[:10], "all": rows_sorted}, indent=2), encoding="utf-8")
    print("Saved Viterbi grid report to", out)
else:
    # Grid tune only requested params.
    repeat_penalties = [0.0, 10.0, 25.0, 50.0, 75.0, 100.0, 150.0]
    min_repeat_gaps = [0, 2, 4, 6, 8, 12]

    print(f'Running grid: {len(repeat_penalties) * len(min_repeat_gaps)} configs...')
    grid = []
    for rp in repeat_penalties:
        for mrg in min_repeat_gaps:
            raw_lrc = _align(
                plain_lines,
                segments,
                enable_fuzzy=True,
                fuzzy_threshold=60,
                fuzzy_window_words=12,
                repeat_penalty=rp,
                max_backtrack=0.5,
                enable_viterbi=False,
                min_repeat_gap=mrg,
            )
            pred = _parse_lrc_output(raw_lrc)
            eval_res, _ = _evaluate(gt, pred)
            grid.append({
                'repeat_penalty': rp,
                'min_repeat_gap': mrg,
                'eval': eval_res,
            })

    grid_sorted = sorted(
        grid,
        key=lambda x: (
            x['eval']['mean_abs_s'] if x['eval']['mean_abs_s'] is not None else 1e9,
            x['eval']['median_abs_s'] if x['eval']['median_abs_s'] is not None else 1e9,
        ),
    )
    best = grid_sorted[0] if grid_sorted else None
    print('Best config:', best)
    print('Top 10 configs:')
    for i, row in enumerate(grid_sorted[:10], start=1):
        e = row['eval']
        print(
            f"{i:02d}. repeat_penalty={row['repeat_penalty']}, "
            f"min_repeat_gap={row['min_repeat_gap']}, "
            f"mean={e['mean_abs_s']:.3f}, median={e['median_abs_s']:.3f}, coverage={e['coverage_pct']:.1f}%"
        )

    # Save details for best config
    best_raw_lrc = _align(
        plain_lines,
        segments,
        enable_fuzzy=True,
        fuzzy_threshold=60,
        fuzzy_window_words=12,
        repeat_penalty=best['repeat_penalty'],
        max_backtrack=0.5,
        enable_viterbi=False,
        min_repeat_gap=best['min_repeat_gap'],
    )
    best_pred = _parse_lrc_output(best_raw_lrc)
    best_eval, best_per = _evaluate(gt, best_pred)

    out = Path('tools') / 'whisperx_test_output' / (Path(audio_path).stem + '_worker_grid_tuning.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                'best': best,
                'top10': grid_sorted[:10],
                'all': grid_sorted,
                'best_eval': best_eval,
                'best_per': best_per,
            },
            indent=2,
        ),
        encoding='utf-8',
    )
    print('Saved grid report to', out)
