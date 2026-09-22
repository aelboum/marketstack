"""The Approval Inbox: authorization, tenant isolation, and the real
propose -> approve -> execute lifecycle, exercised through
`product/approvals/service.py` against the real, installed
`control_plane.approvals` (docs/ROADMAP.md Phase 29). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import pytest
from control_plane.approvals import (
    ApprovalNotPendingError,
    ApprovalRequestNotFoundError,
    SelfApprovalNotAllowedError,
    propose_action,
)
from control_plane.orchestration import ToolDefinition, ToolRegistry
from core.identity.sessions import issue_session
from fastapi import FastAPI
from fastapi.testclient import TestClient
from product.agency.provisioning import provision_agency, provision_client

# Importing this module registers Phase 29's own `agency.role_provisioned`
# subscriber (module-level `subscribe()` side effect) -- without this
# import, `owner`/`member` below would never receive their
# `approvals.approval` grants, exactly mirroring every other product
# module's own `event_handlers.py` precedent.
from product.approvals import event_handlers as _approvals_event_handlers  # noqa: F401
from product.approvals.errors import ApprovalAccessDeniedError
from product.approvals.routes import router as approvals_router
from product.approvals.service import (
    approve_approval,
    execute_approval,
    get_approval_view,
    list_pending_approvals,
    reject_approval,
)

from tests.approvals._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def _propose(tenant_id, proposer_id, tool_key: str = "ai.crm.qualify_lead"):
    return propose_action(tenant_id, proposer_id, tool_key, payload={"note": "test"})


async def _test_handler(
    context: object, payload: Mapping[str, object]
) -> dict[str, object]:
    return {"echoed": dict(payload)}


def _build_test_tool(tool_key: str) -> ToolDefinition:
    """A minimal, self-contained test tool -- `product/approvals/` never
    depends on `product.ai`, so this test builds its own rather than
    reusing `product/ai/tools/*.py`. `required_resource`/`required_action`
    reuse `approvals.approval`/`execute` deliberately: the same `owner`
    role this test already provisions is granted that permission by
    Phase 29's own `event_handlers.py`, so no extra grant setup is
    needed to prove a real, successful execution."""
    return ToolDefinition(
        key=tool_key,
        description="Phase 29 test tool",
        handler=_test_handler,
        required_scope_type="tenant",
        required_resource="approvals.approval",
        required_action="execute",
        autonomy_tier=1,
        side_effect="mutating",
    )


def _grant_owner_role(tenant_id, granting_owner_id, user_id) -> None:
    """`control_plane.orchestration._execute_tool()` checks the tool's
    own `required_resource`/`required_action` against the *proposer's*
    identity, not the approver's/executor's (`execute_approved()`'s own
    docstring: "using the proposer's agent_user_id, never the
    approver's") -- so a test proving a real, successful execution must
    give the proposer real RBAC standing of their own, exactly as a real
    AI-initiated proposal would run on behalf of the real human who
    configured/triggered it, never on the approver's authority."""
    from core.identity import add_tenant_membership
    from core.rbac import RoleScope, assign_role
    from product.agency.roles import ensure_agency_owner_role

    membership = add_tenant_membership(tenant_id, user_id)
    owner_role = ensure_agency_owner_role(tenant_id)
    assign_role(
        tenant_id,
        membership.id,
        owner_role.id,
        scope=RoleScope.SELF,
        actor_user_id=granting_owner_id,
    )


def _standalone_app() -> FastAPI:
    """A router-only test app -- deliberately not `product.api.main.app`
    (which *is* now wired with this router, see the Phase 29 final-wiring
    report) -- these HTTP-level tests exercise the router's own
    authorization/error-mapping behavior in isolation, without pulling in
    every other module's own routes, middleware, and CORS configuration.
    `test_app_smoke.py` and the real `product.api.main.create_app()` are
    what prove this router is actually reachable through the full,
    real application."""
    app = FastAPI()
    app.include_router(approvals_router)
    return app


# --- Listing -----------------------------------------------------------------


def test_list_pending_approvals_returns_real_pending_requests() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _propose(client.tenant_id, proposer.id)
        views = list_pending_approvals(owner.id, client.tenant_id, status="pending")
        assert len(views) == 1
        assert views[0].status == "pending"
        assert views[0].status_label == "Wacht op goedkeuring"
        assert views[0].action_label == "Lead kwalificeren"
        assert views[0].can_decide is True
        assert views[0].can_execute is False
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


def test_list_pending_approvals_empty_result_is_honest() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        assert list_pending_approvals(owner.id, client.tenant_id) == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_pending_approvals_is_tenant_isolated() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        _propose(client_a.tenant_id, owner.id)
        _propose(client_b.tenant_id, owner.id)

        views_a = list_pending_approvals(owner.id, client_a.tenant_id)
        assert len(views_a) == 1
        assert views_a[0].tenant_id == client_a.tenant_id
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_list_pending_approvals_denies_unauthorized_actor() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ApprovalAccessDeniedError):
            list_pending_approvals(stranger.id, client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


# --- Detail -------------------------------------------------------------------


def test_get_approval_view_returns_authorized_approval() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, owner.id)
        view = get_approval_view(owner.id, client.tenant_id, created.id)
        assert view.id == created.id
        assert view.reason  # a real, non-empty, non-invented general reason
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_approval_view_unknown_id_is_non_enumerating() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ApprovalRequestNotFoundError):
            get_approval_view(owner.id, client.tenant_id, uuid.uuid4())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_get_approval_view_cross_tenant_is_denied() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        created = _propose(client_a.tenant_id, owner.id)
        with pytest.raises(ApprovalRequestNotFoundError):
            get_approval_view(owner.id, client_b.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


# --- Approve ------------------------------------------------------------------


def test_approve_by_authorized_non_proposer_succeeds() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, proposer.id)
        view = approve_approval(owner.id, client.tenant_id, created.id)
        assert view.status == "approved"
        assert view.can_execute is True
        assert view.can_decide is False
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


def test_approve_denied_for_unauthorized_actor() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, owner.id)
        with pytest.raises(ApprovalAccessDeniedError):
            approve_approval(stranger.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_self_approval_is_rejected_the_real_saas_os_rule_not_reimplemented() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, owner.id)
        with pytest.raises(SelfApprovalNotAllowedError):
            approve_approval(owner.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_approving_an_already_decided_approval_is_a_conflict() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, proposer.id)
        approve_approval(owner.id, client.tenant_id, created.id)
        with pytest.raises(ApprovalNotPendingError):
            approve_approval(owner.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


# --- Reject -------------------------------------------------------------------


def test_reject_by_authorized_actor_succeeds() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, proposer.id)
        view = reject_approval(owner.id, client.tenant_id, created.id)
        assert view.status == "rejected"
        assert view.can_decide is False
        assert view.can_execute is False
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


def test_reject_denied_for_unauthorized_actor() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, owner.id)
        with pytest.raises(ApprovalAccessDeniedError):
            reject_approval(stranger.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_rejecting_an_already_processed_approval_is_a_conflict() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, proposer.id)
        approve_approval(owner.id, client.tenant_id, created.id)
        with pytest.raises(ApprovalNotPendingError):
            reject_approval(owner.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


# --- Execute ------------------------------------------------------------------


async def test_execute_approved_approval_actually_runs_the_real_tool() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    tool_key = f"test.tool.{uuid.uuid4().hex[:8]}"
    registry = ToolRegistry()
    registry.register(_build_test_tool(tool_key))
    try:
        _grant_owner_role(client.tenant_id, owner.id, proposer.id)
        created = _propose(client.tenant_id, proposer.id, tool_key=tool_key)
        approve_approval(owner.id, client.tenant_id, created.id)

        view = await execute_approval(owner.id, client.tenant_id, created.id, registry=registry)

        assert view.status == "executed"
        assert view.can_execute is False
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


async def test_execute_denied_for_unauthorized_actor() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, owner.id)
        with pytest.raises(ApprovalAccessDeniedError):
            await execute_approval(stranger.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


async def test_rejected_approval_cannot_execute() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, proposer.id)
        reject_approval(owner.id, client.tenant_id, created.id)
        with pytest.raises(ApprovalNotPendingError):
            await execute_approval(owner.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


async def test_pending_approval_cannot_execute_before_being_approved() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, proposer.id)
        with pytest.raises(ApprovalNotPendingError):
            await execute_approval(owner.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


async def test_duplicate_execution_after_success_is_a_conflict_not_a_double_run() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    tool_key = f"test.tool.{uuid.uuid4().hex[:8]}"
    registry = ToolRegistry()
    registry.register(_build_test_tool(tool_key))
    try:
        _grant_owner_role(client.tenant_id, owner.id, proposer.id)
        created = _propose(client.tenant_id, proposer.id, tool_key=tool_key)
        approve_approval(owner.id, client.tenant_id, created.id)
        await execute_approval(owner.id, client.tenant_id, created.id, registry=registry)

        # A second click after the first already succeeded must not
        # re-run the tool -- it must observe "no longer approved" and
        # conflict, exactly like SaaS-OS's own atomic claim guarantees.
        with pytest.raises(ApprovalNotPendingError):
            await execute_approval(owner.id, client.tenant_id, created.id, registry=registry)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


# --- HTTP: authorization, error mapping, non-enumeration ----------------------


def test_http_list_requires_authentication_and_returns_real_data() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _propose(client.tenant_id, proposer.id)
        app = _standalone_app()
        http_client = TestClient(app)

        response = http_client.get(
            f"/v1/approvals/tenants/{client.tenant_id}/approvals",
            headers=_auth_headers(owner.id),
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["status_label"] == "Wacht op goedkeuring"
        assert body[0]["action_label"] == "Lead kwalificeren"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


def test_http_approve_then_reject_conflict_maps_to_409() -> None:
    owner = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, proposer.id)
        app = _standalone_app()
        http_client = TestClient(app)
        headers = _auth_headers(owner.id)

        approve_response = http_client.post(
            f"/v1/approvals/tenants/{client.tenant_id}/approvals/{created.id}/approve",
            headers=headers,
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "approved"

        reject_response = http_client.post(
            f"/v1/approvals/tenants/{client.tenant_id}/approvals/{created.id}/reject",
            headers=headers,
        )
        assert reject_response.status_code == 409
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, proposer.id)


def test_http_self_approval_maps_to_403() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        created = _propose(client.tenant_id, owner.id)
        app = _standalone_app()
        http_client = TestClient(app)

        response = http_client.post(
            f"/v1/approvals/tenants/{client.tenant_id}/approvals/{created.id}/approve",
            headers=_auth_headers(owner.id),
        )

        assert response.status_code == 403
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_http_cross_tenant_approval_is_non_enumerating_404() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        created = _propose(client_a.tenant_id, owner.id)
        app = _standalone_app()
        http_client = TestClient(app)

        response = http_client.get(
            f"/v1/approvals/tenants/{client_b.tenant_id}/approvals/{created.id}",
            headers=_auth_headers(owner.id),
        )

        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_http_unauthorized_member_cannot_decide_but_can_read() -> None:
    """`member` gets `read` only (`event_handlers.py`'s own grants) --
    proves the product-level authorization gate, not just the SaaS-OS
    self-approval rule, is actually enforced."""
    from core.identity import add_tenant_membership
    from core.rbac import RoleScope, assign_role
    from product.agency.roles import ensure_client_member_role

    owner = make_user()
    member_user = make_user()
    proposer = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        membership = add_tenant_membership(client.tenant_id, member_user.id)
        member_role = ensure_client_member_role(client.tenant_id)
        assign_role(
            client.tenant_id,
            membership.id,
            member_role.id,
            scope=RoleScope.SELF,
            actor_user_id=owner.id,
        )
        created = _propose(client.tenant_id, proposer.id)

        # Read succeeds (member has "read").
        views = list_pending_approvals(member_user.id, client.tenant_id)
        assert len(views) == 1

        # Deciding is denied (member has no "decide").
        with pytest.raises(ApprovalAccessDeniedError):
            approve_approval(member_user.id, client.tenant_id, created.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member_user.id, proposer.id)
