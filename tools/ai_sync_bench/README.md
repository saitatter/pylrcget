# AI sync benchmark harness

This harness is the Phase 0 baseline for the AI lyrics synchronization v2
work. It emits a JSON report and a concise Markdown report for every run.

The default backend is deterministic and dependency-free:

```powershell
python tools/ai_sync_bench/run_benchmark.py --backend synthetic --profile smoke --warmups 2 --runs 3
```

Synthetic timings validate the profiler, corpus, aggregation and report
format. They are not model-performance results. The optional `current`
adapter invokes the existing production pipeline directly and requires a
custom JSON corpus with real, read-only audio paths:

```powershell
python tools/ai_sync_bench/run_benchmark.py `
  --backend current `
  --corpus .\benchmarks\ai_sync\local-corpus.json `
  --warmups 2 --runs 3 `
  --output .\benchmarks\ai_sync\current-baseline.json
```

The current adapter does not write audio or lyric files. It only runs the
existing alignment pipeline and writes reports under the requested output
path. Model downloads and optional AI runtime setup must be performed
separately.

The stable-ts research runner must use its isolated interpreter. It supports
full known-text alignment and local alignment from a separate JSON file of
candidate segments:

```powershell
$stable = "$env:LOCALAPPDATA\PyLrcGet\research\stable-ts\Scripts\python.exe"
& $stable tools\ai_sync_bench\run_stable_ts.py `
  --corpus .\benchmarks\ai_sync\local-corpus.json `
  --mode full --warmups 1 --runs 3 `
  --output .\benchmarks\ai_sync\stable-ts-full.json
```

The stable-ts runner is research-only and defaults its model cache to
`%LOCALAPPDATA%\PyLrcGet\models\stable-ts`.

Compare reports with:

```powershell
python tools/ai_sync_bench/compare_backends.py `
  .\benchmarks\ai_sync\baseline.json `
  .\benchmarks\ai_sync\candidate.json
```

Corpus JSON format:

```json
{
  "cases": [
    {
      "id": "song-01",
      "language": "en",
      "category": "exact hit",
      "lines": ["first line", "second line"],
      "expected_timestamps_ms": [1000, 4000],
      "duration_seconds": 8,
      "audio_path": "C:/readonly/corpus/song-01.flac"
    }
  ]
}
```

Keep measured runs comparable by recording commit SHA, Python version,
device, corpus and worker/runtime settings in the JSON metadata.
