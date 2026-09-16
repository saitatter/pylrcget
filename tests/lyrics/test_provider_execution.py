from __future__ import annotations

import pytest

from lyrics.providers import ProviderExecutionPolicy, get_provider_execution_policy


def test_provider_policies_are_conservative_and_lrclib_keeps_current_limit():
    assert get_provider_execution_policy("lrclib").max_concurrency == 4
    assert get_provider_execution_policy("tidal").max_concurrency == 2
    assert get_provider_execution_policy("external").max_concurrency == 1


def test_unknown_provider_defaults_to_single_worker():
    assert get_provider_execution_policy("future-provider").max_concurrency == 1


def test_provider_execution_policy_rejects_invalid_limits():
    with pytest.raises(ValueError):
        ProviderExecutionPolicy(max_concurrency=0)
    with pytest.raises(ValueError):
        ProviderExecutionPolicy(max_concurrency=1, min_request_interval=-1)
