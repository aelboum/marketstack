"""The Approval Inbox API (docs/ROADMAP.md Phase 29), mounted under
`/v1/approvals` in `product/api/main.py`.

**Ingress dependency choice** -- identical reasoning to every other
product router's own module docstring
(`docs/ADR/0002-agency-cross-tenant-route-authorization.md`'s Phase 4
addendum): every route uses `api.dependencies.get_current_actor`, never
`get_tenant_context()`/`require_permission()`. Every
`product/approvals/service.py` function performs its own
`core.rbac.can()` check via `product.approvals.permissions.require()`
before touching any approval request.

**Non-enumeration**: `ApprovalAccessDeniedError` (this module's own) and
`control_plane.approvals.ApprovalRequestNotFoundError` both map to the
identical `404` shape `api.errors.not_found()` uses elsewhere -- a caller
must not be able to distinguish "that approval doesn't exist" from "it
exists in another tenant" from "you can't see it."
`ApprovalNotPendingError` (approve/reject a non-pending request, or
execute a non-approved one) maps to `409` -- a real, expected conflict
(someone else already decided/executed it, or a double-click), not a
caller mistake worth hiding. `SelfApprovalNotAllowedError` maps to `403`
with an explicit message -- this is a documented, known product rule
(separation of duties), not a fact that would leak anything by being
named."""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found
from control_plane.approvals import ApprovalNotPendingError, SelfApprovalNotAllowedError
from fastapi import APIRouter, Depends, HTTPException, status

from product.approvals.errors import ApprovalAccessDeniedError
from product.approvals.service import (
    ApprovalView,
    approve_approval,
    execute_approval,
    get_approval_view,
    list_pending_approvals,
    reject_approval,
)

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (ApprovalAccessDeniedError,)


def _conflict(exc: ApprovalNotPendingError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"This approval is no longer pending (current status: {exc.status!r}). "
            "It may already have been decided or executed by someone else."
        ),
    )


def _self_approval_denied() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You proposed this action, so you cannot also approve or reject it.",
    )


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None
    except ApprovalNotPendingError as exc:
        raise _conflict(exc) from None
    except SelfApprovalNotAllowedError:
        raise _self_approval_denied() from None
    # `control_plane.approvals.ApprovalRequestNotFoundError` is a
    # `LookupError` subclass raised directly by `get_approval()`/
    # `list_approvals()` -- caught alongside this module's own
    # not-found error since both map to the identical non-enumerating
    # 404 (module docstring).
    except LookupError:
        raise not_found("resource") from None


async def _acall(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None
    except ApprovalNotPendingError as exc:
        raise _conflict(exc) from None
    except SelfApprovalNotAllowedError:
        raise _self_approval_denied() from None
    except LookupError:
        raise not_found("resource") from None


def _approval_dict(view: ApprovalView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "tool_key": view.tool_key,
        "action_label": view.action_label,
        "status": view.status,
        "status_label": view.status_label,
        "reason": view.reason,
        "proposer_user_id": str(view.proposer_user_id),
        "approver_user_id": str(view.approver_user_id) if view.approver_user_id else None,
        "created_at": view.created_at.isoformat(),
        "decided_at": view.decided_at.isoformat() if view.decided_at else None,
        "can_decide": view.can_decide,
        "can_execute": view.can_execute,
    }


@router.get("/tenants/{tenant_id}/approvals")
def list_approvals_route(
    tenant_id: uuid.UUID,
    status_filter: str | None = None,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _approval_dict(v)
        for v in _call(list_pending_approvals, actor_id, tenant_id, status=status_filter)
    ]


@router.get("/tenants/{tenant_id}/approvals/{approval_id}")
def get_approval_route(
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _approval_dict(_call(get_approval_view, actor_id, tenant_id, approval_id))


@router.post("/tenants/{tenant_id}/approvals/{approval_id}/approve")
def approve_approval_route(
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _approval_dict(_call(approve_approval, actor_id, tenant_id, approval_id))


@router.post("/tenants/{tenant_id}/approvals/{approval_id}/reject")
def reject_approval_route(
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _approval_dict(_call(reject_approval, actor_id, tenant_id, approval_id))


@router.post("/tenants/{tenant_id}/approvals/{approval_id}/execute")
async def execute_approval_route(
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _approval_dict(await _acall(execute_approval, actor_id, tenant_id, approval_id))


__all__ = ["router"]
