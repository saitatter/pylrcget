# Release notes

Each change updates the `Unreleased` section of `CHANGELOG.md` with a short
English entry under Features, Fixes, Refactors, Docs or CI & Build. Explain the
outcome for users, grouping related changes. Keep emoji out of these files.
Fixes and Refactors apply to published behavior; update the original Features
entry for corrections to unreleased work.

Run the Release workflow manually on `main`. Conventional commits determine
the version. The changelog template moves the reviewed Unreleased entries under
the new version and date, preserves historical entries, and leaves an empty
Unreleased section. Semantic-release commits the changelog and package version
before creating the tag. Do not bump versions or tag manually.

The release description contains `Changes since last release:`, a short
summary, a separator, and `What's Changed`: every non-merge commit in the tag
range once, oldest first, with author and commit links. GitHub supplies new
contributor credits and the comparison link. The default summary comes from
the released changelog entries; an optional editorial summary can be recorded
in `docs/release-summaries.json`, keyed by release tag with a `summary` list.

Preview with `python tools/release_notes.py --tag vX.Y.Z`; apply to an existing
release with `--write`. This changes only the release description, not tags,
assets or package versions. The Release workflow applies it automatically.
The GitHub CLI must be authenticated and release tags/history available locally.

## Personalized artwork

Each release opens with the PyLrcGet music-studio banner. Customize up to six
short highlight strings in the release tag's `items` array in
`docs/release-summaries.json`; its `summary` array remains the release description.
The artwork adds the version, date, previous version, commit count, contributors,
referenced issues addressed, open issues and stars. Repository metrics are captured
when the image is first rendered, normally during publication. Historical previews
use current repository metrics, not reconstructed past counts.

Install rendering dependencies with `pip install -e ".[release]"`. Preview local
work without creating a tag or publishing anything:

```powershell
python tools/release_banner.py --tag v1.16.0 --preview --out "$env:TEMP/pylrcget-preview.webp"
```

Use `--set item_1="Custom highlight"` to override a highlight, or `--set stars=42`
to override a numeric field in a local preview. The output includes a JSON snapshot.
Render that snapshot again without GitHub access with `--data snapshot.json`.

The Release workflow invokes `release_notes.py --banner --write`. It stores the
WebP and JSON snapshot on the orphan `release-banners` branch, then links the image
at its immutable commit in the release description. The artwork does not appear in
the application downloads. Existing per-tag artwork is reused, never overwritten.
Keep this branch and its history: removing it can break past release images.
The existing `RELEASE_PAT` must be allowed to create and update that branch.
