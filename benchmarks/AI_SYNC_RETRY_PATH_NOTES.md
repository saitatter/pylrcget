# AI Sync Retry-Path Delta

Commit: `perf(ai): stop redundant full-song whisper retries by default`

The v2 fallback now uses a conservative retry policy by default:

- the initial WhisperX pass remains unchanged;
- the automatic fixed-window tail recovery is disabled;
- the automatic short-window full-song retry is disabled;
- low-coverage recovery keeps only the first relaxed-VAD pass on CPU;
- CUDA already used one relaxed-VAD configuration and is unchanged.

The previous retry stack is available for compatibility/debug comparisons with:

```text
PYLRCGET_AI_LEGACY_FULL_RETRIES=1
```

With that flag, the fixed-window tail recovery, short-window retry, and all
three CPU relaxed-VAD configurations remain enabled.

This increment was validated by the focused AI test suite. A quality/runtime
comparison on the real five-track corpus remains a release gate; no public
LRCLIB or user Music files are used by this change.
