"""Spike required tests 7-8: Product remains usable if Temporal is not
configured/started, and a worker connection failure is explicit and
non-silent. No Temporal server, no network download -- runs in the
default `pytest` invocation (connecting to a closed local port fails
fast, it does not need internet access).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from product.automation.durable.client import get_client
from product.automation.durable.config import DurableConfig
from temporalio.service import RPCError


def test_product_api_main_never_imports_a_temporal_worker_entrypoint() -> None:
    """Updated for Phase 10.3 production (documented, intentional change
    from the infrastructure spike's own identical-named test): ordinary
    API startup now legitimately imports `product.automation.durable
    .routes` (the production API surface) and `.triggers` (the
    event-triggered-run adapter's own module-level `subscribe()` side
    effect) -- neither one calls `get_durable_config()`/`get_client()` at
    import time, so this still does not require `TEMPORAL_ADDRESS` to be
    set merely to start the API (this phase's own required outcome
    "Product remains usable if Temporal is not configured/started" still
    holds -- verified by `test_app_smoke.py` itself passing with no
    `TEMPORAL_ADDRESS` set). What must remain true, and is what this test
    actually checks: `product/api/main.py` never imports a Temporal
    *worker* entrypoint (`product.automation.durable.worker` or
    `.production_worker`) -- those remain separate processes, never
    imported by the API (`production_worker.py`'s own module docstring)."""
    main_py = Path(__file__).resolve().parents[3] / "product" / "api" / "main.py"
    content = main_py.read_text(encoding="utf-8")

    assert "product.automation.durable.worker" not in content
    assert "product.automation.durable.production_worker" not in content
    assert "durable_worker" not in content  # no `import ... as _durable_worker`-style alias either


def test_existing_phase_10_2_automation_package_does_not_import_durable() -> None:
    """The existing single-step engine (`product/automation/dispatcher.py`,
    `product/automation/actions.py`, etc.) must remain wholly unmodified
    in *behavior* by this spike -- checked here at the import-graph level:
    none of Phase 10.2's own modules reaches into the new adapter."""
    import product.automation.actions
    import product.automation.dispatcher
    import product.automation.scheduled
    import product.automation.workflows

    for module in (
        product.automation.actions,
        product.automation.dispatcher,
        product.automation.scheduled,
        product.automation.workflows,
    ):
        assert not hasattr(module, "durable")


def test_worker_connection_failure_is_explicit_not_silent() -> None:
    """`Client.connect()` against an address nothing listens on must
    raise, not hang or silently return a dead client -- this is the
    "fails clearly" behavior `product/automation/durable/worker.py`'s
    own module docstring relies on instead of a hand-rolled retry
    framework."""
    config = DurableConfig(target_host="127.0.0.1:1")  # port 1: nothing listens here

    # Empirically, `Client.connect()` against a refused local port raises
    # a plain `RuntimeError` wrapping the underlying transport error (the
    # SDK's Rust-core bridge surfaces a connection failure this way, not
    # as `temporalio.service.RPCError` -- confirmed by actually running
    # this test, not assumed from the SDK's own public type surface).
    # `RPCError` is still asserted importable above, and remains the
    # right type to catch for an RPC that fails *after* a connection is
    # established (e.g. a bad namespace) -- a distinct failure mode from
    # this one.
    with pytest.raises((RPCError, OSError, ConnectionError, RuntimeError)):
        asyncio.run(get_client(config))
