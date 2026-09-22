"""The Approval Inbox service layer (docs/ROADMAP.md Phase 29). Every
function below authorizes via `product.approvals.permissions.require()`
first, then delegates to the real `control_plane.approvals` function --
see `product/approvals/__init__.py`'s own module docstring for why this
is an adapter, never a second approval system.

`data_authorization_decision` is always passed as `None` to
`execute_approved()` below -- this surface implements only the approval
side of Phase 29's own diagram (propose -> approve -> execute), not a
Data Authorization decision UI. `control_plane.orchestration._execute_tool()`
already fails closed for any future tool declaring
`requires_data_authorization=True` when no decision is supplied (checked
directly: `if tool.requires_data_authorization and not
_data_authorization_satisfied(None, ...)`) -- so a tool that genuinely
needs one simply cannot be executed through this surface yet, safely,
rather than silently bypassing the check. Extending this to a real
Data Authorization prompt is explicitly out of this phase's scope.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from control_plane.approvals import (
    ApprovalRequest,
)
from control_plane.approvals import (
    approve as cp_approve,
)
from control_plane.approvals import (
    execute_approved as cp_execute_approved,
)
from control_plane.approvals import (
    get_approval as cp_get_approval,
)
from control_plane.approvals import (
    list_approvals as cp_list_approvals,
)
from control_plane.approvals import (
    reject as cp_reject,
)
from control_plane.orchestration import ToolRegistry

from product.approvals.labels import GENERIC_APPROVAL_REASON, action_label, status_label
from product.approvals.permissions import APPROVAL_RESOURCE, require

_DECIDABLE_STATUSES = frozenset({"pending"})
_EXECUTABLE_STATUSES = frozenset({"approved"})


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """The business-facing shape of one `ApprovalRequest` -- every raw
    field this phase's own UX spec asked to avoid leaking
    (`tool_key`, `status`) is still present (a technical/admin context,
    or a caller building its own presentation, may need the real value),
    but always alongside its translated `action_label`/`status_label`
    counterpart so a caller never *has* to touch the raw one."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    tool_key: str
    action_label: str
    status: str
    status_label: str
    reason: str
    proposer_user_id: uuid.UUID
    approver_user_id: uuid.UUID | None
    created_at: datetime
    decided_at: datetime | None
    can_decide: bool
    """Whether this specific approval is still in a state `approve()`/
    `reject()` will accept (`status == "pending"`) -- computed here so
    the frontend never has to hardcode that rule itself; it still means
    nothing about *authorization* to decide, only about *state*."""
    can_execute: bool
    """Whether this specific approval is in a state `execute_approved()`
    will accept (`status == "approved"`) -- same "state, not
    authorization" caveat as `can_decide`."""


def _to_view(row: ApprovalRequest) -> ApprovalView:
    return ApprovalView(
        id=row.id,
        tenant_id=row.tenant_id,
        tool_key=row.tool_key,
        action_label=action_label(row.tool_key),
        status=row.status,
        status_label=status_label(row.status),
        reason=GENERIC_APPROVAL_REASON,
        proposer_user_id=row.proposer_user_id,
        approver_user_id=row.approver_user_id,
        created_at=row.created_at,
        decided_at=row.decided_at,
        can_decide=row.status in _DECIDABLE_STATUSES,
        can_execute=row.status in _EXECUTABLE_STATUSES,
    )


def list_pending_approvals(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, status: str | None = None
) -> list[ApprovalView]:
    """Lists this tenant's own approval requests, optionally filtered to
    one `status`. Named "pending" in the plural for readability at call
    sites even though `status` can select any of the five real values --
    the Approval Inbox's own default view is the pending ones."""
    require(actor_user_id, tenant_id, resource=APPROVAL_RESOURCE, action="read")
    rows = cp_list_approvals(tenant_id, status=status)
    return [_to_view(row) for row in rows]


def get_approval_view(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, approval_id: uuid.UUID
) -> ApprovalView:
    require(actor_user_id, tenant_id, resource=APPROVAL_RESOURCE, action="read")
    return _to_view(cp_get_approval(tenant_id, approval_id))


def approve_approval(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, approval_id: uuid.UUID
) -> ApprovalView:
    """Authorizes, then delegates to the real
    `control_plane.approvals.approve()` -- which itself still separately
    enforces the self-approval rule (`SelfApprovalNotAllowedError`) and
    the pending-only rule (`ApprovalNotPendingError`) unconditionally,
    regardless of what this product-level check decides. This function
    adds an authorization gate; it never relaxes either of those two
    SaaS-OS-enforced invariants."""
    require(actor_user_id, tenant_id, resource=APPROVAL_RESOURCE, action="decide")
    return _to_view(cp_approve(tenant_id, approval_id, actor_user_id))


def reject_approval(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, approval_id: uuid.UUID
) -> ApprovalView:
    require(actor_user_id, tenant_id, resource=APPROVAL_RESOURCE, action="decide")
    return _to_view(cp_reject(tenant_id, approval_id, actor_user_id))


async def execute_approval(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    registry: ToolRegistry | None = None,
) -> ApprovalView:
    """Authorizes, then delegates to the real
    `control_plane.approvals.execute_approved()` -- the only function in
    this module (or in `control_plane.approvals`) that actually invokes
    the proposed tool, using the original *proposer's* identity, never
    this function's own `actor_user_id` (module docstring: "the approving
    human authorizes the agent's proposed action, they do not become the
    actor performing it" -- and by the same logic, neither does whoever
    merely clicks 'execute'). `registry` exists only for tests to inject
    an isolated `ToolRegistry` (mirrors `control_plane.approvals
    .execute_approved()`'s own parameter exactly) -- no HTTP caller can
    supply one (`product/approvals/routes.py` never accepts it), so a
    real request always resolves the real, installed
    `control_plane.orchestration.default_registry()`."""
    require(actor_user_id, tenant_id, resource=APPROVAL_RESOURCE, action="execute")
    row = await cp_execute_approved(
        tenant_id, approval_id, registry=registry, data_authorization_decision=None
    )
    return _to_view(row)


__all__ = [
    "ApprovalView",
    "approve_approval",
    "execute_approval",
    "get_approval_view",
    "list_pending_approvals",
    "reject_approval",
]
