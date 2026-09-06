# stable-ts Research Benchmark Notes

Commit: `research(ai): benchmark stable-ts known-text alignment`

The adapter is research-only and is not registered in the production backend
router. It supports stable-ts full known-text alignment and local alignment
from caller-provided candidate segments, while converting the result into the
shared `AlignmentResult` contract.

## Local environment

- isolated runtime: `%LOCALAPPDATA%\PyLrcGet\research\stable-ts`
- Python: 3.13.15
- stable-ts: 2.19.1
- model smoke-test: `tiny.en` (72.1 MB)
- device: CPU
- test audio: synthetic WAV in `%TEMP%`

## Smoke-test result

The package imported successfully and the full alignment API returned a valid
line-level result. On the synthetic five-second tone, model load was about
`3.1 s` and alignment about `1.9 s`. stable-ts emitted its expected low-signal
alignment warnings on synthetic audio, so this is an API/runtime check, not a
quality result.

Quality and p50/p95 comparisons still require the real English, Romanian, and
Romance-language corpus. The package remains excluded from `pyproject.toml`
and from Auto routing because the upstream repository is archived and the
quality gate has not been met.
