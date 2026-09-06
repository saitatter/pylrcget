# PyLrcGet performance results

## Executive summary

This report covers the `perf/scan-scrape-lab` branch on Windows, Python
3.14.2, with four scanner workers unless noted otherwise.

The reference source was the read-only network library exposed through
`C:\Users\saita\AppData\Roaming\Microsoft\Windows\Network Shortcuts\Music`,
which resolved to `\\MOS\Music`. It contained 4,989 supported audio files.
All benchmark databases and mutations were local temporary data. No file in
the reference library was written, renamed, or deleted.

The main scanner comparison used two warmups and three measured runs. The
latest cache-batching measurements used one warmup and three measured runs;
their JSON files record the exact run configuration. Synthetic LRCLIB tests
used fixture-backed HTTP and never contacted the public service.

## Scanner: main versus optimized Mutagen

Wall-clock medians, four workers:

| Corpus / scenario | A. main | B. optimized Mutagen | Delta |
|---|---:|---:|---:|
| 1k initial | 591.2 ms | 603.2 ms | +2.0% |
| 1k unchanged | 11.2 ms | 207.1 ms | +1,753% |
| 10k initial | 5,758.3 ms | 6,542.6 ms | +13.6% |
| 10k unchanged | 102.4 ms | 2,076.7 ms | +1,928% |
| 4,989 network initial | 12,632.6 ms | 14,285.7 ms | +13.1% |
| 4,989 network unchanged | 653.7 ms | 3,286.7 ms | +403% |

The current optimized scanner does not pass the requested wall-time targets
against the old main scanner. Its sidecar-aware correctness checks add work on
every unchanged track, while main incorrectly treats an unchanged audio file
as sufficient state.

The important correctness difference is visible in the sidecar regression:

| Scenario on 100-file corpus | main | optimized Mutagen |
|---|---:|---:|
| New `.lrc` beside unchanged audio | 100 unchanged, missed | 99 unchanged, 1 updated |
| Mutagen calls for sidecar-only change | n/a | 0 |

The optimized path therefore achieves the intended parse behavior:

```text
unchanged audio + unchanged sidecars -> 0 Mutagen calls
unchanged audio + changed sidecar    -> 0 Mutagen calls
changed audio                        -> 1 metadata parse per audio file
```

On the current 4,989-file network initial sweep, each full scan opened 4,989
audio files. The optimized 100-file instrumented run opened 100 files on the
initial scan, zero on unchanged rescan, and zero for the sidecar-only update.

### Scanner worker sweep

The local 100-file sweep with three measured runs favored one or two workers:

| Workers | Median initial scan |
|---:|---:|
| 1 | 126.2 ms |
| 2 | 126.2 ms |
| 4 | 135.1 ms |
| 8 | 154.0 ms |

A single direct network run favored eight workers because metadata I/O was
dominating:

| Workers | Network initial scan |
|---:|---:|
| 1 | 26.1 s |
| 2 | 19.0 s |
| 4 | 14.6 s |
| 8 | 12.4 s |

The media-dependent results do not justify changing the conservative general
default of four workers. Eight is a useful explicit setting for a responsive
network share, while one or two can be better for small local corpora.

### Scanner implementation decisions

Merge:

- explicit `track_scan_state` with a safe database migration;
- independent audio and sidecar signatures;
- sidecar-aware unchanged fast path;
- DB metadata reuse for sidecar-only updates;
- embedded/sidecar provenance state;
- `scandir()` sidecar metadata cache and batched candidate resolution;
- unnecessary sidecar content-read elimination;
- one normalized Mutagen tag index per opened audio file;
- low-contention timing counters;
- safe `executemany()` track write batches;
- reference-library oracle and mutation soak test.

Keep under measurement:

- sidecar signature checks: required for correctness, but currently the main
  source of unchanged-scan wall-time regression on this network library;
- four-worker default: retain until storage-specific auto-tuning is justified.

Peak RSS was not available from the current Windows benchmark process for a
reliable comparison, so no memory improvement claim is made.

## LRCLIB results

The duplicate-heavy fixture contained 250 tracks with one equivalent lookup
every five tracks. At four workers:

| Metric | Result |
|---|---:|
| Tracks | 250 |
| Unique lookup keys | 50 |
| Deduplicated tracks | 200 |
| HTTP requests | 50 |
| Requests per track | 0.20 |
| Successful matches | 250 / 250 |
| Pending Future high-water mark | 16 |

The pipeline now bulk-loads track metadata in SQL chunks, groups equivalent
lookups, submits only a bounded number of Futures, fans one result out to all
matching tracks, and coordinates rate-limit cooldown within the bulk run.

The fixed-worker sweep did not justify adaptive concurrency on the fixture:

| Workers | Median time | Requests | Pending high-water |
|---:|---:|---:|---:|
| 2 | 7.749 ms | 50 | 8 |
| 4 | 7.778 ms | 50 | 16 |
| 6 | 8.941 ms | 50 | 24 |
| 8 | 9.233 ms | 50 | 32 |

### Fallback early-exit experiment

With 50 high-confidence duplicate fallback matches:

| Mode | Search requests | Total requests | Matches |
|---|---:|---:|---:|
| Current threshold 100 | 250 | 300 | 250 / 250 |
| Experimental threshold 95 | 50 | 100 | 250 / 250 |

The opt-in threshold 95 saved 200 requests, or 66.7%, on this synthetic
fixture. It remains disabled by default until a broader quality corpus proves
that live/remaster/acoustic/cover and ambiguous-title matches do not regress.

### LRCLIB decisions

Merge:

- bulk metadata query;
- bounded Future submission and cancellation behavior;
- equivalent-lookup deduplication;
- shared 429 cooldown;
- fixture-backed request and quality metrics.

Keep opt-in only:

- `PYLRCGET_LRCLIB_EARLY_SCORE=95..100`; default remains the existing score
  100 behavior.

Drop or do not add:

- a separate per-run result cache: after lookup grouping, each unique key is
  already fetched once per bulk operation, so the cache has no useful hit path;
- adaptive concurrency: the fixed-worker sweep showed no stable benefit and
  higher concurrency increases pending work;
- public-service load tests: all large tests remain fixture-backed.

## TagLib experiment

TagLib was compared only after the optimized Mutagen path existed. The binding
was installed in an isolated temporary environment and never added to the
project.

| Measurement on 100-file sample | Mutagen | TagLib |
|---|---:|---:|
| Metadata-only median | 66.752 ms | 18.601 ms |
| End-to-end scanner median | 138.145 ms | 142.129 ms |

TagLib was faster for isolated metadata reads but produced 92 normalized
metadata differences out of 100 files, mainly duration precision and raw
representation differences. End-to-end it was 2.9% slower, not the required
20–25% faster. The isolated `pytaglib` metadata declared
`GPL-3.0-or-later`, while the project is MIT licensed.

Decision: drop TagLib from production and do not add the dependency. Details
are in [`TAGLIB_EVALUATION.md`](TAGLIB_EVALUATION.md).

## Answers to the acceptance questions

1. Measurable scanner wins: zero audio parses for unchanged and sidecar-only
   changes; lower current-cache sample initial time (127.7 ms instrumented);
   batched sidecar cache lookups; correct sidecar change detection.
2. Merge scanner state/provenance, fast-path, metadata reuse, Mutagen index,
   timing, DB batching, and correctness-tested cache changes.
3. Drop adaptive LRCLIB concurrency, redundant per-run cache, and TagLib.
   Keep fallback early exit opt-in only.
4. Best general default: four workers. Eight was fastest in one network run,
   while one/two won locally; no universal retune is justified.
5. Full scanning: not faster in the measured comparison; +13.6% on 10k and
   +13.1% on the 4,989-file network corpus.
6. Unchanged rescanning: not faster than main; the optimized path is correct
   for sidecars and performs zero Mutagen reads, but costs +1.9–4.0 s in the
   measured 10k/network cases.
7. Sidecar-only updates: correct and zero-audio-parse; 31.96 ms on the latest
   100-file sample versus main's 3.29 ms path, which missed the new sidecar.
8. Audio parses avoided: 100% for unchanged and sidecar-only changes; 4,989
   parses remain necessary for a 4,989-file initial scan.
9. LRCLIB requests saved: 200 of 300 fallback requests in the synthetic
   threshold-95 experiment; duplicate grouping reduced 250 logical tracks to
   50 HTTP lookups in the duplicate-heavy corpus.
10. Match quality: 250/250 in both fallback fixture modes; no default matching
    semantics were changed. Broader quality validation is still required
    before enabling the experimental threshold.
11. 429 behavior: shared cooldown is implemented and tested; no public-service
    stress test was performed, so there is no irresponsible load claim.
12. TagLib does not provide enough end-to-end value over optimized Mutagen.
13. TagLib creates an unresolved GPL-3.0-or-later packaging/license issue.
14. TagLib is dropped, not merged and not kept as an application backend.

## Reproducibility

Benchmark scripts are under `tools/perf/`. Representative raw results are
under `benchmarks/results/`, including the main baseline, current optimized
Mutagen runs, LRCLIB worker/fallback sweeps, and the TagLib evaluation.

The complete test suite at final verification passed:

```text
503 passed, 1 warning, 5 subtests passed
```

The warning is the existing optional `torchcodec`/FFmpeg DLL warning from the
AI test module and is unrelated to scanner or LRCLIB changes.
