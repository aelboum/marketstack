"""Tenant purge participant for the `accounting` schema (ADR-0014 Decision
9, extended by Phase 25's own documents/payments per that Decision's own
addendum). **`purge_tenant_data()` is a documented no-op -- no
`accounting.*` row is ever deleted by tenant purge**, covering every table
in the schema unconditionally (Phase 24's `accounts`/`periods`/
`journal_entries`/`journal_lines` and Phase 25's `contact_profiles`/
`tax_codes`/`invoices`/`invoice_lines`/`bills`/`bill_lines`/`payments`/
`payment_allocations` alike) -- no code change was needed to extend this
participant to the new tables, since it never enumerates a table list in
the first place, mirroring
`core/tenancy/retention.py::RetentionClass.FINANCIAL_RETAIN`'s own
posture (already applied to `core.billing_subscriptions`). This is a
deliberate, conservative default, not an oversight: once any
`JournalEntry` is `posted`, deleting an `accounting.accounts`/
`accounting.periods` row it references is already impossible
(`ondelete=RESTRICT` on every posted-line-carrying FK,
`product/accounting/models.py`), so a partial purge would either violate
that constraint or require special-casing "delete only what was never
posted" -- deferred to a future compliance phase with a real legal-
retention policy to build it against, exactly as ADR-0014's own "Deferred
/ explicitly out of scope" section discloses.

`core.tenancy.purge_participants.TenantPurgeParticipant`'s own contract
does not ask a participant to declare *why* it does or doesn't delete
data (module docstring of that Protocol) -- retention posture is this
module's own documented policy, not a field Core inspects."""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)


class AccountingDataPurgeParticipant:
    """Registered so `core.tenancy.purge_tenant()` has a real, named
    participant to call for the `accounting` schema -- not because it
    deletes anything (module docstring)."""

    @property
    def name(self) -> str:
        return "accounting.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        return None


def register(registry: TenantPurgeParticipantRegistry | None = None) -> None:
    """See `product/crm/purge.py::register()`'s own docstring for the
    re-registration/idempotency reasoning."""
    active_registry = registry if registry is not None else default_registry()
    try:
        active_registry.register(AccountingDataPurgeParticipant())
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, AccountingDataPurgeParticipant) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise


__all__ = ["AccountingDataPurgeParticipant", "register"]
