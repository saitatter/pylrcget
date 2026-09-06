# TagLib evaluation

TagLib was evaluated only after the Mutagen scanner optimizations were in
place. The test used `pytaglib==3.2.0` in an isolated temporary environment;
it was not installed into the project virtual environment and is not a
runtime dependency of PyLrcGet.

## Results

The metadata-only reader benchmark used the 100-file sample corpus:

| Reader | Median metadata-read time |
|---|---:|
| Mutagen | 66.752 ms |
| TagLib | 18.601 ms |

TagLib was faster for this isolated operation, but the normalized metadata
comparison produced 92 differences out of 100 files. There were no hard read
failures; the differences were mainly duration precision and representation
differences, so this does not meet the required exact parity gate.

The end-to-end scanner benchmark, including the existing Mutagen-based
embedded lyrics path, was:

| Backend | Median scan time |
|---|---:|
| Optimized Mutagen | 138.145 ms |
| Experimental TagLib metadata reader | 142.129 ms |

TagLib was approximately 2.9% slower end-to-end on this corpus and did not
provide the required 20–25% improvement.

## Packaging and license

The isolated binding metadata declared `License-Expression: GPL-3.0-or-later`,
while this project is MIT licensed. Shipping that binding as a normal runtime
dependency would require an explicit compatibility and distribution decision
that has not been resolved.

## Decision

Drop the TagLib backend experiment from production code. Keep Mutagen as the
metadata reader and do not add a TagLib dependency. The experiment fails the
performance, exact-parity, and packaging/license gates. The raw scanner result
is retained in `benchmarks/results/scan-taglib-experimental-sample100-initial.json`.
