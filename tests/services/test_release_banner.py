import subprocess
from unittest.mock import Mock

import pytest
from PIL import Image

from tools import release_banner as banner
from tools.release_notes import render_notes


def snapshot():
    return {
        "tag": "v1.16.0", "date": "13 Nov\n2026", "previous": "v1.15.0",
        "preview": True, "items": ["Automatic AI setup", "Synchronize selected tracks"],
        "commits": 12, "contributors": 1, "contributor_names": ["@contributor"],
        "issues_addressed": 4, "open_issues": 4, "stars": 18,
    }


def test_banner_renders_a_saved_snapshot_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(banner, "gh", Mock(side_effect=AssertionError("No network when rendering")))
    out = tmp_path / "preview.webp"
    banner.render(snapshot(), out)
    with Image.open(out) as image:
        assert image.size == (1671, 941)
        assert image.format == "WEBP"
        with Image.open(banner.ROOT / "src/ui/assets/app-icon.ico") as source:
            logo = source.ico.getimage((256, 256)).convert("RGBA").resize((100, 100), Image.Resampling.LANCZOS)
        # Compare interior brand colors; WebP introduces small compression error.
        for x, y in ((40, 40), (50, 50), (60, 60)):
            expected = logo.getpixel((x, y))[:3]
            actual = image.getpixel((104 + x, 15 + y))[:3]
            assert max(abs(a - b) for a, b in zip(actual, expected)) < 15


def test_date_line_breaks_and_long_logins_stay_inside_their_slots():
    _, date = banner.fit_text("13 Nov\n2026", banner.SLOTS["date"])
    assert date == "13 Nov\n2026"
    slot = banner.SLOTS["person_1"]
    face, login = banner.fit_text("@" + "verylongname" * 10, slot)
    assert face.getlength(login) <= slot.box[2] - slot.box[0]
    assert login.endswith("…")


def test_preview_cannot_publish(tmp_path, monkeypatch):
    api = Mock()
    monkeypatch.setattr(banner, "gh", api)
    with pytest.raises(ValueError, match="Preview"):
        banner.publish("owner/repo", "v1.16.0", tmp_path / "preview.webp", snapshot())
    api.assert_not_called()


def test_existing_banner_reuses_immutable_url_without_writes(tmp_path, monkeypatch):
    calls = []

    def api(method, endpoint, payload=None):
        calls.append(method)
        if "/git/ref/" in endpoint:
            return {"object": {"sha": "head"}}
        if "/git/trees/" in endpoint:
            return {"sha": "tree", "tree": [{"path": "v1.16.0.webp"}]}
        return [{"sha": "original-banner-commit"}]

    monkeypatch.setattr(banner, "gh", api)
    data = snapshot() | {"preview": False}
    result = banner.publish("owner/repo", "v1.16.0", tmp_path / "not-read.webp", data)
    assert result == "https://raw.githubusercontent.com/owner/repo/original-banner-commit/v1.16.0.webp"
    assert calls == ["GET", "GET", "GET"]


def test_first_banner_creates_an_orphan_commit_with_image_and_snapshot(tmp_path, monkeypatch):
    calls = []

    def api(method, endpoint, payload=None):
        calls.append((method, endpoint, payload))
        if method == "GET":
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 404: Not Found")
        if endpoint.endswith("/git/commits"):
            return {"sha": "new-banner-commit"}
        return {"sha": "new-object"}

    monkeypatch.setattr(banner, "gh", api)
    image = tmp_path / "banner.webp"
    image.write_bytes(b"image bytes")
    data = snapshot() | {"preview": False}
    result = banner.publish("owner/repo", "v1.16.0", image, data)
    commit = next(payload for _, endpoint, payload in calls if endpoint.endswith("/git/commits"))
    tree = next(payload for _, endpoint, payload in calls if endpoint.endswith("/git/trees"))
    assert commit["parents"] == []
    assert {entry["path"] for entry in tree["tree"]} == {"v1.16.0.webp", "v1.16.0.json"}
    assert result.endswith("/new-banner-commit/v1.16.0.webp")


def test_permission_failure_does_not_create_a_branch(tmp_path, monkeypatch):
    api = Mock(side_effect=subprocess.CalledProcessError(1, "gh", stderr="HTTP 403: Forbidden"))
    monkeypatch.setattr(banner, "gh", api)
    with pytest.raises(subprocess.CalledProcessError):
        banner.publish("owner/repo", "v1.16.0", tmp_path / "banner.webp", snapshot() | {"preview": False})
    assert api.call_count == 1


def test_release_notes_start_with_image_and_keep_accessible_text():
    notes = render_notes(["Automatic AI setup"], ["- Commit"], "", "https://example.com/banner.webp")
    assert notes.startswith("![PyLrcGet release highlights](https://example.com/banner.webp)")
    assert "Changes since last release:" in notes
    assert "Automatic AI setup" in notes
