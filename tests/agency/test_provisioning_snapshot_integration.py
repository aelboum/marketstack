"""Integration tests for docs/ROADMAP.md Phase 21 -- Agency Provisioning
Loop: `product.agency.provisioning.provision_client()`'s optional
`snapshot_id`, which composes the existing Phase 3.1 client-provisioning
flow with the existing Phase 14 `apply_snapshot()` capability. Real,
disposable PostgreSQL. Marked `integration`, excluded from the default
`pytest` run.

Uses `tests.templates._cleanup` (not `tests.agency._cleanup` directly) --
these tests create real `crm.pipelines`/`crm.pipeline_stages` and
`templates.snapshots` rows in addition to the tenants/roles Phase 3.1's
own tests create, and `tests.templates._cleanup.cleanup_tenant_tree()`
already composes all three layers correctly (templates -> crm -> agency),
mirroring `tests/templates/test_snapshots_integration.py`'s own identical
choice.
"""

from __future__ import annotations

import uuid

import pytest
from core.tenancy import get_tenant
from product.agency.errors import AgencyAccessDeniedError, ClientProvisioningSetupFailedError
from product.agency.provisioning import (
    CLIENT_PROVISIONED_EVENT_TYPE,
    provision_agency,
    provision_client,
)
from product.crm.pipelines import create_pipeline, create_stage, list_pipelines
from product.foundation.events import subscribe
from product.templates.snapshots import create_snapshot

from tests.templates._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _seed_pipeline(owner_id, tenant_id, name: str = "Sales") -> None:
    pipeline = create_pipeline(owner_id, tenant_id, name=name, is_default=True)
    create_stage(owner_id, tenant_id, pipeline.id, name="Open", position=0)


def test_provision_client_with_snapshot_applies_setup_and_publishes_event() -> None:
    """docs/ROADMAP.md Phase 21's own acceptance criterion: provisioning
    a client with a chosen setup produces a real, queryable crm.pipelines
    row in the *new* tenant, and the new agency.client_provisioned event
    fires with the snapshot_id it applied."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    _seed_pipeline(owner.id, agency.tenant_id, name="Business Setup Sales")
    snapshot = create_snapshot(
        owner.id, agency.tenant_id, name="Standaard opzet", domains=["crm.pipelines"]
    )

    received = []
    subscribe(CLIENT_PROVISIONED_EVENT_TYPE, received.append)

    client = None
    try:
        client = provision_client(
            owner.id, agency.tenant_id, _name("client"), snapshot_id=snapshot.id
        )
        pipelines = list_pipelines(owner.id, client.tenant_id)
        assert any(p.name == "Business Setup Sales" for p in pipelines)

        matching = [e for e in received if e.tenant_id == str(client.tenant_id)]
        assert len(matching) == 1
        assert matching[0].payload == {
            "agency_tenant_id": str(agency.tenant_id),
            "snapshot_id": str(snapshot.id),
        }
    finally:
        ids = [agency.tenant_id] if client is None else [client.tenant_id, agency.tenant_id]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_provision_client_without_snapshot_is_unchanged() -> None:
    """Strictly additive: omitting snapshot_id reproduces Phase 3.1's own
    exact behavior -- no crm.pipelines row, event still fires with
    snapshot_id None."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))

    received = []
    subscribe(CLIENT_PROVISIONED_EVENT_TYPE, received.append)

    client = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        assert list_pipelines(owner.id, client.tenant_id) == []
        matching = [e for e in received if e.tenant_id == str(client.tenant_id)]
        assert len(matching) == 1
        assert matching[0].payload == {
            "agency_tenant_id": str(agency.tenant_id),
            "snapshot_id": None,
        }
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unknown_snapshot_id_leaves_client_usable_but_reports_setup_failed() -> None:
    """Partial-failure honesty: an unresolvable snapshot_id does not roll
    back the client tenant, does not publish
    CLIENT_PROVISIONED_EVENT_TYPE, and is reported as a distinct,
    catchable failure -- never silently swallowed, never a bare
    SnapshotNotFoundError with no way to know the tenant exists."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))

    received = []
    subscribe(CLIENT_PROVISIONED_EVENT_TYPE, received.append)

    created_tenant_id = None
    try:
        with pytest.raises(ClientProvisioningSetupFailedError) as excinfo:
            provision_client(
                owner.id, agency.tenant_id, _name("client"), snapshot_id=uuid.uuid4()
            )
        failure = excinfo.value
        created_tenant_id = failure.client.tenant_id
        assert failure.reason == "SnapshotNotFoundError"

        # The client tenant genuinely exists and is ACTIVE -- not rolled
        # back, not left in an ambiguous state.
        tenant = get_tenant(created_tenant_id)
        assert tenant.id == created_tenant_id

        # No "provisioned" event for a client whose chosen setup failed.
        assert not any(e.tenant_id == str(created_tenant_id) for e in received)
    finally:
        ids = (
            [agency.tenant_id]
            if created_tenant_id is None
            else [created_tenant_id, agency.tenant_id]
        )
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_agency_cannot_apply_another_agencys_snapshot() -> None:
    """Cross-agency isolation: a snapshot_id naming a real snapshot owned
    by a DIFFERENT agency cannot be applied -- source_tenant_id is always
    the provisioning agency's own tenant, so `apply_snapshot()`'s own
    ownership check (`SnapshotNotFoundError`, non-enumerating) rejects it
    exactly as it would for a direct cross-tenant `apply_snapshot()`
    call."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    _seed_pipeline(owner_b.id, agency_b.tenant_id)
    other_snapshot = create_snapshot(
        owner_b.id, agency_b.tenant_id, name="Agency B's own setup", domains=["crm.pipelines"]
    )

    created_tenant_id = None
    try:
        with pytest.raises(ClientProvisioningSetupFailedError) as excinfo:
            provision_client(
                owner_a.id,
                agency_a.tenant_id,
                _name("client"),
                snapshot_id=other_snapshot.id,
            )
        created_tenant_id = excinfo.value.client.tenant_id
        assert excinfo.value.reason == "SnapshotNotFoundError"
    finally:
        ids = [agency_a.tenant_id] if created_tenant_id is None else [
            created_tenant_id,
            agency_a.tenant_id,
        ]
        cleanup_tenant_tree(*ids)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_unrelated_actor_still_cannot_provision_with_a_snapshot() -> None:
    """The existing agency.client:create authorization check still runs
    first, unchanged -- passing a snapshot_id grants no new authority."""
    owner = make_user()
    attacker = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    _seed_pipeline(owner.id, agency.tenant_id)
    snapshot = create_snapshot(
        owner.id, agency.tenant_id, name="Owner-only setup", domains=["crm.pipelines"]
    )
    try:
        with pytest.raises(AgencyAccessDeniedError):
            provision_client(
                attacker.id, agency.tenant_id, _name("should-not-exist"), snapshot_id=snapshot.id
            )
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, attacker.id)
