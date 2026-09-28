"""Product-owned exceptions for `product/accounting/` (docs/ROADMAP.md
Phase 24). Mirrors `product/reputation/errors.py`'s own discipline
exactly. `AccountingPeriodNotFoundError`/`AccountingPeriodClosedError`
are named exactly as `docs/ADR/0014-mini-accounting-foundation.md`
Decision 5 requires -- posting into a date with no `OPEN` period covering
it and posting into a `CLOSED` period are two distinct, distinguishable
failures, not one generic validation error.
"""

from __future__ import annotations

import uuid


class AccountingAccessDeniedError(Exception):
    """Raised by every `product/accounting/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/accounting/permissions.py
    ::require()`, the one authorization chokepoint every mutating and read
    function here calls first, before any database access."""

    def __init__(
        self, actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str
    ) -> None:
        self.actor_user_id = actor_user_id
        self.tenant_id = tenant_id
        self.resource = resource
        self.action = action
        super().__init__(
            f"{actor_user_id} is not authorized for {action!r} on {resource!r} "
            f"in tenant {tenant_id}."
        )


class AccountingReferenceNotFoundError(Exception):
    """Raised when a caller-supplied account/period/journal-entry id does
    not resolve to a real, in-tenant row. Mapped to the same
    non-enumerating "not found" shape as `AccountingAccessDeniedError` at
    any future API layer -- a caller must not be able to distinguish
    "that id doesn't exist" from "it exists in another tenant" from "you
    can't see it.\""""

    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class AccountingValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an unknown account type, an unbalanced journal entry, an empty line
    list, an attempt to edit/void a non-draft entry, an attempt to reverse
    a non-posted entry) -- a client input error, never an authorization or
    lookup failure."""


class AccountingConflictError(Exception):
    """Raised for a genuine state conflict this module's own logic
    detects (a duplicate account `code` for the same tenant) -- the
    service-layer translation of the real, database-enforced `UNIQUE`
    constraint violation, never a race-prone SELECT-then-INSERT check.
    Mirrors `product/reputation/errors.py::ReputationConflictError`."""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} {value!r} is already in use.")


class AccountingPeriodNotFoundError(Exception):
    """Raised by `post_journal_entry()`/`reverse_journal_entry()` when no
    period at all (`OPEN` or `CLOSED`) covers the entry's `entry_date` --
    `docs/ADR/0014-...` Decision 5: "no period is ever silently created,"
    a caller must explicitly `create_period()` first."""

    def __init__(self, tenant_id: uuid.UUID, entry_date: object) -> None:
        self.tenant_id = tenant_id
        self.entry_date = entry_date
        super().__init__(f"no accounting period covers {entry_date} in tenant {tenant_id}.")


class AccountingPeriodClosedError(Exception):
    """Raised by `post_journal_entry()`/`reverse_journal_entry()` when the
    period covering the entry's `entry_date` exists but is `CLOSED` --
    distinct from `AccountingPeriodNotFoundError` per Decision 5: closing
    a period does not retroactively invalidate anything already posted
    into it, it only rejects **new** posts and reversals targeting it."""

    def __init__(self, tenant_id: uuid.UUID, period_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        self.period_id = period_id
        super().__init__(f"accounting period {period_id} is closed in tenant {tenant_id}.")


__all__ = [
    "AccountingAccessDeniedError",
    "AccountingConflictError",
    "AccountingPeriodClosedError",
    "AccountingPeriodNotFoundError",
    "AccountingReferenceNotFoundError",
    "AccountingValidationError",
]
