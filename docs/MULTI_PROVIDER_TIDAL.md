# Multi-provider lyrics and TIDAL (#57)

PyLrcGet keeps LRCLIB as the default lyrics source and adds a provider-neutral
router. Provider order and enablement are configured in Settings → Lyrics →
Lyrics Sources. Provider-specific options are available in the Providers tab.

## Provider setup

The Providers tab contains a selector for each configured source:

- LRCLIB: configure the server URL used for downloading and publishing.
- TIDAL: configure the country, developer Client ID, and OAuth redirect URI.

LRCLIB remains enabled by default. TIDAL is disabled until it is enabled in the
Lyrics Sources priority list.

## TIDAL setup

The native transport uses the official TIDAL API:

1. Open Settings → Lyrics → Providers and select TIDAL.
2. Enter the TIDAL Client ID and redirect URI
   `http://127.0.0.1:8765/callback`.
3. Press `Connect TIDAL` and finish the browser login.
4. Enable TIDAL in Lyrics Sources and move it to the desired priority.
5. Save the settings, then use Download missing lyrics.

OAuth access and refresh tokens are stored in the operating-system keyring;
they are not written to the PyLrcGet database or UI JSON.

The TIDAL provider resolves local metadata to a catalogue track first. ISRC is
preferred; artist/title metadata is used when ISRC is unavailable. The resolved
provider track ID is then passed to the official lyrics relationship transport.
Remote mappings are cached and invalidated when identity-relevant metadata
changes.

The public TIDAL API can return an empty lyrics relationship even when the
consumer-facing TIDAL application displays lyrics. PyLrcGet treats that as a
clean TIDAL miss and continues to the next enabled provider. It does not call
undocumented internal endpoints.

## Matching and provenance

The router keeps the existing modes: Prefer synced, Synced only, and Plain
only. A provider result is scored before it can be accepted, and low-confidence
TIDAL catalogue matches are rejected. The selected lyrics source is stored
separately for plain and synced lyrics; older rows remain unknown rather than
receiving fabricated attribution.

Bulk downloads use one metadata read, duplicate lookup collapse, bounded
pending futures, per-provider concurrency limits, a per-run result cache, and
per-batch provider health state. Transient errors are not cached. Fatal
authentication or configuration failures can disable that provider for the
current batch while allowing other enabled providers to continue.

## Local benchmark

The benchmark harness never contacts LRCLIB or TIDAL:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\venv\Scripts\python.exe tools/perf/benchmark_multi_provider.py `
  --tracks 250 --duplicate-every 5 --workers 4 --warmups 2 --runs 3
```

Reports are written to `benchmarks/results/` when an output path is supplied.
Do not use a user's music folder as a writable corpus; scanner benchmarks
support `--read-only-source` for initial and unchanged measurements.
