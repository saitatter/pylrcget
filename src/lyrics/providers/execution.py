from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderExecutionPolicy:
    """Concurrency and pacing limits for one lyrics provider."""

    max_concurrency: int
    min_request_interval: float = 0.0

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("Provider concurrency must be at least one")
        if self.min_request_interval < 0:
            raise ValueError("Provider request interval cannot be negative")


_DEFAULT_POLICIES: dict[str, ProviderExecutionPolicy] = {
    "lrclib": ProviderExecutionPolicy(max_concurrency=4),
    "tidal": ProviderExecutionPolicy(max_concurrency=2, min_request_interval=0.1),
    "external": ProviderExecutionPolicy(max_concurrency=1),
}


def get_provider_execution_policy(provider_id: str) -> ProviderExecutionPolicy:
    """Return a conservative policy for known providers and unknown extensions."""

    normalized = str(provider_id or "").strip().casefold()
    return _DEFAULT_POLICIES.get(normalized, ProviderExecutionPolicy(max_concurrency=1))
