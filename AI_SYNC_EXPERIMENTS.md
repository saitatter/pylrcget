# AI Sync Experiments and Knowledge Base

This document records experiments performed on the local benchmark set:

`C:\Users\andrvoicu\Downloads\music_test`

The `.lrc` files in that folder were used only as ground truth for evaluation.
They must not be used as input by the runtime synchronizer.

## Benchmark and interpretation

The important metrics are:

- `mean_abs_s`: mean absolute error of line start timestamps.
- `p95_abs_s`: error of the worst 5% of lines; this exposes catastrophic chorus
  or tail collapses that the mean can hide.
- `max_abs_s`: largest line error.
- `rtf`: processing time divided by audio duration.

WhisperX CPU results are not perfectly deterministic between runs. Small changes
of 1-2 seconds should not be treated as meaningful without repeated runs.

## Current production pipeline

The active implementation is in `src/ui/workers/ai_sync_worker.py`:

1. WhisperX transcription.
2. Fixed-window ASR (`60s` window, `45s` step) when VAD coverage is sparse or
   the tail is missing.
3. `condition_on_previous_text=False` for independent chunks.
4. WhisperX forced alignment, with per-chunk alignment when global alignment
   loses a meaningful tail.
5. Candidate filtering using confidence, lexical vocabulary, density and tail
   re-entry rules.
6. Monotonic Viterbi alignment from plain lyric lines to ASR words.
7. Repeat-aware rewind penalties, late-position priors and tail rescue.
8. Coarse timestamp fallback when forced alignment drops the ASR tail.

The most reliable global improvement was enabling
`condition_on_previous_text=False`. Historical benchmark:

- mean error: about `11.41s -> 7.73s`
- mean p95: about `42.92s -> 29.54s`
- improvement was observed on 4 of 5 tracks.

Against release `v1.14.1`, the improved pipeline was measured at roughly:

- mean error: `36.19s -> 8.95s`
- p95: `76.51s -> 30.52s`

The exact values vary across CPU runs.

## Experiments that were rejected

### Demucs as the primary input

Demucs vocal separation was tested with multiple model sizes. It did not
produce a consistent gain and introduced variable latency/alignment shifts.
The medium model helped selected songs; small was weaker and large was too
slow without a reliable global improvement. Do not make Demucs the default
input.

### Whisper initial prompt containing the lyrics

Passing the complete lyrics as `initial_prompt` caused hallucinated or
multilingual text. It was removed.

### Global shorter ASR windows

`30s/20s` windows helped isolated regions, especially `Upside Down`, but
regressed other songs. Keep the longer fixed-window default and use shorter
windows only in a guarded experiment.

### Aggressive lexical filtering

Strict confidence/density or anti-hallucination filters removed real sung words.
On `House of Sleep`, real tokens such as `don't`, `know`, `nothing` and `yet`
were removed from a repeated chorus, causing Viterbi to jump to a later chorus.
Limited in-vocabulary restoration helped one run (`16.98s -> 8.69s`) but was
not consistently beneficial across all tracks.

### Adaptive retry on suspicious regions

Retrying selected regions with shorter windows or more aggressive VAD degraded
`Upside Down` and was withdrawn.

### Larger Whisper beam size

`beam_size=10` helped some songs but regressed `House of Sleep` and
`Upside Down`, while being slower. It is not the global default.

### RMS/spectral prior

Mix RMS activity identified active audio but did not identify which repeated
line was being sung. The gain was negligible (for example about `7.00s ->
6.99s` on `House of Sleep`) and there was a small regression on `Upside Down`.
Do not use mix RMS as a primary timestamp signal.

### TTS comparison

Synthesized speech does not match singing reliably because of timbre, rhythm,
accent, sustained vowels and phrasing. TTS should not be used as the main
alignment signal.

### Direct lyrics-guided WhisperX alignment

The complete known lyrics were passed directly to the WhisperX CTC alignment
model, without Whisper transcript text. This is not sufficient because one
global forced path compresses lyrics across instrumental gaps and repeated
choruses.

Representative results:

| Track | mean error | p95 |
| --- | ---: | ---: |
| House of Sleep | 18.09s | 32.21s |
| Keelhauled | 12.37s | 24.79s |
| Nancy the Tavern Wench | 2.21s | 6.80s |
| See You in Hell (acoustic) | 77.31s | 206.73s |
| Upside Down | 93.10s | 170.89s |

### Whisper anchors plus one forced-alignment window per line

Whisper chunked anchors were used to define one local window per lyric line.
This helped `House of Sleep` but regressed `Upside Down` and other tracks.
Incorrect anchors force the aligner to search in the wrong region.

### Multiple forced-alignment windows per line

Three nearby windows (`-3s`, `0s`, `+3s`) were scored by mean acoustic
confidence. Results were inconsistent and cost roughly 3x the alignment time.
One run gave a small improvement from about `8.97s -> 8.49s`, but regressions
remained. Acoustic confidence is not calibrated enough to choose globally.

## Qwen3-ForcedAligner experiment

The package was installed only in the local `.venv313` experiment environment;
it was not added to `pyproject.toml` and must not become a core dependency.

Model tested:

`Qwen/Qwen3-ForcedAligner-0.6B`

### Qwen with complete lyrics

The complete plain lyrics were aligned against the complete audio:

| Track | Qwen mean error | p95 |
| --- | ---: | ---: |
| House of Sleep | 38.36s | 59.24s |
| Keelhauled | 12.56s | 23.30s |
| Nancy the Tavern Wench | 46.77s | 78.08s |
| See You in Hell (acoustic) | 26.33s | 55.81s |
| Upside Down | 24.92s | 63.09s |

Qwen was better than direct WhisperX on `Upside Down` and `See You in Hell`,
but worse on `House of Sleep` and `Nancy`, and much worse than the active
chunked pipeline.

### Qwen with Whisper-anchored chunks

Whisper chunked anchors were used to group lyric lines into 60-second audio
regions. This was too coarse; Qwen compressed local instrumental gaps.

Using 20-second regions was better:

| Track | Whisper baseline | Qwen 20s |
| --- | ---: | ---: |
| House of Sleep | 10.88s | **6.40s** |
| Keelhauled | 14.15s | **13.64s** |
| Nancy the Tavern Wench | 4.25s | 6.79s |
| See You in Hell (acoustic) | 14.68s | 14.98s |
| Upside Down | 4.84s | 6.20s |

The average change was negligible (`9.76s -> 9.60s`), with clear regressions.
Qwen is therefore rejected as a global replacement for now.

## Qwen3-ASR-1.7B experiment

The `qwen-asr==0.0.6` package was used in `.venv313`. The model was tested
without changing `pyproject.toml`:

`Qwen/Qwen3-ASR-1.7B`

### Plain ASR transcription

CPU inference was very slow:

- `House of Sleep`: about 126 seconds.
- `Upside Down`: about 147 seconds.

The transcript was sometimes more fluent than Whisper, but still changed
important sung words and line structure. Examples:

- `House of Sleep`: `I will make you see` instead of `I will make you sleep`;
  `Sweet dreams`/`Sweetest love` hallucination-like substitutions.
- `Upside Down`: `As the pages turn` instead of `As the pages burn`;
  `I'll die`/`Don't cry`/`hide in the skies` instead of the known chorus.

Better prose transcription does not imply better lyric synchronization.

### Integrated Qwen forced alignment

The official integrated path was also tested:

```text
Qwen3ASRModel.from_pretrained(
    "Qwen/Qwen3-ASR-1.7B",
    forced_aligner="Qwen/Qwen3-ForcedAligner-0.6B",
)
```

On `House of Sleep`, timestamp output contained long runs with `0.0` or the
same repeated timestamp (for example many tokens at `55.76s`). The result did
not preserve the long-song timeline and is unusable as direct LRC input.

This may be related to the model's long-audio chunk merge/alignment behavior,
but it is not worth making it an application dependency until chunked input is
validated separately. For now Qwen3-ASR-1.7B is rejected for runtime
synchronization, just like Qwen3-ForcedAligner as a global replacement.

## Important failure observations

### House of Sleep

- Repeated chorus lines are easy to map to the wrong occurrence.
- Confidence/density filtering can remove genuine low-confidence sung words.
- The tail contains repeated `You don't know...` material and needs strict
  progression handling.

### Upside Down

- Whisper can compress the `118-145s` region into a hallucinated segment such
  as `I'm so down, you fool yourself and you're hiding the skies.`
- The late tail around `153-179s` can be transcribed incompletely.
- Global shorter windows, beam size changes and adaptive retries were not safe
  defaults.

### General

- VAD often misses sung or softly sung portions even when the audio is active.
- Forced alignment cannot recover a region that was assigned to the wrong
  temporal window.
- Repeated choruses require sequence-level constraints, not just local lexical
  similarity.
- Mean error alone is misleading; always inspect p95, max error and line-level
  outliers.

## Recommended next experiments

Do not change the production default without a five-track benchmark.

1. Improve the candidate selector with a calibrated confidence gate and a
   no-regression fallback to the current Whisper/Viterbi timestamp.
2. Use multiple candidate windows only for low-confidence or structurally
   suspicious lines, not for every line.
3. Use Whisper/Qwen only as local acoustic evidence; retain Viterbi monotonic
   ordering and repeat-aware constraints as the final decision layer.
4. Benchmark a singing-specific aligner such as SOFA separately. SOFA requires
   an older Python 3.8 environment and a phoneme dictionary/model, so it should
   remain isolated from the main Python 3.13 environment.
5. Record repeated benchmark runs and report median plus p95, not one CPU run.

## Environment notes

- Main application environment currently uses Python 3.14 and cannot install
  the current WhisperX dependency set because `ctranslate2==4.4.0` has no
  compatible cp314 wheel.
- AI experiments were run in `.venv313` with Python 3.13.
- Recommended AI setup remains:

  `py -3.13 -m venv venv313`

  `venv313\Scripts\python.exe -m pip install torch torchaudio whisperx soundfile`

- Optional experimental Qwen installation:

  `venv313\Scripts\python.exe -m pip install qwen-asr==0.0.6`
