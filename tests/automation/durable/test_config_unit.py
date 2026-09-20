"""Phase 10.3 durable-adapter configuration (docs/ADR/0007-automation-execution-substrate.md).
Pure unit tests, no network, no Temporal server, no database -- runs in
the default `pytest` invocation.
"""

from __future__ import annotations

import pytest
from product.automation.durable.config import (
    DEFAULT_NAMESPACE,
    DEFAULT_TASK_QUEUE,
    DurableConfigurationError,
    get_durable_config,
)


def test_missing_temporal_address_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Product remains usable if Temporal is not configured (this phase's
    own required spike outcome 7 / 14): the config loader fails clearly
    and explicitly, never silently defaults to a guessed endpoint."""
    monkeypatch.delenv("TEMPORAL_ADDRESS", raising=False)
    with pytest.raises(DurableConfigurationError):
        get_durable_config()


def test_configured_address_is_read_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal-test-host:7233")
    monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)
    monkeypatch.delenv("TEMPORAL_TASK_QUEUE", raising=False)

    config = get_durable_config()

    assert config.target_host == "temporal-test-host:7233"
    assert config.namespace == DEFAULT_NAMESPACE
    assert config.task_queue == DEFAULT_TASK_QUEUE


def test_namespace_and_task_queue_overrides_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal-test-host:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "spike-namespace")
    monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "spike-queue")

    config = get_durable_config()

    assert config.namespace == "spike-namespace"
    assert config.task_queue == "spike-queue"


def test_empty_temporal_address_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPORAL_ADDRESS", "")
    with pytest.raises(DurableConfigurationError):
        get_durable_config()
