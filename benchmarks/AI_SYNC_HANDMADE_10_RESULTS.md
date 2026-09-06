# AI lyrics synchronization benchmark — 10-track corpus

Date: 2026-09-06  
Branch: `ai/lyrics-sync-v2-lab`  
Benchmark commit: `0108acd`  
Platform: Windows 11, CPU-only  

## Scope and reference data

The test used ten tracks from the read-only Music share. Nine tracks had
handmade timed `.lrc` files. `05 Spirit of the Forest` had only a handmade
plain `.txt`, so its synchronized reference was taken from the LRCLIB record
[33716507](https://lrclib.net/api/get/33716507). No file on the Music share was
created, changed, renamed, or deleted.

The LRCLIB record matches the track duration, but its text is more complete and
has different line segmentation than the handmade `.txt`. Therefore the first
nine tracks are the primary handmade accuracy set; Spirit is a secondary,
external-reference comparison and is not a claim of handmade parity.

All models received the same plain lyric text for a given case. The corpus was
run with `language=en`; `Kädet siipinä` is intentionally retained as a
compatibility stress case. Timings are CPU wall-clock measurements after one
warmup where supported.

## Backends tested

| Backend | Model/runtime | Runs | Status |
| --- | --- | ---: | --- |
| `lyrics-aligner` | production default, persistent external runtime, Python 3.13 | 3/case | application candidate |
| `stable-ts` | `tiny.en`, full known-text alignment | 3/case | research |
| legacy WhisperX | `base`, CPU `int8`, fallback forced | 1 for first 9, 3 for Spirit | comparison only |
| HubertFA | `1218_hfa_model_new_dict` ONNX | 1/case | research; approximate line mapping |
| SOFA | `tgm_en_v100` | 1/case | research; approximate line mapping |

The benchmark measures line-start timestamp error against the supplied
reference. It does not judge vocal quality or lyric transcription quality.

## Aggregate results — first nine handmade timed tracks

| Backend | Total case medians | Mean/case | Coverage | Mean line error | Median case mean error | Full-coverage cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `lyrics-aligner` | 118.60 s | 13.18 s | 100.0% | 3.10 s | 1.55 s | 9/9 |
| `stable-ts tiny.en` | 18.89 s | 2.10 s | 92.4% | 8.07 s | 0.71 s | 4/9 |
| legacy WhisperX base | 99.31 s | 11.03 s | 88.9% | 48.90 s | 50.88 s | 8/9 |
| HubertFA ONNX | 144.09 s | 16.01 s | 95.7% | 6.16 s | 5.24 s | 8/9 |
| SOFA | 50.06 s | 5.56 s | 95.7% | 15.16 s | 12.76 s | 8/9 |

`Total case medians` is the sum of the median per-track timings, not one
single sequential wall-clock run. Research backends have slightly different
model-load/process-startup accounting, so this is a practical comparison,
not a release benchmark.

## Per-track results — time / coverage / mean error

| Track | lyrics-aligner | stable-ts | WhisperX | HubertFA | SOFA |
| --- | ---: | ---: | ---: | ---: | ---: |
| Atlantis | 22.87 s / 100% / 1.55 s | 2.10 s / 97.6% / 2.33 s | 22.32 s / 100% / 50.88 s | 17.28 s / 100% / 0.56 s | 5.83 s / 100% / 6.01 s |
| Library | 9.88 s / 100% / 1.09 s | 2.57 s / 95.2% / 2.34 s | 15.78 s / 100% / 15.21 s | 10.59 s / 100% / 0.30 s | 4.95 s / 100% / 1.75 s |
| Do You Miss Me at All | 16.37 s / 100% / 0.97 s | 1.97 s / 100% / 0.71 s | 14.15 s / 100% / 35.77 s | 14.08 s / 100% / 0.81 s | 5.36 s / 100% / 5.24 s |
| Snap My Fingers | 15.08 s / 100% / 0.44 s | 1.41 s / 100% / 0.61 s | 3.41 s / 0% / n/a | 12.96 s / 100% / 1.24 s | 5.24 s / 100% / 7.20 s |
| Cottages and Saunas | 14.64 s / 100% / 5.83 s | 1.92 s / 75.0% / 23.83 s | 5.30 s / 100% / 101.29 s | 12.74 s / 100% / 6.54 s | 5.29 s / 100% / 12.76 s |
| Journey Man | 7.24 s / 100% / 1.46 s | 1.55 s / 96.8% / 0.70 s | 3.34 s / 100% / 58.96 s | 8.49 s / 100% / 5.24 s | 5.03 s / 100% / 19.93 s |
| Fields in Flames | 13.17 s / 100% / 2.00 s | 2.41 s / 100% / 0.50 s | 9.20 s / 100% / 113.71 s | 16.77 s / 100% / 5.89 s | 5.88 s / 100% / 21.81 s |
| Native Land | 11.80 s / 100% / 3.68 s | 3.35 s / 66.7% / 41.11 s | 11.72 s / 100% / 51.05 s | 32.01 s / 100% / 13.11 s | 6.43 s / 100% / 37.15 s |
| Kädet siipinä | 7.56 s / 100% / 10.89 s | 1.62 s / 100% / 0.51 s | 14.09 s / 100% / 13.21 s | 19.18 s / 60.9% / 21.74 s | 6.05 s / 60.9% / 24.59 s |

## Spirit of the Forest — LRCLIB external reference

| Backend | Median time | Coverage | Mean line error | P95 line error | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| `lyrics-aligner` | 17.32 s | 100% | 4.19 s | 23.19 s | complete output |
| `stable-ts tiny.en` | 5.39 s | 88.9% | 8.46 s | 41.34 s | 16/18 lines |
| legacy WhisperX base | 10.64 s | 100% | 36.20 s | 75.97 s | structurally valid, inaccurate |
| HubertFA ONNX | 27.33 s | 100% | 23.34 s | 48.52 s | line mapping approximation |
| SOFA | 7.51 s | 100% | 17.70 s | 43.08 s | line mapping approximation |

## Decisions

1. Keep `lyrics-aligner` as the production default. It is the only tested
   backend with 100% line coverage on all ten cases and the best aggregate
   mean error among the production-compatible paths, although it has outliers
   on a few difficult songs.
2. Keep `stable-ts` research-only. It is by far the fastest backend, but its
   missed lines and large failures on `Cottages and Saunas` and `Native Land`
   make it unsuitable as the default without a quality gate/fallback.
3. Do not use legacy WhisperX as the primary synchronized-lyrics backend.
   Several outputs contained repeated/non-monotonic timestamps; `Snap My
   Fingers` returned no synchronized output.
4. Keep HubertFA and SOFA isolated experiments. HubertFA was strong on several
   English cases but has dictionary/coverage failures and high outliers;
   SOFA is faster but less accurate overall and also loses Finnish coverage.
5. Do not merge any research backend into the application default based on
   this corpus alone. The next useful step is broader reference coverage,
   especially non-English lyrics and songs with intentional repeats.

## Reproducibility and caveats

- Primary corpus: 9 handmade timed `.lrc` files; 337 reference lines total.
- External case: 18 LRCLIB-timed lines for Spirit.
- `lyrics-aligner` and `stable-ts` used three measured runs per case.
- WhisperX used one full nine-track sweep because it was already clearly
  failing structurally; Spirit was rerun three times after fixing the forced
  fallback setup.
- HubertFA and SOFA use word-level TextGrid output mapped to line starts by
  sequential text matching. Their line metrics are useful for comparison but
  not equivalent to a production adapter's final LRC renderer.
- Model artifacts and all generated WAV/TextGrid/JSON files remain outside the
  repository in local application/temp directories.

