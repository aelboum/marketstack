"""Proves `product/api/main.py::create_app()` -- the real application
composition root -- actually wires `product.accounting`'s purge
participant and event-handler module (docs/ROADMAP.md Phase 24 completion
remediation, 2026-09-28). Real disposable Postgres (purge-participant
registration itself needs none, but this package's own fixtures do).
Marked `integration`, excluded from the default `pytest` run.

Import-order note: this test package's own `tests/accounting/_cleanup.py`
already imports `product.accounting.event_handlers` for its own,
separately-documented reason, so a test in this same pytest process
cannot *exclusively* attribute the `owner`/`member` permission grant to
`create_app()`'s own import line. What this test proves instead --
still the meaningful claim `product/accounting/__init__.py`'s own
docstring makes -- is that `create_app()` itself contains and
successfully executes this wiring (no `ImportError`, no exception from
`register_accounting_purge_participant()`), and that the purge
participant it registers is reachable from the real, process-wide
default registry afterward, mirroring every other
`test_routes_integration.py::create_app()` call elsewhere in this suite.
"""

from __future__ import annotations

import pytest
from core.tenancy.purge_participants import default_registry
from product.accounting.purge import AccountingDataPurgeParticipant
from product.api.main import create_app

pytestmark = pytest.mark.integration


def test_create_app_registers_accounting_purge_participant() -> None:
    create_app()

    registry = default_registry()
    assert any(
        isinstance(participant, AccountingDataPurgeParticipant) for participant in registry.list()
    )


def test_create_app_is_idempotent_across_repeated_calls() -> None:
    """`register()`'s own re-registration tolerance
    (`DuplicateTenantPurgeParticipantError` caught, module docstring of
    `product/accounting/purge.py`) means a second `create_app()` call --
    e.g. a second test module in this same process also booting the app
    -- must never raise."""
    create_app()
    create_app()
