from __future__ import annotations

import time

import pytest

from lyrics.providers.tidal_auth import (
    TidalAccessContext,
    TidalAuthenticationError,
    TidalOAuthSession,
)


class _Store:
    def __init__(self, token=None):
        self.token = token
        self.saved = []

    def load(self, client_id):
        return self.token

    def save(self, client_id, token):
        self.token = token
        self.saved.append(token)

    def delete(self, client_id):
        self.token = None


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _HttpSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_tidal_session_uses_unexpired_access_token_without_network():
    store = _Store({"access_token": "access", "expires_at": time.time() + 3600})
    http = _HttpSession(_Response({"access_token": "unused", "expires_in": 3600}))
    session = TidalOAuthSession("client", "http://127.0.0.1:8765/callback", token_store=store, http_session=http)

    context = session.get_access_context()

    assert context == TidalAccessContext(access_token="access", expires_at=store.token["expires_at"])
    assert http.calls == []


def test_tidal_session_refreshes_expired_token_and_preserves_refresh_token():
    store = _Store({"access_token": "expired", "expires_at": time.time() - 1, "refresh_token": "refresh"})
    http = _HttpSession(_Response({"access_token": "fresh", "expires_in": 3600}))
    session = TidalOAuthSession("client", "http://127.0.0.1:8765/callback", token_store=store, http_session=http)

    context = session.get_access_context()

    assert context.access_token == "fresh"
    assert store.token["refresh_token"] == "refresh"
    assert http.calls[0][1]["data"]["grant_type"] == "refresh_token"


def test_tidal_session_requires_client_id_and_local_redirect_uri():
    session = TidalOAuthSession("", "https://example.test/callback", token_store=_Store())

    with pytest.raises(TidalAuthenticationError, match="client ID"):
        session.get_access_context()


def test_tidal_session_rejects_non_local_redirect_uri():
    session = TidalOAuthSession("client", "https://example.test/callback", token_store=_Store())

    with pytest.raises(TidalAuthenticationError, match="localhost"):
        session.connect()
