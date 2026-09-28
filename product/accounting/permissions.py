"""Product-defined permissions for `product/accounting/` (docs/ROADMAP.md
Phase 24). Mirrors `product/reputation/permissions.py`'s own discipline
exactly -- every permission here is this product's own invention;
`accounting.*` tables have no SaaS-OS-provided authorization of any kind.

**Three resources**, one per aggregate root this phase introduces:
`ACCOUNT_RESOURCE`, `PERIOD_RESOURCE`, `JOURNAL_RESOURCE`
(`journal_lines` has no independent access boundary apart from the entry
it belongs to, the same "a child row is not its own resource"
consolidation `product/websites/permissions.py`'s own module docstring
already applies to `Page` under `Website`).

**Action names**: `PERIOD_RESOURCE`'s `manage` action (close/reopen) and
`JOURNAL_RESOURCE`'s `post`/`reverse` actions are named exactly as
`docs/ADR/0014-mini-accounting-foundation.md` Decision 5 names them
(`accounting.period.manage`, distinct from `accounting.journal.post`).
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.accounting.errors import AccountingAccessDeniedError

ACCOUNT_RESOURCE = "accounting.account"
PERIOD_RESOURCE = "accounting.period"
JOURNAL_RESOURCE = "accounting.journal"


def grant_to_role(
    tenant_id: uuid.UUID, role: Role, *, resource: str, actions: tuple[str, ...]
) -> None:
    """Grant `role` (already existing, in `tenant_id`) every named
    `action` for `resource` -- idempotent, mirrors
    `product/reputation/permissions.py::grant_to_role()`'s own
    check-then-grant discipline."""
    for action in actions:
        permission = register_permission(resource, action)
        if get_role_permission(tenant_id, role.id, permission.id) is None:
            grant_permission(tenant_id, role.id, permission.id)


def require(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str) -> None:
    """Raise `product.accounting.errors.AccountingAccessDeniedError`
    unless `actor_user_id` holds `(resource, action)` at `tenant_id` --
    the one authorization chokepoint every `product/accounting/*.py`
    service function calls first, before any database read or write."""
    if not can(actor_id=actor_user_id, tenant_id=tenant_id, action=action, resource=resource):
        raise AccountingAccessDeniedError(
            actor_user_id, tenant_id, resource=resource, action=action
        )


__all__ = ["ACCOUNT_RESOURCE", "JOURNAL_RESOURCE", "PERIOD_RESOURCE", "grant_to_role", "require"]
