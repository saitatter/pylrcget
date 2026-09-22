# PyLrcGet benchmark summary

Updated: 2026-09-16

This file keeps the conclusions from the local performance and AI experiments
after removing generated per-run reports and raw result files from the
repository. The benchmark runners remain available under
[tools/perf/](../tools/perf/) and [tools/ai_sync_bench/](../tools/ai_sync_bench/).

All Music-share measurements used the reference location
C:\Users\saita\AppData\Roaming\Microsoft\Windows\Network Shortcuts\Music
read-only. No file in that location was created, changed, renamed, or deleted.
Generated databases, fixtures, and model outputs were stored in temporary or
local application directories.

## Scanner: optimized Mutagen

Historical measurements: Windows, Python 3.14.2, four workers, median of
three measured runs after warmups. They were collected before the project was
pinned to Python 3.13.15; the recorded Python version describes the benchmark
environment, not the current supported runtime.

| Scenario | Main | Optimized Mutagen | Delta |
|---|---:|---:|---:|
| 1k initial | 591.2 ms | 603.2 ms | +2.0% |
| 1k unchanged | 11.2 ms | 207.1 ms | +1,753% |
| 10k initial | 5,758.3 ms | 6,542.6 ms | +13.6% |
| 10k unchanged | 102.4 ms | 2,076.7 ms | +1,928% |
| 4,989-file network initial | 12,632.6 ms | 14,285.7 ms | +13.1% |
| 4,989-file network unchanged | 653.7 ms | 3,286.7 ms | +403% |

The optimized path is slower in these measurements because the old main path
did not verify sidecars on unchanged audio. That old behavior missed a newly
created sidecar. The optimized path correctly distinguishes sidecar changes
and achieved:

- zero Mutagen reads for unchanged audio;
- zero Mutagen reads for sidecar-only changes;
- correct detection of a new sidecar beside unchanged audio;
- metadata reuse from the database for sidecar-only updates.

The local 100-file worker sweep favored one or two workers; a single network
run favored eight. Four workers remains the safest general default because
the best setting is storage-dependent.

Decision: keep the correctness and unnecessary-work eliminations. Do not claim
a full-scan wall-time win until sidecar signature checks are optimized further.

## LRCLIB pipeline

Fixture-backed duplicate corpus: 250 tracks, 50 unique lookup keys, three
measured runs:

| Metric | Result |
|---|---:|
| Unique lookups | 50 |
| Deduplicated tracks | 200 |
| HTTP requests | 50 |
| Requests per track | 0.20 |
| Successful matches | 250 / 250 |
| Pending Future high-water mark at 4 workers | 16 |

The fixed concurrency sweep did not justify adaptive concurrency:

| Workers | Median time | Pending high-water |
|---:|---:|---:|
| 2 | 7.749 ms | 8 |
| 4 | 7.778 ms | 16 |
| 6 | 8.941 ms | 24 |
| 8 | 9.233 ms | 32 |

An experimental fallback threshold of 95 reduced synthetic fallback traffic
from 300 to 100 requests with 250/250 matches, but remains opt-in until a
broader quality corpus is available. Bulk metadata reads, bounded futures,
lookup deduplication, and shared 429 coordination are retained. Adaptive
concurrency and a redundant per-run cache are not promoted.

## AI synchronization

Ten-track comparison, with nine handmade timed references and one LRCLIB
reference. The production English lyrics-aligner remains the default:

| Backend | CPU total | GPU total | GPU delta | GPU coverage | GPU mean error |
|---|---:|---:|---:|---:|---:|
| lyrics-aligner | 135.07 s | 154.39 s | 14.3% slower | 100% | 3.21 s |
| stable-ts tiny.en | 24.32 s | 3.99 s | 83.6% faster | 92% | 8.11 s |
| legacy WhisperX | 109.95 s | 18.62 s | 83.1% faster | 90% | 53.13 s |
| HubertFA ONNX | 171.92 s | 132.44 s | 23.0% faster | 100% | 7.96 s |
| SOFA | 57.57 s | 59.34 s | 3.1% slower | 100% | 15.48 s |

GPU availability does not guarantee lower end-to-end time: lyrics-aligner is
dominated by audio preparation and alignment overhead. lyrics-aligner is
English-only; known non-English lyrics use the legacy WhisperX compatibility
fallback. stable-ts, HubertFA, and SOFA remain research-only.

## TagLib

TagLib was tested only after the optimized Mutagen path:

| Measurement | Mutagen | TagLib |
|---|---:|---:|
| Metadata-only median on 100 files | 66.752 ms | 18.601 ms |
| End-to-end scanner median | 138.145 ms | 142.129 ms |

TagLib produced 92 normalized metadata differences out of 100 files and was
2.9% slower end-to-end. The isolated binding declared GPL-3.0-or-later while
PyLrcGet is MIT. Decision: do not add TagLib as a dependency or production
backend.

## Final verification

At the time of consolidation:

619 passed
1 warning
5 subtests passed
ruff check .: passed

The warning is the known optional TorchCodec/FFmpeg DLL warning in the local
AI environment. It is unrelated to scanner, LRCLIB, or TagLib decisions.
