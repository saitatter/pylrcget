from tools.release_notes import changelog_summary, render_notes


def test_summary_uses_only_requested_version():
    text = "# Changelog\n\n## Unreleased\n\n- Future\n\n## v1.16.0 (2026-11-12)\n\n### Fixes\n- Install AI\n\n## v1.15.0 (2026-09-23)\n\n- Old\n"
    assert changelog_summary(text, "v1.16.0") == ["Install AI"]


def test_notes_keep_credits_and_compare_without_generated_pr_list():
    generated = "## What's Changed\n* A PR\n\n## New Contributors\n* @someone\n\n**Full Changelog**: https://example.com/compare"
    result = render_notes(["Install AI"], ["- Commit by author (link)"], generated)
    assert result.startswith("Changes since last release:\n\n- Install AI")
    assert result.count("What's Changed") == 1
    assert "A PR" not in result
    assert "@someone" in result
    assert "**Full Changelog**" in result
    assert "Commit by author" in result
