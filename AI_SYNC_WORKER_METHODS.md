# AI Sync Worker — Technical Detection & Alignment Methods

This document describes the **core detection/alignment methods** used by the AI sync pipeline in `src/ui/workers/ai_sync_worker.py`.
It focuses on algorithmic behavior (what is detected, why, and how), not on a function-by-function API listing.

---

## 1. End-to-end detection pipeline

The runtime pipeline is:

1. **ASR + forced alignment** to obtain timestamped word candidates.
2. **Candidate reliability detection** (lexical, confidence, density, tail checks).
3. **Global sequence alignment** (Viterbi over line→word mappings).
4. **Tail-collapse detection and rescue** for repeated/ambiguous endings.
5. **LRC reconstruction** preserving original plain-lyrics layout.

The system is designed to remain robust when ASR text is imperfect, repeated choruses exist, and late-song coverage is unstable.

---

## 2. Lexical emission detection (line ↔ word-window compatibility)

For each plain lyric line and each candidate ASR start index, the worker computes an **emission score** in `[0,1]`:

- It compares line tokens against a local ASR window.
- Matching is fuzzy (RapidFuzz-based).
- Matches that require skipping too deep into the window are penalized.

### Why this matters

This is the primary “is this line likely spoken here?” detector.  
If emissions are noisy (common in tails), the system relies more on global priors and rescue logic.

### Concrete lyric example

Plain line: `About the dreams I have`  
Candidate windows:
- Window A around `~95s`: partial overlap, score ~0.55
- Window B around `~229s`: stronger overlap, score ~0.82

Emission detection should prefer B, unless ASR quality collapses.

---

## 3. Speech-candidate detection and hard gating

Before dynamic programming, the worker builds a **hard candidate mask** over ASR words.
A word is considered alignable only if it passes layered gates:

1. **Speech-like token gate** (non-lexical/noise-like tokens removed).
2. **Confidence gate** with different thresholds for:
   - in-vocabulary tokens (present in plain lyrics vocabulary),
   - out-of-vocabulary tokens.
3. **Temporal density gate** (isolated spikes are downweighted/removed).
4. **Tail cutoff** after last reliable dense speech region.
5. **Tail re-entry exception**: if a late phrase is lexically plausible and has a strong anchor token, it is re-enabled.

### Why this matters

This reduces instrumental/noise hallucinations and dramatically shrinks the Viterbi state space.

### Concrete lyric example

Late words at `228–229s`: `you don't know nothing`  
If dense speech ended near `160s`, naive cutoff would drop them.  
Tail re-entry detection restores these words when they are in-vocab and anchored, preventing false early collapse.

---

## 4. Anchor detection (confidence-based structural guidance)

The worker detects sparse **high-confidence, low-ambiguity anchor tokens** and maps them to approximate line positions.

Anchor shaping gives local score boosts/penalties around anchor neighborhoods, helping global alignment remain monotonic and stable.

### Why this matters

In repeated songs, lexical similarity alone is insufficient; anchors provide structural hints with strong precision.

---

## 5. Repeat-aware rewind detection

Repeated lines (choruses/refrains) are a major failure mode:
multiple timeline clusters can look lexically similar.

The worker detects repeated phrases and builds **expected cluster progression targets**.  
Then it applies:

- **state-level rewind penalties** (line mapped too early vs expected cluster),
- **transition-level rewind penalties** (consecutive lines staying in the wrong early cluster).

### Concrete lyric example

Line `You don't know` appears 4 times.  
If occurrence #4 is mapped to cluster #2 instead of #4, rewind penalties push alignment forward.

---

## 6. Late-tail positional priors (weak-emission regime)

When late lines have weak lexical evidence, the system activates tail-specific priors:

- **Expected-position bonus** near late expected timeline locations.
- **Candidate start floor** to avoid searching far back in early clusters for clearly late lines.

### Why this matters

This addresses the common “tail line snapped to mid-song chorus” behavior without globally forcing late bias on high-confidence lines.

---

## 7. Tail collapse detection and rescue

After Viterbi backtracking, the worker performs a dedicated **tail collapse detector**:

- Finds weak-emission tail lines.
- Compares aligned positions against expected timeline/index progression.
- If enough lines lag significantly, triggers rescue:
  - lifts tail lines to a floor near expected late positions,
  - enforces monotonic progression.

Two detection modes exist:
- **time-based** (preferred for sparse tails),
- **index-based** fallback.

### Concrete lyric example

Expected tail around `~220s`, aligned tail around `~122s`  
=> rescue shifts late lines forward into plausible end-of-song region.

---

## 8. Coverage-failure detection and relaxed-VAD retry

ASR/VAD can truncate speech coverage (especially long tracks).
The worker detects this via:

- minimum duration / minimum lyric-line guards,
- **reliable tail coverage ratio**:
  `coverage_ratio = reliable_tail_seconds / track_duration_seconds`,
- minimum uncovered tail gap.

If coverage is poor, a **relaxed VAD** pass is run.

### Selection detector (default vs relaxed)

Relaxed output is selected if either:

1. tail extension is large enough, or
2. a no-GT quality proxy improves:
   `quality = line_match*2 + vocab_ratio + coverage*0.5`.

---

## 9. Manual-anchor guided detection

User-provided anchors (`line_index`, `time_ms`) are converted into line→word constraints.
The worker interpolates guided candidate ranges between anchors and adds strong local shaping around anchor targets.

### Why this matters

It allows deterministic recovery for hard songs while preserving automatic behavior elsewhere.

---

## 10. Global optimization method (Viterbi)

The final mapping is solved as a monotonic dynamic-programming path:

- **State**: `(line_idx, word_idx)`
- **Emission**: lexical compatibility at that state
- **Transition**: progression cost (small/zero for normal forward movement, penalties for degenerate motion)
- **Shaping terms**: anchors, rewind constraints, manual anchors, late-line priors

This yields a globally consistent alignment path, unlike greedy local matching.

---

## 11. Runtime and practical tuning notes

### Main runtime driver

After ASR/alignment, the dominant cost is typically emission+DP scoring.
Recent optimization switched lexical matching to RapidFuzz to reduce this bottleneck.

### Safe tuning directions

- tighten/loosen confidence thresholds in candidate mask,
- adjust late-line priors only for weak-emission lines,
- tune tail-collapse gap thresholds (`seconds` / `word indices`),
- tune relaxed-VAD trigger coverage ratio.

### Risky tuning directions

- globally increasing positional priors (can over-constrain valid repeats),
- aggressive pruning without benchmark coverage (can miss true late alignments).

---

## 12. Interpreting benchmark metrics

- **mean_abs_s**: average absolute timestamp error per matched line.
- **p95_abs_s**: tail-quality indicator; sensitive to collapse failures.
- **rtf**: runtime factor (`processing_time / audio_duration`).

In practice:
- lower `mean_abs_s` = better overall placement,
- lower `p95_abs_s` = fewer catastrophic tail failures,
- lower `rtf` = faster runtime.

