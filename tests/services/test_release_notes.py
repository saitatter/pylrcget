from tools.release_notes import changelog_summary, commit_rows, render_notes


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


def test_commit_rows_keep_each_commit_and_link_authors_and_issue_references():
    history = (
        "123456789\x00User\x00123+user@users.noreply.github.com\x00Add batch sync\x00Fixes #62. Related to #41 and #62.\x1e\n"
        "987654321\x00Contributor\x00user@example.com\x00Fix setup\x00\x1e\n"
    )
    rows = commit_rows(history, "saitatter/pylrcget")
    assert len(rows) == 2
    assert "[@user](https://github.com/user)" in rows[0]
    assert rows[0].count("issues/62") == 1
    assert "issues/41" in rows[0]
    assert "Fix setup by Contributor" in rows[1]
