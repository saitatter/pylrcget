from __future__ import annotations

from lyrics.providers import TidalAccessContext, TidalSessionProvider


class _FakeTidalSession:
    def __init__(self):
        self.context = TidalAccessContext("access-token", country_code="RO")
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def get_access_context(self) -> TidalAccessContext:
        if not self.connected:
            raise RuntimeError("not connected")
        return self.context


def test_tidal_session_provider_isolated_from_catalogue_client():
    session: TidalSessionProvider = _FakeTidalSession()

    assert not session.is_connected()
    session.connect()
    access = session.get_access_context()
    session.disconnect()

    assert access.access_token == "access-token"
    assert access.country_code == "RO"
    assert not session.is_connected()
