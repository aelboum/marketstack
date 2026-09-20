"""Product-defined permissions for `product/telephony/` (docs/ROADMAP.md
Phase 8). Mirrors `product/appointments/permissions.py`'s own discipline
exactly -- every permission here is this product's own invention;
`telephony.*` tables have no SaaS-OS-provided authorization of any kind.

**`CALL_RECORDING_RESOURCE` is deliberately separate from
`CALL_RESOURCE`** -- Phase 8.3's own roadmap Security consideration:
"who can listen to a recording is an RBAC permission, not implicit from
general call-history access." A role with `telephony.call:read` does not
automatically get `telephony.call_recording:read`.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.telephony.errors import TelephonyAccessDeniedError

PHONE_NUMBER_RESOURCE = "telephony.phone_number"
CALL_RESOURCE = "telephony.call"
CALL_RECORDING_RESOURCE = "telephony.call_recording"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Grant `role` (already existing, in `tenant_id`) every named
    `action` for `resource` -- idempotent, mirrors
    `product/appointments/permissions.py::grant_to_role()`'s own
    check-then-grant discipline."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `product.telephony.errors.TelephonyAccessDeniedError` unless
    `actor_user_id` holds `(resource, action)` at `tenant_id` -- the one
    authorization chokepoint every `product/telephony/*.py` service
    function calls first, before any database read or write."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise TelephonyAccessDeniedError(actor_user_id, tenant_id, resource=resource, action=action)
