# PyLrcGet AI Sync v2 Results

Status: lab branch `ai/lyrics-sync-v2-lab`  
Date: 2026-09-06  
Reference Music folder: only shortcut metadata was read; its contents were not
traversed and no file was modified.

This report separates measured runtime smoke-tests from quality measurements.
Synthetic audio validates process/API behavior only; it is not evidence that a
backend is accurate on singing.

## Runtime environments

| Runtime | Python | Main packages | Purpose |
| --- | --- | --- | --- |
| application venv | 3.14.2 | PySide6, Mutagen, existing WhisperX stack | app and full tests |
| AI runtime | 3.13.15 | Torch 2.8.0 CPU, torchaudio 2.8.0, WhisperX 3.8.6, librosa 1.0.0, g2p-en | production AI service |
| stable-ts research | 3.13.15 | stable-ts 2.19.1, Torch 2.14.0 CPU | isolated research |
| SOFA research | 3.8.10 | Torch 2.4.1 CPU, torchaudio 2.4.1, upstream requirements | isolated research |
| HubertFA ONNX research | 3.10.0 | ONNX Runtime 1.23.2 CPU, librosa 0.9.2 | isolated research |

The English `lyrics-aligner` checkpoint is 40,357,640 bytes and is stored only
under `%LOCALAPPDATA%\PyLrcGet\lyrics-aligner`. The stable-ts `tiny.en`
checkpoint is 75,571,315 bytes and is stored only under
`%LOCALAPPDATA%\PyLrcGet\models\stable-ts`.

## Quality baseline

The existing five-track benchmark in `AI_SYNC_EXPERIMENTS.md` remains the
quality reference:

| Pipeline | Macro mean error | Macro p95 error | Interpretation |
| --- | ---: | ---: | --- |
| release v1.14.1 | ~37.59 s | ~80.63 s | historical baseline |
| current English lyrics-aligner routing | ~1.67 s | ~12.04 s | production quality reference |

Those values are historical measurements from the existing real five-track
corpus. They were not replaced by synthetic-audio results.

An additional read-only share sample contained four usable English audio/LRC
pairs. Three sequential service runs produced the following aggregate:

| Sample | Repeated runs | Median wall/run | Macro mean error | Macro p95 error | Coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| read-only share English sample | 3 | 50.873 s | 3.244 s | 20.005 s | 100% |

This sample uses the sidecar LRC timestamps as ground truth and is useful as a
local sanity check, but it is not directly comparable to the historical
five-track macro because the cases differ.

## Warm English runtime

The real `lyrics-aligner` backend was exercised with a local synthetic six-
second WAV and `hello world`:

| Run | Wall time | Coverage | Checkpoint loads | Result |
| --- | ---: | ---: | ---: | --- |
| first persistent job | 3,560.8 ms | 1.0 | 1 | valid LRC |
| second job, same service | 105.4 ms | 1.0 | reused | identical LRC |

The second job is approximately 33.8x faster than the first in this smoke
test. The persistent service stayed alive between jobs and reported Python
3.13.15. This demonstrates removal of per-job process/checkpoint overhead; it
does not establish the five-track quality gate.

On the four-case read-only share sample, every request completed through the
warm English backend with `enable_demucs_candidate=false`; all three measured
runs returned 100% line coverage. The service was reused across the complete
sequence.

The backend also ran directly in 3,198.6 ms with one checkpoint load,
`audio_copied: false`, and `align_subprocess: false`.

## stable-ts research runtime

The isolated runner downloaded `tiny.en` and aligned the same type of local
synthetic tone:

| Model load | Alignment | Coverage | Notes |
| ---: | ---: | ---: | --- |
| 3,075.5 ms | 1,880.1 ms | 1.0 | low-signal warnings; API smoke-test only |

The reproducible runner is:

```powershell
$stable = "$env:LOCALAPPDATA\PyLrcGet\research\stable-ts\Scripts\python.exe"
& $stable tools\ai_sync_bench\run_stable_ts.py `
  --corpus .\benchmarks\ai_sync\local-corpus.json `
  --mode full --warmups 1 --runs 3 `
  --output .\benchmarks\ai_sync\stable-ts-full.json
```

stable-ts remains research-only. Its upstream repository is archived, and no
real English/Romanian/Romance quality corpus was available for this run.

## Research backend matrix

| Backend | Languages | Measured quality | Runtime/artifact status | Decision |
| --- | --- | --- | --- | --- |
| English lyrics-aligner | English | existing five-track reference preserved | warm CPU service works; MIT code, checkpoint external | keep/default for known English |
| WhisperX legacy | multilingual fallback | existing compatibility path | AI runtime works; expensive retries now compatibility-gated | keep fallback |
| LyricsAlignment-Multilingual | EN/FR/DE/IT/ES | not measured in this run | model/runtime not configured | keep manifest-only research |
| Generic CTC | model-dependent | no model selected | pluggable contract only; no license-safe singing model selected | keep architecture, no default |
| stable-ts | Whisper languages | synthetic API smoke only | isolated Python 3.13; 75.6 MB tiny model; archived upstream | keep research-only |
| SOFA | English in selected upstream setup | not measured | upstream requests Python 3.8, `.ckpt`, and G2P dictionary; no checkpoint bundled | keep blocked research |
| HubertFA | zh/ja/en/yue | not measured | Python 3.10 ONNX CPU import works; no model/dictionary pair | keep blocked research |

Source checkouts and notes:

- [stable-ts](https://github.com/jianfch/stable-ts)
- [SOFA](https://github.com/qiuqiao/SOFA)
- [HubertFA](https://github.com/wolfgitpr/HubertFA)

## Implemented changes

- long-lived external AI runtime with protocol/version handshake;
- warm English lyrics-aligner with in-process model reuse, G2P cache, and no
  per-song audio copy/subprocess;
- text-first language routing when known lyrics are already available;
- backend-independent `AlignmentResult` and quality validation;
- confidence-gated Demucs candidate;
- research contracts for multilingual singing and generic CTC backends;
- hierarchical regions, structural candidate DP, and manual anchors;
- optional bounded local Whisper rescue;
- bounded model caches, decoded-audio reuse, phonemization service, and
  packaging/license policy;
- conservative legacy WhisperX retry policy. Set
  `PYLRCGET_AI_LEGACY_FULL_RETRIES=1` to restore the previous full retry stack
  for compatibility comparisons;
- reproducible stable-ts benchmark runner and multilingual/structural stress
  tests.

## Correctness and regression status

```text
583 passed
1 warning
5 subtests passed
```

The warning is the existing Windows `torchcodec`/FFmpeg DLL warning from the
application venv. It is not caused by the research adapters. The new stress
suite covers English, Romanian, French, Spanish, repeated-chorus candidate
selection, bounded candidate counts, sparse evidence fallbacks, and validator
flags.

## Routing recommendation

```text
known English lyrics
    -> text-first detection
    -> warm lyrics-aligner
    -> Demucs only when confidence is low
    -> validator and final LRC

known non-English lyrics
    -> legacy WhisperX compatibility fallback
    -> structural/Viterbi selection
    -> optional bounded local rescue

no known lyrics
    -> legacy WhisperX transcription/alignment
```

Research backends must stay out of Auto routing until a real singing corpus
meets coverage, p95, catastrophic-error, packaging, and licensing gates.

## Answers to the release questions

1. Warm English sync removes the repeated model/process startup cost; the
   local smoke-test improved from 3,560.8 ms to 105.4 ms.
2. Startup/checkpoint load is paid once per persistent service instead of once
   per job.
3. Yes. Known ordinary English lyrics route from text evidence without full
   Whisper language detection.
4. The conditional Demucs path is implemented and was disabled for the strict
   four-case warm-backend measurement; a corpus comparison is still required
   before quantifying necessity.
5. No Romanian backend can be recommended from the available measured data;
   legacy WhisperX remains the safe fallback.
6. The same applies to French/German/Spanish/Italian; the multilingual
   candidate remains research-only.
7. Generic CTC has not been promoted because no model-specific singing result
   and license evidence are available.
8. Source-separation benefit remains confidence-gated and corpus-dependent.
9. Structural DP and stress tests protect monotonic/repeated-block behavior;
   the four-case share sample also reached 100% line coverage, but real
   comparative deltas still require the five-track corpus.
10. The default retry change avoids the automatic extra full-song passes; the
    exact count must be measured on a real fallback corpus.
11. Legacy WhisperX remains the fallback for unsupported or failed backends.
12. Yes, until a replacement meets the quality gates.
13. English lyrics-aligner code is MIT; research model artifact licenses remain
    unresolved where noted above.
14. Research models should download on demand, never as core application
    dependencies.
15. The routing recommendation is the conservative table shown above.

## Remaining release gates

The branch is not claiming final promotion of stable-ts, SOFA, HubertFA,
multilingual singing, or generic CTC. To close those gates, run the provided
benchmark tools against a curated read-only singing corpus containing English,
Romanian, one Romance language, repeated choruses, gaps, live/remaster
variants, and ground-truth timestamps. Do not use the user Music folder as a
write target; any future run against it must remain explicitly read-only.
