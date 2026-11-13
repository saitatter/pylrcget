# Release artwork

`template.png` is original PyLrcGet artwork generated with OpenAI image generation
on 2026-11-13. The Collectarr release dashboard supplied the composition reference;
the studio, music equipment and PyLrcGet branding were generated for this project.
The blank surfaces receive release data from `tools/release_banner.py`. The
invented waveform mark was removed from the background; the renderer composites
the real `src/ui/assets/app-icon.ico` at full fidelity beside the wordmark.

JetBrains Mono and Patrick Hand are distributed under their accompanying SIL
Open Font License notices. The font files and notices were sourced from the
Collectarr App release-artwork directory. No Collectarr application code is used.

Release text and metrics are rendered locally with Pillow, without emoji or
network image dependencies. Store generated per-release WebP images and their
JSON data snapshots outside this source directory; publication keeps them on
the separate `release-banners` branch.
