"""Bounded workflow/activity input (this phase's own required test 6).
Pure unit tests, no Temporal server, no network -- runs in the default
`pytest` invocation.
"""

from __future__ import annotations

import asyncio

import pytest
from product.automation.durable.activities import (
    ProbeActivityInput,
    ProbeActivityInputError,
    probe_activity,
)


def test_probe_activity_input_accepts_bounded_values() -> None:
    value = ProbeActivityInput(tenant_id="spike-tenant-1", resource_id="spike-resource-1")
    assert value.tenant_id == "spike-tenant-1"
    assert value.resource_id == "spike-resource-1"


def test_probe_activity_input_rejects_empty_tenant_id() -> None:
    with pytest.raises(ProbeActivityInputError):
        ProbeActivityInput(tenant_id="", resource_id="spike-resource-1")


def test_probe_activity_input_rejects_oversized_field() -> None:
    with pytest.raises(ProbeActivityInputError):
        ProbeActivityInput(tenant_id="x" * 256, resource_id="spike-resource-1")


def test_probe_activity_is_pure_no_io_given_bounded_input() -> None:
    """Calls the activity function directly (`asyncio.run(...)`, no
    Temporal worker/server/network involved at all) to confirm it
    performs no I/O and returns a bounded, deterministic echo --
    possible only because `probe_activity` makes no call into the SDK's
    own execution-context accessors (`activities.py`'s own docstring)."""
    value = ProbeActivityInput(tenant_id="spike-tenant-1", resource_id="spike-resource-1")

    result = asyncio.run(probe_activity(value))

    assert result.echoed_tenant_id == "spike-tenant-1"
    assert result.echoed_resource_id == "spike-resource-1"
