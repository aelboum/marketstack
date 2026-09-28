"""Product-defined permissions for `product/accounting/` (docs/ROADMAP.md
Phase 24-25). Mirrors `product/reputation/permissions.py`'s own discipline
exactly -- every permission here is this product's own invention;
`accounting.*` tables have no SaaS-OS-provided authorization of any kind.

**Six resources**, one per aggregate root: Phase 24's `ACCOUNT_RESOURCE`/
`PERIOD_RESOURCE`/`JOURNAL_RESOURCE`, and Phase 25's `INVOICE_RESOURCE`/
`BILL_RESOURCE`/`PAYMENT_RESOURCE` (`journal_lines`/`invoice_lines`/
`bill_lines`/`payment_allocations`/`contact_profiles`/`tax_codes` have no
independent access boundary apart from their own parent/primary
aggregate -- the same "a child row is not its own resource" consolidation
`product/websites/permissions.py`'s own module docstring already applies
to `Page` under `Website`; `contact_profiles`/`tax_codes` are managed
under `INVOICE_RESOURCE`'s own `create`/`read` actions since tagging a
contact or defining a tax code is a prerequisite step of the same
invoicing workflow, not a separate resource).

**Action names**, per `docs/ADR/0014-mini-accounting-foundation.md`
Decision 5/13 exactly: `PERIOD_RESOURCE.manage` (close/reopen),
`JOURNAL_RESOURCE.post`/`.reverse`, `INVOICE_RESOURCE.post`/`.cancel`,
`BILL_RESOURCE.post` (Decision 13's own deliberate asymmetry: bill
approval/posting is owner-only, invoice posting is not),
`PAYMENT_RESOURCE.allocate`/`.reverse_allocation`.
"""

from __future__ import annotations

import uuid

from core.rbac import Role, can, get_role_permission, grant_permission, register_permission

from product.accounting.errors import AccountingAccessDeniedError

ACCOUNT_RESOURCE = "accounting.account"
PERIOD_RESOURCE = "accounting.period"
JOURNAL_RESOURCE = "accounting.journal"
INVOICE_RESOURCE = "accounting.invoice"
BILL_RESOURCE = "accounting.bill"
PAYMENT_RESOURCE = "accounting.payment"


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


__all__ = [
    "ACCOUNT_RESOURCE",
    "BILL_RESOURCE",
    "INVOICE_RESOURCE",
    "JOURNAL_RESOURCE",
    "PAYMENT_RESOURCE",
    "PERIOD_RESOURCE",
    "grant_to_role",
    "require",
]
