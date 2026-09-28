"""Mini bookkeeping module (docs/ROADMAP.md Phase 24 -- "Mini Accounting
Foundation"; `docs/ADR/0014-mini-accounting-foundation.md`, currently
PROPOSED). **This phase implements exactly**: chart of accounts
(`product/accounting/accounts.py`), accounting periods with period
locking (`product/accounting/periods.py`), and journal entries with
double-entry immutability, posting, and reversal
(`product/accounting/journal.py`). It deliberately does **not**
implement customers/suppliers, invoices/bills, tax codes, or payments/
allocations -- those are Phase 25's own scope (ADR-0014's own "Phase 24 /
Phase 25 scope boundary" section). Never shares a table, model class, or
service module with `core.billing` (this platform's own SaaS subscription
billing) or `product.billing` (Phase 13's resale layer) -- see ADR-0014
Decision 1.

`product.accounting` depends on nothing beyond `product.foundation` and
installed SaaS-OS/core contracts this phase (`core.rbac`,
`core.idempotency`, `core.audit_log`, `core.tenancy`, `infra.db`) --
**not even `product.crm`** yet (`pyproject.toml`'s own "Accounting does
not depend on any product module (Phase 24)" contract): Decision 6's
CRM-contact-role-tag edge is Phase 25 scope, added only when that phase
actually needs it. No other product module may depend on
`product.accounting` (already enforced, pre-emptively, by every other
carved-out module's own `forbidden_modules` list).

**This module's purge participant (`product/accounting/purge.py
::register`) and event-handler module (`product/accounting
/event_handlers.py`, whose `agency.role_provisioned` subscription only
takes effect once imported) ARE wired into `product/api/main.py`**
(Phase 24 completion remediation, 2026-09-28) -- a purely additive
two-import-plus-one-call change (`from product.accounting import
event_handlers as _accounting_event_handlers  # noqa: F401`,
`from product.accounting.purge import register as
register_accounting_purge_participant`, and a
`register_accounting_purge_participant()` call alongside every other
module's own), which did not touch or conflict with `product/api
/main.py`'s own pre-existing, unrelated dev-auth-bypass hunk. No router
exists for this phase to wire -- Phase 24's own roadmap scope has no
user-visible result yet and needs no HTTP surface (matches
`product/appointments/models.py::CalendarEvent`'s own Phase 7.5
precedent: "no HTTP routes added this pass -- the domain/service layer
alone establishes the boundary").

As a result: `accounting.*` purge participation is now reachable through
the real running application (still a documented no-op per Decision 9,
`purge.py`'s own module docstring -- reachable, not newly destructive),
and the `owner`/`member` permission grants in `event_handlers.py` are now
automatically provisioned for every newly-created role, exactly like
every other fully-wired module.
"""
