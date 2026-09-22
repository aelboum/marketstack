"""`product/templates/purge.py`: the tenant-purge participant covering
`templates.snapshots`, and its tenant-scoping -- purging tenant A must
never touch tenant B's rows (docs/ROADMAP.md Phase 14). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from infra.db import select, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.crm.pipelines import create_pipeline
from product.templates.models import Snapshot
from product.templates.purge import TemplatesDataPurgeParticipant
from product.templates.snapshots import create_snapshot

from tests.templates._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def test_purge_deletes_only_the_target_tenants_snapshots() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        create_pipeline(owner_a.id, client_a.tenant_id, name="A")
        create_pipeline(owner_b.id, client_b.tenant_id, name="B")
        snapshot_a = create_snapshot(
            owner_a.id, client_a.tenant_id, name="A Snapshot", domains=["crm.pipelines"]
        )
        snapshot_b = create_snapshot(
            owner_b.id, client_b.tenant_id, name="B Snapshot", domains=["crm.pipelines"]
        )

        TemplatesDataPurgeParticipant().purge_tenant_data(client_a.tenant_id)

        with tenant_session_scope(client_a.tenant_id) as session:
            assert session.get(Snapshot, snapshot_a.id) is None
        with tenant_session_scope(client_b.tenant_id) as session:
            assert session.get(Snapshot, snapshot_b.id) is not None
    finally:
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_purge_participant_is_idempotent() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_pipeline(owner.id, client.tenant_id, name="Once")
        create_snapshot(owner.id, client.tenant_id, name="Once", domains=["crm.pipelines"])

        participant = TemplatesDataPurgeParticipant()
        participant.purge_tenant_data(client.tenant_id)
        # A second run against an already-empty tenant must not raise.
        participant.purge_tenant_data(client.tenant_id)

        with tenant_session_scope(client.tenant_id) as session:
            leftover = (
                session.execute(select(Snapshot).where(Snapshot.tenant_id == client.tenant_id))
                .scalars()
                .all()
            )
            assert leftover == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
