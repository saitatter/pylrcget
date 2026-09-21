# PyLrcGet

PyLrcGet is a native PySide6 desktop app for browsing a local music library,
finding and editing synced/plain lyrics, playing tracks, exporting sidecars,
embedding lyrics, and publishing to LRCLIB.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-Qt-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)

## What it does

- Scans folders recursively into SQLite, with incremental refresh and exclusion rules.
- Browses Tracks, Albums, Artists, Album Artists, Lyrics Browser, and Lyrics Activity.
- Downloads lyrics through an ordered provider matrix.
- Supports LRCLIB by default and optional Musixmatch website/API transports.
- Edits synced or plain lyrics, tracks unsaved drafts, and highlights lyrics during playback.
- Exports `.lrc`/`.txt` sidecars and optionally embeds lyrics into supported formats.
- Provides local AI Auto Sync with CUDA when available and CPU fallback.
- Includes playback controls, custom speed, volume, themes, keyboard shortcuts, and logs.

Provider settings are opt-in: a disabled provider is never used as an automatic
fallback. See [Musixmatch provider notes](docs/MULTI_PROVIDER_MUSIXMATCH.md).

## Screenshots

Add final captures under `docs/screenshots/` when the visual set is ready.
These are the most useful views for the project page:

| File | Capture |
|---|---|
| `tracks-light.png` | Tracks + lyrics panel in the Light theme, with a selected track. |
| `tracks-dark.png` | The same view in the Dark theme, showing the normal browsing hierarchy. |
| `lyrics-editor.png` | Synced lyrics editor with timestamps, toolbar, and playback controls. |
| `empty-lyrics.png` | Missing-lyrics state with provider actions visible. |
| `settings-providers.png` | Provider matrix and per-provider settings. |
| `responsive-narrow.png` | Narrow window showing the compact command bar and usable lyrics pane. |

When added, place the corresponding Markdown image links here, for example:

```markdown
![Tracks in the Light theme](docs/screenshots/tracks-light.png)
```

## Quick start

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python main.py
```

The core application supports Python 3.10+. Python 3.13 is recommended for
the optional AI runtime. The app does not modify a music folder during normal
scanning; exports and embedding are explicit user actions.

## Optional AI Auto Sync

```powershell
python -m pip install -e ".[ai]"
```

The packaged app can install the AI stack into its own runtime. WhisperX
supports the multilingual path; `lyrics-aligner` is used for English when it
is available. CUDA is selected automatically when available, but GPU is not
guaranteed to be faster for every backend.

If the bootstrap interpreter must be selected explicitly:

```powershell
$env:PYLRCGET_AI_BOOTSTRAP_PYTHON = "C:\Path\to\python.exe"
```

Optional Demucs is used only as a candidate vocal-stem path and is not
required for the base AI workflow.

## Lyrics providers

| Provider | Default | Notes |
|---|:---:|---|
| LRCLIB | Yes | Download, search, and publish support. |
| Musixmatch | No | Website transport needs no key; official API accepts a user-provided key. |

Enable and order providers in `Settings -> Lyrics -> Providers`. Provider
matching uses artist, title, album, duration, and version metadata. Full
transport limitations are documented in
[docs/MULTI_PROVIDER_MUSIXMATCH.md](docs/MULTI_PROVIDER_MUSIXMATCH.md).

## Supported audio formats

| Format | Scan | Lyrics read/write | Sidecar export |
|---|:---:|:---:|:---:|
| MP3, WAV | Yes | Yes | Yes |
| M4A / MP4 | Yes | Yes | Yes |
| FLAC, OGG / OGA, OPUS | Yes | Yes | Yes |
| WMA / ASF | Yes | Yes | Yes |
| DSF, DFF, MPC / Musepack | Yes | Yes | Yes |

Playback depends on the active backend and installed codecs. Metadata support
can be broader than playback support for a specific format.

## Important settings

| Area | Examples |
|---|---|
| Library | Music folders, exclusions, worker count, scan source, startup view |
| Lyrics | Download mode, provider order, sidecars, embedding, filename pattern |
| AI Sync | Device, language, fuzzy matching, optional Demucs candidate |
| Appearance | Theme, UI scale, font size, album art |
| Shortcuts | Global playback keys and lyrics-editor keys |

Download modes are `Prefer synced`, `Synced only`, and `Plain only`. Export
and embedding format choices are configured independently from download mode.

## Performance and design notes

The scanner separates audio and sidecar state, reuses stored metadata for
unchanged audio, and avoids unnecessary Mutagen and sidecar reads. LRCLIB
bulk work uses batched metadata reads, bounded concurrency, duplicate lookup
collapse, and shared rate-limit coordination.

See the [benchmark summary](benchmarks/RESULTS_SUMMARY.md) for measured
results, known trade-offs, and the TagLib decision. The benchmark harnesses
are documented in [tools/perf/README.md](tools/perf/README.md) and
[tools/ai_sync_bench/README.md](tools/ai_sync_bench/README.md).

## Development

Run the test suite and static checks from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m pytest
ruff check .
```

Useful focused commands:

```powershell
python -m pytest tests/widgets_navigation -q
python tools/perf/benchmark_lrclib.py --tracks 250 --duplicate-every 5 --warmups 2 --runs 3
```

Performance fixtures and benchmark output are generated under `benchmarks/`;
do not point a mutating benchmark at a real music folder. Read-only source
measurements must use the harness `--read-only-source` option.

## Building

```powershell
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm pylrcget.spec
```

For the portable single-file build:

```powershell
pyinstaller --noconfirm pylrcget-portable.spec
```

## Releases and troubleshooting

Releases use Conventional Commits and semantic-release. See
[CHANGELOG.md](CHANGELOG.md) for published changes.

- **No lyrics found:** check provider enablement/order and the track metadata.
- **AI dependencies missing:** use the AI setup dialog or install the `ai` extra in a supported Python 3.10-3.13 environment.
- **Playback issue:** verify the backend and codec support for the file format.
- **Windows SmartScreen warning:** release executables are currently unsigned.

## License and credits

MIT © saitatter. The project is an independent desktop reimplementation
inspired by the LRCLIB ecosystem and is not a fork of the original LRCGET
application.

Support: [Ko-fi](https://ko-fi.com/saitatter)
