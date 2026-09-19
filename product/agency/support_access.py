"""Support access workflow (docs/ROADMAP.md Phase 3.4) -- 1:1 thin
wrappers over `core.rbac`'s existing, already-implemented support-access
request/approve/deny/revoke primitives. No new logic: every function
below passes its arguments straight through to the corresponding
`core.rbac` function, which is itself the complete, already-audited,
already-time-boxed, already-self-authorizing implementation
(`docs/SECURITY-PRIVACY.md`: "No ad hoc 'impersonate tenant' backdoor is
ever built, regardless of how convenient it would be")."""

from __future__ import annotations

import uuid
from datetime import datetime

from core.rbac import (
    RoleScope,
    SupportAccessRequest,
    approve_support_access,
    create_support_access_request,
    deny_support_access,
    revoke_support_access,
)


def request_client_support_access(
    *,
    requester_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    reason: str,
    requested_expires_at: datetime,
    scope_mode: RoleScope = RoleScope.SELF,
    requested_starts_at: datetime | None = None,
) -> SupportAccessRequest:
    return create_support_access_request(
        requester_user_id=requester_user_id,
        tenant_id=tenant_id,
        reason=reason,
        requested_expires_at=requested_expires_at,
        scope_mode=scope_mode,
        requested_starts_at=requested_starts_at,
    )


def approve_client_support_access(
    *, approver_user_id: uuid.UUID, tenant_id: uuid.UUID, request_id: uuid.UUID
) -> SupportAccessRequest:
    return approve_support_access(
        approver_user_id=approver_user_id, tenant_id=tenant_id, request_id=request_id
    )


def deny_client_support_access(
    *, approver_user_id: uuid.UUID, tenant_id: uuid.UUID, request_id: uuid.UUID
) -> SupportAccessRequest:
    return deny_support_access(
        approver_user_id=approver_user_id, tenant_id=tenant_id, request_id=request_id
    )


def revoke_client_support_access(
    *, revoker_user_id: uuid.UUID, tenant_id: uuid.UUID, request_id: uuid.UUID
) -> SupportAccessRequest:
    return revoke_support_access(
        revoker_user_id=revoker_user_id, tenant_id=tenant_id, request_id=request_id
    )
