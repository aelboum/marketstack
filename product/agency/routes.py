"""The agency/client management API (docs/ROADMAP.md Phase 3), mounted
under `/v1/agency` in `product/api/main.py`, per `docs/API-ARCHITECTURE.md`'s
versioning convention.

**Ingress dependency choice -- read `docs/ADR/0002-agency-cross-tenant-
route-authorization.md` before changing this.** Every route below uses
`api.dependencies.get_current_actor` (authentication only: resolves the
session to a `user_id`, no tenant-membership check) rather than
`api.dependencies.get_tenant_context`/`require_permission()`. This is
deliberate, not an oversight: `get_tenant_context()` requires a direct
`core.identity.TenantMembership` row at the exact target tenant, which an
agency owner reaching a client only via a `SUBTREE`-scoped role does not
have. Every service-layer function these routes call
(`core.rbac.can()`-gated internally, or gated via this product's own
`AgencyAccessDeniedError` check) performs its own real authorization --
this is a different, equally-enforced ingress dependency, not a bypass.

**Non-enumeration**: every authorization/lookup failure from the service
layer maps to the identical `404` shape `api.errors.not_found()` already
uses elsewhere in this platform (`_call()` below) -- never a `403`, never
a message that would let a caller distinguish "this tenant doesn't exist"
from "it exists but you can't touch it." `InvitationInvalidError` (raised
by `accept_invitation_route` only) is deliberately NOT in that bucket --
see that route's own comment: it isn't an authorization decision (the
actor isn't being denied access to something real), it's a credential
that didn't redeem, so it gets its own, distinct `400` -- which changes
nothing about non-enumeration, since `core.identity.accept_invitation()`
itself already collapses wrong-tenant/unknown/expired/revoked/already-
accepted into that identical exception before this router ever sees it
(`product/agency/onboarding.py`'s own docstring).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from api.dependencies import get_current_actor
from api.errors import not_found
from core.identity import InvitationInvalidError, InvitationNotAuthorizedError
from core.rbac import (
    DelegationNotAuthorizedError,
    DelegationNotFoundError,
    DenyNotAuthorizedError,
    DenyNotFoundError,
    RoleAssignmentNotAuthorizedError,
    RoleScope,
    SupportAccessAlreadyDecidedError,
    SupportAccessNotAuthorizedError,
    SupportAccessNotFoundError,
    SupportAccessSelfApprovalError,
)
from core.tenancy import TenantClosedError, TenantInaccessibleError, TenantNotFoundError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from product.agency.delegation import (
    create_client_delegation,
    create_client_deny,
    revoke_client_delegation,
    revoke_client_deny,
)
from product.agency.errors import AgencyAccessDeniedError, UnknownDelegatablePermissionError
from product.agency.onboarding import accept_client_invitation, invite_client_member
from product.agency.provisioning import list_clients as _list_clients
from product.agency.provisioning import provision_agency, provision_client
from product.agency.support_access import (
    approve_client_support_access,
    deny_client_support_access,
    request_client_support_access,
    revoke_client_support_access,
)

router = APIRouter(prefix="/v1/agency", tags=["agency"])

# Every exception a service-layer call in this module can raise that
# means "this actor may not see/do this" or "this thing doesn't exist" --
# mapped to the identical non-enumerating 404, in one place, per the
# module docstring. `UnknownDelegatablePermissionError` is deliberately
# NOT in this tuple -- it means "you named a permission that does not
# exist at all," a client input error, not an access-control question
# (the permission catalog itself is not secret), so it keeps its own,
# distinct 400 below.
_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    AgencyAccessDeniedError,
    TenantNotFoundError,
    TenantClosedError,
    TenantInaccessibleError,
    InvitationNotAuthorizedError,
    RoleAssignmentNotAuthorizedError,
    DelegationNotAuthorizedError,
    DelegationNotFoundError,
    DenyNotAuthorizedError,
    DenyNotFoundError,
    SupportAccessNotAuthorizedError,
    SupportAccessNotFoundError,
    SupportAccessAlreadyDecidedError,
    SupportAccessSelfApprovalError,
)


def _call(fn, *args, **kwargs):
    """Invoke a service-layer function, mapping every known
    authorization/lookup failure to the shared non-enumerating 404, and
    every `UnknownDelegatablePermissionError` to a plain 400. Used by
    every route handler below instead of a per-route try/except, so the
    mapping lives in exactly one place."""
    try:
        return fn(*args, **kwargs)
    except UnknownDelegatablePermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown permission: resource={exc.resource!r} action={exc.action!r}.",
        ) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


# --- Request/response bodies -------------------------------------------


class CreateAgencyRequest(BaseModel):
    name: str


class CreateClientRequest(BaseModel):
    name: str


class InviteMemberRequest(BaseModel):
    invited_email: str


class AcceptInvitationRequest(BaseModel):
    raw_token: str


class CreateDelegationRequest(BaseModel):
    delegate_user_id: uuid.UUID
    resource: str
    action: str
    scope_mode: RoleScope = RoleScope.SELF
    expires_at: datetime | None = None
    allow_redelegate: bool = False


class CreateDenyRequest(BaseModel):
    principal_user_id: uuid.UUID
    resource: str
    action: str
    scope_mode: RoleScope = RoleScope.SELF


class RequestSupportAccessRequest(BaseModel):
    reason: str
    requested_expires_at: datetime
    scope_mode: RoleScope = RoleScope.SELF


# --- Routes ---------------------------------------------------------------


@router.post("/agencies", status_code=status.HTTP_201_CREATED)
def create_agency(
    body: CreateAgencyRequest, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    agency = _call(provision_agency, actor_id, body.name)
    return {"tenant_id": str(agency.tenant_id), "name": agency.name}


@router.post("/agencies/{agency_tenant_id}/clients", status_code=status.HTTP_201_CREATED)
def create_client(
    agency_tenant_id: uuid.UUID,
    body: CreateClientRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    client = _call(provision_client, actor_id, agency_tenant_id, body.name)
    return {
        "tenant_id": str(client.tenant_id),
        "name": client.name,
        "agency_tenant_id": str(agency_tenant_id),
    }


@router.get("/agencies/{agency_tenant_id}/clients")
def list_agency_clients(
    agency_tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    clients = _call(_list_clients, actor_id, agency_tenant_id)
    return [{"tenant_id": str(c.tenant_id), "name": c.name} for c in clients]


@router.post("/tenants/{tenant_id}/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation_route(
    tenant_id: uuid.UUID,
    body: InviteMemberRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    sent = _call(invite_client_member, actor_id, tenant_id, body.invited_email)
    return {"invitation_id": str(sent.invitation_id), "raw_token": sent.raw_token}


@router.post("/tenants/{tenant_id}/invitations/accept")
def accept_invitation_route(
    tenant_id: uuid.UUID,
    body: AcceptInvitationRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    """`get_current_actor`, not `get_tenant_context`, for a third reason
    beyond `docs/ADR/0002-...`'s existing two: the accepting user has no
    membership at `tenant_id` yet -- by definition, since accepting the
    invitation is what creates that membership -- so `get_tenant_context()`
    would 404 an otherwise-legitimate caller before they could ever
    complete the one action that would satisfy it. Not a cross-tenant
    case (ADR-0002's original two reasons); an unauthenticated-with-
    respect-to-this-tenant case instead.

    `InvitationInvalidError` is handled here directly, not via `_call()`'s
    shared 404 mapping -- see the module docstring's Non-enumeration
    note."""
    try:
        membership = accept_client_invitation(body.raw_token, actor_id, tenant_id)
    except InvitationInvalidError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invitation is invalid, expired, revoked, already accepted, "
                "or does not belong to this tenant."
            ),
        ) from None
    return {"tenant_id": str(membership.tenant_id), "membership_id": str(membership.id)}


@router.post("/tenants/{tenant_id}/delegations", status_code=status.HTTP_201_CREATED)
def create_delegation_route(
    tenant_id: uuid.UUID,
    body: CreateDelegationRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    grant = _call(
        create_client_delegation,
        delegator_user_id=actor_id,
        delegate_user_id=body.delegate_user_id,
        tenant_id=tenant_id,
        resource=body.resource,
        action=body.action,
        scope_mode=body.scope_mode,
        expires_at=body.expires_at,
        allow_redelegate=body.allow_redelegate,
    )
    return {"delegation_id": str(grant.id)}


@router.delete(
    "/tenants/{tenant_id}/delegations/{delegation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_delegation_route(
    tenant_id: uuid.UUID, delegation_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(
        revoke_client_delegation,
        revoker_user_id=actor_id,
        tenant_id=tenant_id,
        delegation_grant_id=delegation_id,
    )


@router.post("/tenants/{tenant_id}/denies", status_code=status.HTTP_201_CREATED)
def create_deny_route(
    tenant_id: uuid.UUID,
    body: CreateDenyRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    grant = _call(
        create_client_deny,
        grantor_user_id=actor_id,
        principal_user_id=body.principal_user_id,
        tenant_id=tenant_id,
        resource=body.resource,
        action=body.action,
        scope_mode=body.scope_mode,
    )
    return {"deny_id": str(grant.id)}


@router.delete("/tenants/{tenant_id}/denies/{deny_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_deny_route(
    tenant_id: uuid.UUID, deny_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(revoke_client_deny, revoker_user_id=actor_id, tenant_id=tenant_id, deny_grant_id=deny_id)


@router.post("/tenants/{tenant_id}/support-access-requests", status_code=status.HTTP_201_CREATED)
def request_support_access_route(
    tenant_id: uuid.UUID,
    body: RequestSupportAccessRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    request = _call(
        request_client_support_access,
        requester_user_id=actor_id,
        tenant_id=tenant_id,
        reason=body.reason,
        requested_expires_at=body.requested_expires_at,
        scope_mode=body.scope_mode,
    )
    return {"request_id": str(request.id)}


@router.post("/tenants/{tenant_id}/support-access-requests/{request_id}/approve")
def approve_support_access_route(
    tenant_id: uuid.UUID, request_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    request = _call(
        approve_client_support_access,
        approver_user_id=actor_id,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    # approve_support_access() always sets approved_at -- the field is
    # Optional on the model (a not-yet-decided request has none), not
    # because this specific return path could ever see it unset.
    assert request.approved_at is not None
    return {"request_id": str(request.id), "approved_at": request.approved_at.isoformat()}


@router.post("/tenants/{tenant_id}/support-access-requests/{request_id}/deny")
def deny_support_access_route(
    tenant_id: uuid.UUID, request_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    request = _call(
        deny_client_support_access,
        approver_user_id=actor_id,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    assert request.denied_at is not None
    return {"request_id": str(request.id), "denied_at": request.denied_at.isoformat()}


@router.post("/tenants/{tenant_id}/support-access-requests/{request_id}/revoke")
def revoke_support_access_route(
    tenant_id: uuid.UUID, request_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    request = _call(
        revoke_client_support_access,
        revoker_user_id=actor_id,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    assert request.revoked_at is not None
    return {"request_id": str(request.id), "revoked_at": request.revoked_at.isoformat()}
