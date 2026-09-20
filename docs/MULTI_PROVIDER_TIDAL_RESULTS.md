# Multi-provider lyrics and TIDAL (#57) results

## Architecture summary

The branch introduces `TrackLookupContext`, `LyricsProviderResult`, provider
capabilities, a priority router, result selection, provider error
classification, per-batch health state, bounded result caching, and
provider-specific execution limits. LRCLIB is still the default enabled
provider and continues to use the existing `LrcLibAPI` and matching/retry
behavior.

TIDAL is split into three boundaries:

- `TidalCatalogueClient` resolves official catalogue metadata and track IDs,
  preferring ISRC and falling back to confident metadata matching.
- `TidalOAuthSession` performs OAuth 2.1 + PKCE and stores refreshable tokens in
  the OS keyring.
- `TidalLyricsTransport` retrieves lyrics after resolution. The native
  implementation requests the official track `lyrics` relationship; the
  versioned external helper protocol remains optional.

The `TidalProvider` adapter joins those boundaries and returns the same
provider-neutral result shape as LRCLIB. Persistence, sidecar export,
embedding, and editor behavior remain in the existing application layers.

## Migration summary

The database is currently schema version 10. The migration set preserves
existing tracks and lyrics, adds ISRC storage, remote provider mappings, and
separate plain/synced lyrics provenance. Existing provenance remains `NULL`
when it cannot be known historically. The remote mapping is unique per
`(track_id, provider)` and is invalidated by identity-relevant metadata changes,
not by lyrics edits.

Fresh and upgraded databases are covered by migration tests, including rows
with downloaded, embedded, sidecar, manual, and unknown lyrics state.

## Matching and fallback results

Deterministic fixtures cover:

- exact ISRC resolution and normalized ISRC forms;
- multiple equivalent candidates with stable provider-ID tie breaking;
- confident artist/title/album/duration matching;
- clear metadata mismatch rejection;
- Czech and Unicode metadata;
- live/studio version penalty;
- plain fallback followed by a synced result from a later provider;
- provider errors, cancellation, and download-mode selection.

The router accepts a synced result immediately, keeps a plain result as a
fallback for synced-preferred mode, and preserves the existing Synced only and
Plain only semantics. Fatal helper/auth/configuration failures can disable a
provider for the current batch; 429, timeout, and 5xx conditions remain
transient and are not cached as permanent failures.

## TIDAL fixture results

Catalogue and provider tests verify that:

- ISRC lookup is attempted before metadata search;
- metadata search works without ISRC;
- nested artist/album relationships are normalized;
- low-confidence candidates are rejected;
- the resolved remote ID is passed to the lyrics transport;
- plain and synced helper payloads become provider-neutral results;
- helper cancellation, timeout, non-zero exit, invalid JSON, and output-size
  limits are handled safely.

No live TIDAL or LRCLIB test is run by the suite, so public services are not
stress-tested and no credentials are required for CI.

## Bulk benchmark

Command used on Windows, Python 3.14.2, two warmups and three measured runs:

```powershell
$env:PYTHONPATH = "$PWD\\src"
.\venv\Scripts\python.exe tools/perf/benchmark_multi_provider.py `
  --tracks 250 --duplicate-every 5 --workers 4 --warmups 2 --runs 3
```

This is a local deterministic fixture benchmark. It does not measure public
network latency.

| Metric | Median |
|---|---:|
| Tracks processed | 250 |
| Unique lookup keys | 50 |
| Duplicates avoided | 200 |
| Requests saved | 190 |
| LRCLIB attempts | 50 |
| TIDAL attempts | 10 |
| LRCLIB direct-ID/search | 25 / 25 |
| TIDAL direct-ID/search | 5 / 5 |
| Successful matches | 250 / 250 |
| Total fixture time | 1.080 ms |
| Pending Future high-water mark | 16 |
| Result-cache hits | 0 |

The zero cache-hit value is expected: duplicate jobs are collapsed before
submission, so the cache is a safety net for repeated completed lookups rather
than a replacement for deduplication. Its LRU bound is 8,192 entries by
default.

## Known TIDAL API limitation

The public TIDAL API can return an empty lyrics relationship even when the
consumer-facing TIDAL application displays lyrics. PyLrcGet treats that as a
clean TIDAL miss and continues to LRCLIB or another configured provider. It
does not call undocumented internal endpoints.

## Release recommendation

Keep the multi-provider architecture and native OAuth/API transport. Keep the
experimental internal transport disabled. The external helper remains an
optional fallback. Do not persist raw credentials in PyLrcGet settings; the
refreshable session uses the operating-system keyring.

Packaging impact: the small `keyring` dependency was added for secure token
storage. No TIDAL SDK, native library, or bundled helper was added.

## Future-provider notes

Future providers should implement only the provider contract and return
normalized results. They should use their own authentication, matching
diagnostics, rate-limit cooldown, concurrency policy, and transport. They must
not write database lyrics fields, audio tags, sidecars, or editor state
directly. Publishing to LRCLIB remains LRCLIB-specific.

## Verification

The branch was verified with the complete pytest suite: **746 passed, 1
warning, 5 subtests passed**. Ruff also passes. The only known test warning is
the pre-existing optional TorchCodec/FFmpeg DLL warning from the local AI
environment.
