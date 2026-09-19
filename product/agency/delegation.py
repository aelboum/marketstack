"""Delegated administration and explicit deny (docs/ROADMAP.md Phase
3.3) -- thin wrappers over `core.rbac`'s existing, already-implemented,
already-tested `create_delegation()`/`revoke_delegation()`/
`create_deny()`/`revoke_deny()`. No new authorization mechanics live
here; every call below is self-authorizing via `core.rbac.can()`
internally, exactly like every function `product/agency/onboarding.py`
wraps.

The one thing this module adds: a delegator/grantor may only name a
`(resource, action)` pair that is already a real, registered `core.rbac`
permission -- never a caller-supplied pair this module would silently
register on their behalf (`docs/SECURITY-PRIVACY.md`'s "product-defined
permission *names*... the evaluator is not" rule, applied defensively
here: letting an HTTP caller conjure a brand-new permission by naming it
in a delegation request would be a mass-assignment-adjacent risk).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from core.rbac import (
    DelegationGrant,
    DenyGrant,
    RoleScope,
    create_delegation,
    create_deny,
    get_permission,
    revoke_delegation,
    revoke_deny,
)

from product.agency.errors import UnknownDelegatablePermissionError


def _resolve_permission_id(resource: str, action: str) -> uuid.UUID:
    permission = get_permission(resource, action)
    if permission is None:
        raise UnknownDelegatablePermissionError(resource, action)
    return permission.id


def create_client_delegation(
    *,
    delegator_user_id: uuid.UUID,
    delegate_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    resource: str,
    action: str,
    scope_mode: RoleScope = RoleScope.SELF,
    starts_at: datetime | None = None,
    expires_at: datetime | None = None,
    allow_redelegate: bool = False,
) -> DelegationGrant:
    permission_id = _resolve_permission_id(resource, action)
    return create_delegation(
        delegator_user_id=delegator_user_id,
        delegate_user_id=delegate_user_id,
        tenant_id=tenant_id,
        scope_mode=scope_mode,
        permission_id=permission_id,
        starts_at=starts_at,
        expires_at=expires_at,
        allow_redelegate=allow_redelegate,
    )


def revoke_client_delegation(
    *, revoker_user_id: uuid.UUID, tenant_id: uuid.UUID, delegation_grant_id: uuid.UUID
) -> DelegationGrant:
    return revoke_delegation(
        revoker_user_id=revoker_user_id,
        tenant_id=tenant_id,
        delegation_grant_id=delegation_grant_id,
    )


def create_client_deny(
    *,
    grantor_user_id: uuid.UUID,
    principal_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    resource: str,
    action: str,
    scope_mode: RoleScope = RoleScope.SELF,
) -> DenyGrant:
    permission_id = _resolve_permission_id(resource, action)
    return create_deny(
        grantor_user_id=grantor_user_id,
        principal_user_id=principal_user_id,
        tenant_id=tenant_id,
        scope_mode=scope_mode,
        permission_id=permission_id,
    )


def revoke_client_deny(
    *, revoker_user_id: uuid.UUID, tenant_id: uuid.UUID, deny_grant_id: uuid.UUID
) -> DenyGrant:
    return revoke_deny(
        revoker_user_id=revoker_user_id, tenant_id=tenant_id, deny_grant_id=deny_grant_id
    )
