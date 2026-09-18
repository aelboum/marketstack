"""Integration tests for product/white_label/branding.py against a real,
already-migrated PostgreSQL database (white_label.tenant_branding must
already exist -- see scripts/check-integration.sh). Marked `integration`,
excluded from the default `pytest` run.

The adversarial cross-agency test (docs/ROADMAP.md Phase 2.3's own
explicit checkpoint requirement) gets the most attention here -- it is
the one test this phase names as gating the ship decision.
"""

from __future__ import annotations

import uuid

import pytest
from core.tenancy import TenantNotFoundError, create_tenant
from infra.db import session_scope, tenant_session_scope
from product.white_label.branding import PLATFORM_DEFAULT_BRANDING_DISPLAY_NAME, DbBrandingProvider
from product.white_label.models import TenantBranding
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _delete_tenant_tree(*tenant_ids: uuid.UUID) -> None:
    for tid in tenant_ids:
        with tenant_session_scope(tid) as session:
            session.execute(
                text("DELETE FROM white_label.tenant_branding WHERE tenant_id = :t"),
                {"t": str(tid)},
            )
    with session_scope() as session:
        for tid in tenant_ids:
            session.execute(text("DELETE FROM core.tenants WHERE id = :id"), {"id": str(tid)})


def _set_branding(tenant_id: uuid.UUID, display_name: str) -> None:
    with tenant_session_scope(tenant_id) as session:
        session.add(TenantBranding(tenant_id=tenant_id, display_name=display_name))


def test_tenant_with_no_customization_anywhere_gets_platform_default() -> None:
    tenant = create_tenant(f"branding-none-{uuid.uuid4().hex[:8]}")
    try:
        branding = DbBrandingProvider().get_branding(tenant.id)
        assert branding.display_name == PLATFORM_DEFAULT_BRANDING_DISPLAY_NAME
        assert branding.source_tenant_id is None
    finally:
        _delete_tenant_tree(tenant.id)


def test_tenant_with_own_branding_uses_it() -> None:
    tenant = create_tenant(f"branding-own-{uuid.uuid4().hex[:8]}")
    try:
        _set_branding(tenant.id, "Own Brand")
        branding = DbBrandingProvider().get_branding(tenant.id)
        assert branding.display_name == "Own Brand"
        assert branding.source_tenant_id == tenant.id
    finally:
        _delete_tenant_tree(tenant.id)


def test_child_inherits_parent_branding_with_correct_source() -> None:
    agency = create_tenant(f"branding-agency-{uuid.uuid4().hex[:8]}")
    client = create_tenant(f"branding-client-{uuid.uuid4().hex[:8]}", parent_id=agency.id)
    try:
        _set_branding(agency.id, "Agency Brand")
        branding = DbBrandingProvider().get_branding(client.id)
        assert branding.display_name == "Agency Brand"
        # source_tenant_id records the AGENCY's id, not the client's own --
        # proves this is genuinely inherited, not a coincidental match.
        assert branding.source_tenant_id == agency.id
        assert branding.source_tenant_id != client.id
    finally:
        _delete_tenant_tree(client.id, agency.id)


def test_unknown_tenant_id_fails_closed_not_default() -> None:
    """docs/ROADMAP.md Phase 2.3: "fail-closed on an unrecognized/
    malformed tenant id; no default-tenant fallback" -- a nonexistent
    tenant_id must raise, never silently resolve to the platform
    default (which is reserved for a *valid* tenant with no
    customization)."""
    with pytest.raises(TenantNotFoundError):
        DbBrandingProvider().get_branding(uuid.uuid4())


def test_adversarial_unrelated_agency_branding_never_leaks() -> None:
    """docs/ROADMAP.md Phase 2.3's own named checkpoint test: two
    independent hierarchies -- Agency X (branded) -> Client A, and
    Agency Y (unbranded) -> Client B. Resolving Client B's branding
    must return the platform default, and must NEVER return Agency X's
    branding under any circumstance -- this is the exact bug class
    docs/WHITE-LABEL.md section 6 names: an off-by-one in the ancestor
    walk reaching an unrelated tenant."""
    agency_x = create_tenant(f"branding-agencyx-{uuid.uuid4().hex[:8]}")
    client_a = create_tenant(f"branding-clienta-{uuid.uuid4().hex[:8]}", parent_id=agency_x.id)
    agency_y = create_tenant(f"branding-agencyy-{uuid.uuid4().hex[:8]}")
    client_b = create_tenant(f"branding-clientb-{uuid.uuid4().hex[:8]}", parent_id=agency_y.id)
    try:
        _set_branding(agency_x.id, "Agency X Brand -- must never leak to Agency Y's tree")

        # Sanity: Agency X's own tree correctly sees Agency X's branding.
        assert DbBrandingProvider().get_branding(client_a.id).display_name == (
            "Agency X Brand -- must never leak to Agency Y's tree"
        )

        # The actual adversarial assertion: Agency Y's tree sees ONLY the
        # platform default, never Agency X's branding, at every level.
        for tenant_id in (agency_y.id, client_b.id):
            branding = DbBrandingProvider().get_branding(tenant_id)
            assert branding.display_name == PLATFORM_DEFAULT_BRANDING_DISPLAY_NAME
            assert branding.display_name != "Agency X Brand -- must never leak to Agency Y's tree"
            assert branding.source_tenant_id is None
    finally:
        _delete_tenant_tree(client_a.id, agency_x.id, client_b.id, agency_y.id)
