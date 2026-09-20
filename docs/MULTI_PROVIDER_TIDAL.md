# Multi-provider lyrics and TIDAL (#57)

PyLrcGet keeps LRCLIB as the default lyrics source and adds a provider-neutral
router. Provider order and enablement are configured in Settings → Lyrics →
Lyrics Sources. Existing LRCLIB behavior remains the default when no new
source is enabled.

## TIDAL setup

The native transport is the default path and does not require an external
helper:

1. Open Settings → Lyrics.
2. Enter the TIDAL Client ID and redirect URI
   `http://127.0.0.1:8765/callback`.
3. Select `Official API`, press `Connect TIDAL`, and finish the browser login.
4. Enable TIDAL in Lyrics Sources and move it to the desired priority.
5. Save the settings, then use Download missing lyrics.

OAuth access and refresh tokens are stored in the operating-system keyring;
they are not written to the PyLrcGet database or UI JSON. The helper transport
remains available as an optional fallback.

The TIDAL provider resolves local metadata to a catalogue track first. ISRC is
preferred; artist/title metadata is used when ISRC is unavailable. The
resolved provider track ID is then passed to the configured lyrics transport.
Remote mappings are cached and invalidated when identity-relevant metadata
changes.

The helper receives one JSON object on stdin and must return one JSON object on
stdout. The protocol is version 1:

```json
{
  "protocol_version": 1,
  "provider": "tidal",
  "track": {
    "title": "Example Song",
    "artists": ["Artist"],
    "album": "Album",
    "duration_seconds": 243.2,
    "isrc": "USABC1234567"
  },
  "provider_track_id": "123456789",
  "requested_mode": "prefer_synced"
}
```

A successful response contains `ok: true`, the same provider track ID, and at
least one of `plain_lyrics` or `synced_lyrics`. A clean miss can return
`ok: false` with `error` set to `not_found`, `no_lyrics`, or `unsupported`.

Commands are parsed into argv and launched with `shell=False`. The helper has
a bounded timeout, stderr is captured for diagnostics, and cancellation
terminates the process with a kill fallback. The default request does not
include a local path, library root, OS username, or lyrics content.

The native path uses the official TIDAL API with a bearer token and requests
the track's `lyrics` relationship. TIDAL may return an empty relationship for
tracks whose lyrics are not exposed to third-party applications; that is
treated as a clean miss and the configured fallback provider can continue.

The optional helper remains user-owned and is launched with `shell=False`.

## Native API status

The official client now includes OAuth 2.1 + PKCE, token refresh, authenticated
catalogue resolution, and the official track `lyrics` relationship transport.
The `Experimental internal` transport remains disabled. Empty public lyrics
responses are not retried through undocumented endpoints; LRCLIB remains the
safe configured fallback.

## Matching and provenance

The router keeps the existing modes: Prefer synced, Synced only, and Plain
only. A provider result is scored before it can be accepted, and low-confidence
TIDAL catalogue matches are rejected. The selected lyrics source is stored
separately for plain and synced lyrics; older rows remain unknown rather than
receiving fabricated attribution.

Bulk downloads use one metadata read, duplicate lookup collapse, bounded
pending futures, per-provider concurrency limits, a per-run result cache, and
per-batch provider health state. Transient errors are not cached. Fatal helper
or authentication/configuration failures can disable that provider for the
current batch while allowing configured fallback providers to continue.

## Local benchmark

The benchmark harness never contacts LRCLIB, TIDAL, or a helper:

```powershell
$env:PYTHONPATH = "$PWD\\src"
.\venv\Scripts\python.exe tools/perf/benchmark_multi_provider.py `
  --tracks 250 --duplicate-every 5 --workers 4 --warmups 2 --runs 3
```

Reports are written to `benchmarks/results/` when an output path is supplied.
Do not use a user's music folder as a writable corpus; scanner benchmarks
support `--read-only-source` for initial and unchanged measurements.
