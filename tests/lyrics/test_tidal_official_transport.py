from __future__ import annotations

from lyrics.providers.tidal_transport import OfficialTidalLyricsTransport


class _Response:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_official_transport_reads_json_api_lyrics_relationship():
    session = _Session(
        _Response(
            {
                "data": {"type": "tracks", "id": "42"},
                "included": [
                    {
                        "type": "lyrics",
                        "id": "lyrics-42",
                        "attributes": {
                            "lrcText": "[00:01.00]Hello",
                            "plainText": "Hello",
                        },
                    }
                ],
            }
        )
    )
    transport = OfficialTidalLyricsTransport("token", country_code="ro", session=session)

    result = transport.get_lyrics("42")

    assert result is not None
    assert result.synced_lyrics == "[00:01.00]Hello"
    assert result.plain_lyrics == "Hello"
    assert result.source == "official"
    assert session.calls[0][1]["params"] == {"include": "lyrics", "countryCode": "RO"}
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer token"


def test_official_transport_classifies_generic_lyrics_by_timestamp():
    session = _Session(_Response({"included": [{"type": "lyrics", "attributes": {"text": "[01:02.50]Line"}}]}))

    result = OfficialTidalLyricsTransport("token", session=session).get_lyrics("42")

    assert result is not None
    assert result.synced_lyrics == "[01:02.50]Line"
    assert result.plain_lyrics is None


def test_official_transport_treats_empty_public_relationship_as_clean_miss():
    session = _Session(_Response({"data": {"type": "tracks", "id": "42"}, "included": []}))

    assert OfficialTidalLyricsTransport("token", session=session).get_lyrics("42") is None
