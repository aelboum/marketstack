"""Integration tests for product/agency/support_access.py. Marked
`integration`, excluded from the default `pytest` run.

docs/ROADMAP.md Phase 3.4's own acceptance criterion: "full propose ->
approve -> time-boxed access -> automatic/manual revoke cycle works,
fully audited." Auditing itself is core.rbac's own, already-tested
responsibility (every function this module wraps calls
core.audit_log.record() internally) -- this file proves the product-side
wrapper composes the cycle correctly, not core.audit_log's own behavior.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core.rbac import can
from product.agency.provisioning import provision_agency
from product.agency.support_access import (
    approve_client_support_access,
    deny_client_support_access,
    request_client_support_access,
    revoke_client_support_access,
)

from tests.agency._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_full_request_approve_revoke_cycle() -> None:
    owner = make_user()
    engineer = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        now = datetime.now(UTC)
        request = request_client_support_access(
            requester_user_id=engineer.id,
            tenant_id=agency.tenant_id,
            reason="Phase 3 integration test",
            requested_starts_at=now,
            requested_expires_at=now + timedelta(hours=1),
        )
        # Requesting grants nothing by itself.
        assert not can(
            actor_id=engineer.id,
            tenant_id=agency.tenant_id,
            action="create",
            resource="agency.client",
        )

        approve_client_support_access(
            approver_user_id=owner.id, tenant_id=agency.tenant_id, request_id=request.id
        )
        assert can(
            actor_id=engineer.id,
            tenant_id=agency.tenant_id,
            action="create",
            resource="agency.client",
        )

        revoke_client_support_access(
            revoker_user_id=owner.id, tenant_id=agency.tenant_id, request_id=request.id
        )
        assert not can(
            actor_id=engineer.id,
            tenant_id=agency.tenant_id,
            action="create",
            resource="agency.client",
        )
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, engineer.id)


def test_denied_request_grants_nothing() -> None:
    owner = make_user()
    engineer = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    try:
        now = datetime.now(UTC)
        request = request_client_support_access(
            requester_user_id=engineer.id,
            tenant_id=agency.tenant_id,
            reason="Phase 3 integration test",
            requested_starts_at=now,
            requested_expires_at=now + timedelta(hours=1),
        )
        deny_client_support_access(
            approver_user_id=owner.id, tenant_id=agency.tenant_id, request_id=request.id
        )
        assert not can(
            actor_id=engineer.id,
            tenant_id=agency.tenant_id,
            action="create",
            resource="agency.client",
        )
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(owner.id, engineer.id)
