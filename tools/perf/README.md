# Performance harness

These scripts measure the current scanner and bulk LRCLIB pipeline without
changing application state. Run them with the project virtual environment:

```powershell
python tools/perf/generate_test_library.py .\benchmarks\corpora\small --tracks 1000 --formats wav
python tools/perf/benchmark_scan.py --library .\benchmarks\corpora\small --scenario initial --warmups 2 --runs 3
python tools/perf/benchmark_scan.py --library .\benchmarks\corpora\small --scenario unchanged --warmups 2 --runs 3
python tools/perf/benchmark_scan.py --library "\\MOS\Music" --scenario initial --read-only-source --warmups 2 --runs 3
python tools/perf/benchmark_scan.py --library "\\MOS\Music" --scenario unchanged --read-only-source --warmups 2 --runs 3
python tools/perf/benchmark_scan.py --library "\\MOS\Music" --scenario initial --read-only-source --lightweight --warmups 2 --runs 3
python tools/perf/benchmark_worker_sweep.py --library .\benchmarks\corpora\small --workers 1,2,4,8 --warmups 2 --runs 3
python tools/perf/benchmark_worker_sweep.py --library "\\MOS\Music" --read-only-source --workers 1,2,4,8 --warmups 0 --runs 1
python tools/perf/benchmark_lrclib.py --tracks 250 --duplicate-every 5 --warmups 2 --runs 3
```

The scripts write JSON and Markdown reports below `benchmarks/results/` by
default. Each scan sample uses a temporary copy of the input corpus and a
temporary database. Incremental scenarios warm up the same database, apply a
deterministic mutation, and then measure the second scan.

`benchmark_lrclib.py` is fixture-backed by default. It never sends requests to
the public LRCLIB service. The generated fixture provides exact matches and
can be made duplicate-heavy with `--duplicate-every`.

Supported scan scenarios are:

```text
initial, unchanged, audio-changed, sidecar-added, sidecar-changed,
sidecar-removed, sidecar-renamed, mixed
```

For format diversity, `generate_test_library.py` can use an installed
`ffmpeg` executable with `--formats mp3,flac,m4a,ogg,opus,wma,wav`; WAV-only
corpora do not need external tools.

Compare two reports with:

```powershell
python tools/perf/compare_results.py baseline.json candidate.json
```
