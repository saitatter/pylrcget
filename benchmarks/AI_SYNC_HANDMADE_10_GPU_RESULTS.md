# AI lyrics synchronization — GPU benchmark

Date: 2026-09-06  
GPU: NVIDIA GeForce RTX 4070 Ti SUPER, 16 GB  
Audio source: `\\MOS\\Music` / `C:\\Users\\saita\\AppData\\Roaming\\Microsoft\\Windows\\Network Shortcuts\\Music`  
Source access: read-only; all generated outputs were written under `%TEMP%`.  
Branch: `ai/lyrics-sync-v2-lab`

## What was tested

The same ten-track corpus used by the CPU benchmark was run with an explicit
CUDA device. The first nine tracks have hand-timed lyrics; `Spirit of the
Forest` uses the synced LRCLIB record `33716507` as its reference.

Each cell below is `elapsed time / line coverage / mean absolute line error`.
Times are per-case medians for the three-run backends. HubertFA and SOFA were
run once per case in a fresh process because their research CLIs do not expose
the application worker protocol.

| Case | lyrics-aligner | stable-ts | WhisperX | HubertFA | SOFA |
|---|---:|---:|---:|---:|---:|
| 01 | 22.24s / 100% / 1.5s | 0.35s / 98% / 2.3s | 4.13s / 100% / 50.9s | 15.12s / 100% / 0.6s | 12.12s / 100% / 6.0s |
| 02 | 10.67s / 100% / 1.1s | 0.38s / 95% / 2.3s | 2.84s / 100% / 15.6s | 4.11s / 100% / 0.3s | 5.74s / 100% / 1.7s |
| 03 | 16.98s / 100% / 1.0s | 0.34s / 100% / 0.7s | 3.00s / 100% / 35.9s | 11.94s / 100% / 0.8s | 5.22s / 100% / 5.2s |
| 04 | 15.74s / 100% / 0.4s | 0.28s / 100% / 0.6s | 0.55s / 0% / n/a | 9.54s / 100% / 1.2s | 5.24s / 100% / 7.2s |
| 05 | 16.64s / 100% / 5.8s | 0.34s / 75% / 23.8s | 0.59s / 100% / 101.3s | 10.79s / 100% / 6.5s | 5.25s / 100% / 12.8s |
| 06 | 9.52s / 100% / 1.5s | 0.30s / 97% / 0.7s | 0.45s / 100% / 59.0s | 6.22s / 100% / 5.2s | 4.92s / 100% / 19.9s |
| 07 | 16.72s / 100% / 2.0s | 0.42s / 100% / 0.5s | 1.23s / 100% / 113.7s | 14.01s / 100% / 5.9s | 5.10s / 100% / 21.8s |
| 08 | 14.87s / 100% / 3.7s | 0.54s / 67% / 41.1s | 1.61s / 100% / 48.5s | 31.41s / 100% / 13.1s | 5.46s / 100% / 37.2s |
| 09 | 9.15s / 100% / 10.9s | 0.28s / 100% / 0.5s | 2.27s / 100% / 8.6s | 11.94s / 100% / 22.6s | 4.90s / 100% / 25.3s |
| 10 Spirit (LRCLIB) | 17.65s / 100% / 4.2s | 0.76s / 89% / 8.5s | 1.80s / 100% / 32.1s | 17.36s / 100% / 23.3s | 5.39s / 100% / 17.7s |

## GPU versus CPU

The CPU all-ten totals combine the existing nine-track measured corpus with
the separately measured LRCLIB `Spirit` case. They are useful directional
comparisons; the research backends do not all use identical process-lifetime
protocols.

| Backend | CPU all-10 | GPU all-10 | GPU delta | GPU coverage | GPU mean error | Decision |
|---|---:|---:|---:|---:|---:|---|
| lyrics-aligner | 135.07s | 154.39s | 14.3% slower | 100% | 3.21s | Keep production default; do not force GPU for speed |
| stable-ts tiny.en | 24.32s | 3.99s | 83.6% faster | 92.0% | 8.11s | GPU works, but quality remains experimental |
| legacy WhisperX | 109.95s | 18.62s | 83.1% faster | 90.0% | 53.13s | Do not promote; fast but inaccurate |
| HubertFA ONNX | 171.92s | 132.44s | 23.0% faster | 100% | 7.96s | Keep isolated; persistent CUDA session can OOM on long tracks |
| SOFA | 57.57s | 59.34s | 3.1% slower | 100% | 15.48s | Keep isolated research candidate |

The production-oriented `lyrics-aligner` GPU run did use CUDA, but its
end-to-end cost is dominated by audio preparation and alignment overhead. GPU
is therefore available, not automatically faster.

### Follow-up: vectorized CUDA DTW

The initial GPU result above used the upstream NumPy DTW path. A controlled
same-process comparison on the same ten tracks isolated that path:

| DTW implementation | Total |
|---|---:|
| NumPy/CPU DTW | 159.17s |
| Vectorized CUDA DTW | 127.50s |
| Change | **19.9% faster** |

All ten generated LRC outputs were byte-for-byte equivalent between the two
DTW implementations. The CUDA implementation is now used only when the
lyrics-aligner device is CUDA; CPU and MPS keep the existing upstream path.
The original CPU/GPU table remains as the pre-optimization baseline, while
this controlled result isolates the optimization without mixing in model-load
or process-lifetime differences.

## Device support conclusion

| Component | CUDA tested | Notes |
|---|---:|---|
| lyrics-aligner | Yes | CUDA path ran, but CPU was faster in this corpus |
| stable-ts | Yes | `torch 2.8.0+cu128`; large speedup, quality unchanged |
| legacy WhisperX | Yes | `torch 2.8.0+cu128`; large speedup, quality problem remains |
| HubertFA | Yes | `onnxruntime-gpu`; CUDA arena growth caused an OOM in a persistent session |
| SOFA | Yes | `torch 2.4.1+cu124`; no meaningful end-to-end speedup |
| Mutagen scanner | Not applicable | Metadata/filesystem work is CPU/I/O-bound |

The application `Auto` setting now resolves to CUDA, then MPS, then CPU when
the selected runtime actually exposes that device. Explicit unavailable
devices still fail clearly. This behavior is covered by
`tests/ai/test_ai_device.py`.

## Language finding: lyrics-aligner

`lyrics-aligner` is English-only in the current implementation:

- `EnglishLyricsAlignerBackend.supports_language()` accepts only `en`.
- `EnglishG2PPhonemizer.supports_language()` accepts only `en`.
- The default router registers it only for `en`; other languages use the
  fallback backend.

It can be used for English lyrics even when the artist or title contains
non-English text. It should not be treated as a Finnish, Romanian, or general
multilingual lyrics aligner. The Finnish-looking corpus case was deliberately
run through the English experiment and therefore is not evidence of Finnish
support.

## Raw reports

The machine-readable GPU reports remain in `%TEMP%`:

- `pylrcget-handmade-lyrics-aligner-gpu.json`
- `pylrcget-handmade-stable-gpu.json`
- `pylrcget-handmade-whisperx-gpu.json`
- `pylrcget-handmade-hubertfa-gpu.json`
- `pylrcget-handmade-sofa-gpu.json`

No file in the Music reference folder was modified.
