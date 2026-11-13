# Local AI validation — 2026-11-13

Verified on Windows, Python 3.13.15, NVIDIA GeForce RTX 4070 Ti SUPER (16 GB),
driver 610.88. This is a local functional and timing check, not a guarantee of
alignment accuracy for other songs, languages or hardware.

## Installation and packaging

- Installed the optional AI stack into a new temporary runtime using the generated
  setup command, with Git and system Python absent from `PATH`. The pinned
  standalone interpreter created the virtual environment and installed the packages.
- Downloaded and verified the pinned English backend and its license. Installed
  CMU pronunciation data and both NLTK tagger resources in the application cache.
- Imported Torch, Torchaudio, WhisperX ASR, SoundFile and Demucs in the fresh runtime.
  English and Romanian inference passed on CPU and Auto with CPU-only Torch.
- Upgraded that isolated runtime through the CUDA installation plan. English
  inference passed on CPU and CUDA; Romanian passed on Auto with CUDA available.
- Built the Windows directory package with `pylrcget.spec`. The external runtime
  successfully imported and ran the AI source copied into that package, including
  the new dependency and pronunciation-data code. The packaged GUI was not launched
  against the user's application data.
- Settings probes reported Ready for the English and multilingual backends in
  CPU, CUDA and Auto modes.

The tested package constraints are declared in `ai_dependencies.py` and matched
by the `ai` extra in `pyproject.toml`. The important versions include Torch and
Torchaudio 2.8.0, WhisperX 3.8.6, Transformers 4.57.6 and Demucs 4.1.0.

## Inference and configuration checks

| Scenario | Result |
| --- | --- |
| English phonetic alignment on CPU, CUDA and Auto | Passed on synthesized speech and two music excerpts in all three modes; full tracks passed on CPU and CUDA. |
| Romanian WhisperX on CPU, CUDA and Auto | Passed with a real Romanian speech sample. |
| Automatic text-language selection | Routed English and Romanian to their corresponding backends. |
| English backend unavailable | WhisperX fallback completed alignment. |
| Fuzzy matching on/off, thresholds 0 and 100 | Completed through the fallback path; English phonetic alignment uses separate scoring. |
| Demucs toggle on/off | Completed; the optional candidate was skipped when mix quality was already high. |
| Direct Demucs separation | CPU and CUDA produced nonempty 44.1 kHz vocal stems from an eight-second music excerpt; temporary stems were removed. |
| Manual timing hints | Completed through guided WhisperX alignment, preserving the hint-aware path. |
| Auto with CUDA hidden | Completed on CPU. |
| Explicit CUDA with CUDA hidden | Returned an actionable unsupported-CUDA error. |
| Cancellation and runtime restart | Cancelled the current job; the same service then completed another job. |
| Missing audio | Returned a failure without a result to save. |
| Unicode audio filename | Completed with a filename containing Romanian and CJK characters. |
| Silent audio with no lyrics | Returned a no-speech failure without synchronized output. |
| No supplied lyrics | WhisperX produced segment-level synchronized text. |
| Real batch with two tracks | Produced two unsaved drafts; committed lyrics remained unchanged. |
| Batch cancellation | Stopped the queue and discarded late results without modifying committed lyrics. |

The Romanian sample came from `google/fleurs`, `ro_ro`, validation row 0, through
the Hugging Face dataset server. It checks the multilingual speech route; it does
not establish Romanian singing accuracy. Synthetic English text was original.

## Music timing against embedded reference lyrics

The user supplied an acoustic recording and a studio recording, each with embedded
synchronized lyrics. Both were copied to temporary local storage before testing.
Inference, clipping, draft writes and reports used only local copies and an isolated
SQLite database. No audio, lyrics text or private source paths are committed here.

Full-song English alignment retained all 34 acoustic lines and all 40 studio lines.
CPU and CUDA produced the same measured timing errors against the embedded reference:

| Recording | CPU time | CUDA time | Median absolute timing error | Largest timing error |
| --- | ---: | ---: | ---: | ---: |
| Acoustic, 326 seconds | 25.60 s | 23.41 s | 0.33 s | 20.24 s |
| Studio, 225 seconds | 12.04 s | 12.94 s | 0.12 s | 9.80 s |

The large outliers mean the output still needs review before saving. A successful
job means the pipeline completed and preserved lyrics, not that every line has
the correct musical onset. These measurements also show that CUDA is not always
faster than CPU for the English backend on short songs.

The subsequent [32-run benchmark](AI_BENCHMARKS.md) separates cold and warm times,
adds p95 and tolerance rates, and compares CPU, CUDA, Auto and optional Demucs.
It includes an exportable figure and anonymized measurements.

After testing, SHA-256, file size and modification time of both network originals
were unchanged. Their existing embedded lyrics were never saved or rewritten.

## Problems found and corrected

- The external English runtime did not search the application's NLTK cache.
  Setup now installs its resources, source and external execution find them, and
  missing pronunciation data is detected for repair.
- Unconstrained installation resolved incompatible Torch/Torchaudio/WhisperX
  versions. Both source and packaged setup now use the tested package constraints;
  unsupported core versions are reported for repair.
- The English backend shortcut bypassed manual timing hints. Hinted jobs now use
  the guided alignment route, and the fuzzy setting describes its actual scope.
- Auto's UI dependency check required CUDA even when a working CPU runtime could
  handle the request. It now accepts CPU fallback while explicit CUDA stays strict.

## Scope and reproduction

Linux, macOS/MPS, other GPUs and the full supported language list were not exercised
on this machine. Run unit tests with `python -m pytest tests/ai -q`. For new read-only
audio corpora, use the production-pipeline adapter described in
`tools/ai_sync_bench/README.md`, keeping generated reports and all audio outside Git.

The detailed local JSON reports include progress and per-case timings. Keep those
reports local when they contain user-selected paths or copyrighted lyric text.

The optional `AI dependency checks` workflow installs the pinned stack and checks
it with CPU Torch. Its equivalent local test run passed 190 AI tests with real
Torch and CUDA hidden, including the tensor parity test omitted by the lightweight
environment. Four non-tensor backend tests now run without optional AI packages.
The fresh runtime emitted an optional TorchCodec/FFmpeg-library warning, but the
tested SoundFile/NumPy audio paths completed successfully.

## Backend comparison and optimization follow-up

[Independent experiments](AI_OPTIMIZATION_EXPERIMENTS.md) compare the actual
WhisperX base and English lyrics-aligner pipelines on full recordings, verify
individual DTW and matching changes, and exercise forced full-length Demucs
stems. These measurements supersede device-only comparisons as evidence for
backend selection on the two English samples. No broader language or model
accuracy claim follows from them.
