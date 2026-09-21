"""`product/billing/purge.py`: the tenant-purge participant covering
`billing.resale_plans`, and its tenant-scoping -- purging tenant A must
never touch tenant B's rows (docs/ROADMAP.md Phase 13). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.billing import create_plan
from core.billing.provider import FakeBillingProvider
from infra.db import select, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.billing.models import ResalePlan
from product.billing.purge import BillingDataPurgeParticipant
from product.billing.resale_plans import ResalePlanView, create_resale_plan
from product.billing.subscriptions import create_platform_subscription

from tests.billing._cleanup import (
    cleanup_global_plan_keys,
    cleanup_tenant_tree,
    cleanup_users,
    make_user,
)

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _seed_resale_plan(owner_id, agency_tenant_id) -> tuple[str, ResalePlanView]:
    platform_key = _name("platform-plan")
    create_plan(platform_key, "Throwaway Platform Plan", entitlements={"max_users": 10})
    create_platform_subscription(
        owner_id, agency_tenant_id, platform_key, _name("idem"), provider=FakeBillingProvider()
    )
    plan = create_resale_plan(
        owner_id,
        agency_tenant_id,
        key=_name("tier"),
        name="Tier",
        price_amount=0,
        price_currency="USD",
        entitlements={"max_users": 1},
    )
    return platform_key, plan


def test_purge_deletes_only_the_target_tenants_resale_plans() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        platform_key_a, plan_a = _seed_resale_plan(owner_a.id, agency_a.tenant_id)
        platform_key_b, plan_b = _seed_resale_plan(owner_b.id, agency_b.tenant_id)

        BillingDataPurgeParticipant().purge_tenant_data(agency_a.tenant_id)

        with tenant_session_scope(agency_a.tenant_id) as session:
            assert session.get(ResalePlan, plan_a.id) is None
        with tenant_session_scope(agency_b.tenant_id) as session:
            assert session.get(ResalePlan, plan_b.id) is not None
    finally:
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)
        cleanup_global_plan_keys(
            platform_key_a, plan_a.underlying_plan_key, platform_key_b, plan_b.underlying_plan_key
        )


def test_purge_participant_is_idempotent() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        platform_key, plan = _seed_resale_plan(owner.id, agency.tenant_id)

        participant = BillingDataPurgeParticipant()
        participant.purge_tenant_data(agency.tenant_id)
        # A second run against an already-empty tenant must not raise.
        participant.purge_tenant_data(agency.tenant_id)

        with tenant_session_scope(agency.tenant_id) as session:
            leftover = (
                session.execute(select(ResalePlan).where(ResalePlan.tenant_id == agency.tenant_id))
                .scalars()
                .all()
            )
            assert leftover == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
        cleanup_global_plan_keys(platform_key, plan.underlying_plan_key)
