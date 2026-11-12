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
