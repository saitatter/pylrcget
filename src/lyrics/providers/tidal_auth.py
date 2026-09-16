from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TidalAccessContext:
    """OAuth access data passed to TIDAL clients without exposing credentials to UI code."""

    access_token: str
    country_code: str | None = None
    expires_at: float | None = None


class TidalSessionProvider(Protocol):
    """Authentication/session boundary for official TIDAL API access."""

    def is_connected(self) -> bool:
        ...

    def connect(self) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def get_access_context(self) -> TidalAccessContext:
        ...
