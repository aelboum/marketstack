# ADR 0014: Mini Accounting foundation — scope, source of truth, and deferred localization

## Status

PROPOSED — not yet reviewed or formally approved. This document was
drafted as background research during the Phase 24 read-only readiness
audit (2026-09-27) and was never taken through this repository's ADR
approval workflow; it remains untracked in version control as of that
audit. It describes the *proposed* architecture for Phase 24 (accounting
foundation) and Phase 25 (revenue/document/money workflow) — see
"Phase 24 / Phase 25 scope boundary" immediately below — and is not yet
an accepted implementation decision. `docs/ROADMAP.md`'s own Phase 24
section requires this ADR to be formalized as a real, reviewed, committed
decision record before or alongside Phase 24's first implementation
commit; until that happens, treat every decision below as a starting
point for review, not as pre-approved scope.

## Phase 24 / Phase 25 scope boundary

Per the Phase 24 read-only audit (2026-09-27): this ADR was written as
one document covering the full accounting architecture, but
`docs/ROADMAP.md` splits that architecture across two separate phases.
Not every decision below is Phase 24 implementation scope.

- **Phase 24** (chart of accounts, periods, journal entries, double-entry
  immutability, period locking — this phase touches no contact, no tax
  code, no invoice/bill/payment row): Decision 1 (context), Decision 2,
  Decision 3, Decision 4, Decision 5, the journal/ledger portion of
  Decision 9, the journal-event portion of Decision 10, and the
  journal-posting/reversal portion of Decision 11.
- **Phase 25** (customers, invoices, suppliers, tax codes, payments/
  allocations): Decision 6, Decision 7, Decision 8, the document/payment
  portion of Decision 9's retention scope, the document/payment-event
  portion of Decision 10, and the invoice/bill/payment-idempotency
  portion of Decision 11.

Decisions 6–8 are not deleted or judged incorrect by this boundary — they
remain part of this ADR as the broader accounting architecture. They are
labeled below so an implementer cannot reasonably read all eleven
decisions as Phase 24 scope.

## Context

Phase 15 introduces `product/accounting/` — a deliberately small SMB
accounting foundation (chart of accounts, periods, journals, invoices,
bills, payments/allocations, reporting), not a Dutch/Moroccan-compliant
accounting suite and not a replacement for SaaS-OS's own
`core.billing` (product subscription billing). This ADR records the
decisions that make later Dutch/Moroccan localization and
bank/e-invoicing integrations possible without a rewrite, while keeping
this phase's own scope small.

Architecture invariant carried over unchanged from every prior phase:
`Products -> SaaS Core -> Infrastructure`. SaaS-OS is not modified.
`product.accounting` may depend on `product.crm` (one narrow edge, see
"CRM contact relationship" below) and on installed SaaS-OS/core
contracts (`core.rbac`, `core.idempotency`, `core.tenancy`,
`infra.db`); nothing may depend on `product.accounting`.

## Decision 1 (Phase 24 — context): product subscription billing vs. tenant's own accounting are unrelated systems

`product/billing/` (Phase 13, `docs/ADR/0012-...`) is this platform's
own commercial layer: what a *reseller tenant* charges its descendants,
mapped onto `core.billing_subscriptions`. `product/accounting/` is a
completely separate concern: the tenant's **own** double-entry books —
what it owes/is owed, tracked independently of whether or how it pays
for this SaaS product. Neither module imports the other; a
`docs/ROADMAP.md` Phase-13-style resale plan and an accounting
`Invoice` share no code, no table, and no schema. This ADR makes that
separation explicit because the vocabulary ("invoice", "plan", "payment")
overlaps in English even though the domains do not.

## Decision 2 (Phase 24): posted journal entries are the sole accounting source of truth

Every reporting query (trial balance, general ledger, account balance,
receivables/payables aging) reads only `accounting.journal_lines` joined
through `accounting.journal_entries` **where `status = 'posted'`**.
Mutable document status (`Invoice.status`, `Bill.status`) drives UI/API
behavior (can this document still be voided? is it fully paid?) but
never substitutes for the ledger in a report — an invoice sitting in
`draft` never appears in a receivables total; a `voided` journal entry's
lines never appear in a balance, because voiding a journal entry that
was never posted leaves no `posted` lines to include in the first place
(see Decision 3: a `draft` entry has no financial effect at all).
Receivables/payables reports read `Invoice.outstanding_amount`/
`Bill.outstanding_amount` (denormalized, updated transactionally by
`product/accounting/payments.py::create_allocation()`) rather than
re-deriving it from the ledger on every read — a deliberate,
documented shortcut: the invoice/bill row is still only ever created by
this module's own service layer under RLS, so this denormalization
never becomes an independent, divergent source of truth reachable from
outside this module.

## Decision 3 (Phase 24): immutable posted journals; correction is by reversal only

Lifecycle: `DRAFT -> POSTED`, `DRAFT -> VOIDED`, `POSTED -> REVERSED`.
A `DRAFT` journal entry has no financial effect (excluded from every
report by Decision 2) and may be edited or voided freely — voiding it is
not a correction, it is discarding something that was never posted.
Once `POSTED`, an entry's own rows (`JournalEntry`/`JournalLine`) are
never updated or deleted by any service function — no
`update_journal_entry()`/`delete_journal_line()` exists once status is
`posted`, mirroring `product/crm/pipelines.py`'s own "the roadmap states
no update/delete requirement" discipline, applied here as a hard
invariant rather than a convenience. Correcting a posted entry means
`reverse_journal_entry()`: creates a **new** `POSTED` entry whose lines
are the exact debit/credit mirror of the original (every debit becomes a
credit and vice versa, same accounts, same amounts), tagged
`reverses_entry_id -> original.id`, and flips the original's own status
to `REVERSED`. Both entries remain in the ledger forever — the
correction is visible, not hidden, matching double-entry bookkeeping
practice and this phase's own auditability requirement.

**Addendum (2026-09-28, Phase 24 completion remediation): reversal
`entry_date` policy.** This ADR does not specify which `entry_date` a
reversal itself is posted under — a genuine gap, not previously decided
here. Recorded now, under this document's own PROPOSED status (not a
new "Accepted" decision; subject to the same formal review as everything
else in this document): `reverse_journal_entry()` accepts an explicit,
caller-supplied `reversal_entry_date`; when omitted, it defaults to the
current date. This is the only choice that keeps every one of this
phase's other invariants intact without inventing new ones: reusing the
*original* entry's own `entry_date` would let a reversal attempt to post
into a period that has since been closed — silently reopening the exact
"closing a period rejects new posts" guarantee Decision 5 exists to
provide — whereas a caller-controlled (default: today) date lets the
reversal resolve its own, possibly different, `OPEN` period through the
identical `find_period_for_date()`/advisory-lock path `post_journal_entry()`
already uses, with no new locking, immutability, or auditability
mechanism. Deterministic per call: the same explicit `reversal_entry_date`
always resolves to the same period; the default (today) is the one
caller-visible non-determinism already inherent to "today," identical to
every other module in this codebase that defaults a timestamp to "now."
Not a credit-note mechanism — no document/invoice semantics are
introduced by this addendum.

## Decision 4 (Phase 24): monetary representation — `NUMERIC`, unsigned dual-column debit/credit

`product/crm/models.py::Opportunity` already has a money-shaped column
(`amount_minor_units` `Integer` + `amount_currency`) — that convention
is deliberately **not** reused here. An opportunity's amount is a single
estimate; a ledger's core invariant is `sum(debits) == sum(credits)`
across arbitrarily many rows, which is far more naturally expressed and
constrained with SQL `NUMERIC` (Python `Decimal` on the way out —
`infra.db.Numeric`'s own `asdecimal=True` default) than with integer
minor units, and every monetary column here (`journal_lines.debit_amount`/
`credit_amount`, invoice/bill/payment amounts) is `Numeric(18, 2)`.
Scale `2` assumes a 2-decimal-minor-unit currency (EUR, MAD, USD, ...);
a 0-decimal (JPY) or 3-decimal (e.g. some historical dinars) currency is
explicitly **not** supported yet — `docs/ROADMAP.md`'s own scope
exclusion list already defers a real multi-currency/FX engine, and this
is the natural continuation of that boundary, not a new one. Never a
floating-point type anywhere in this schema.

**Debit/credit representation**: two unsigned, non-negative columns per
line (`debit_amount NUMERIC(18,2) DEFAULT 0`, `credit_amount NUMERIC(18,2)
DEFAULT 0`), constrained by
`ck_accounting_journal_lines_exactly_one_side`: exactly one of the two is
strictly positive, the other is exactly zero — never both zero (an empty
line), never both positive (a line that is somehow its own debit and
credit), never negative (the classic "a negative debit is secretly a
credit" foot-gun this representation makes structurally impossible,
rather than merely discouraged). A signed single-`amount` column was
considered and rejected: it pushes the "which sign means debit" decision
into every single reader (report queries, reversal logic, display code)
instead of the schema itself.

Entry-level balance (`sum(debits) == sum(credits)` across a whole
`JournalEntry`'s lines) is **not** a single-row `CHECK` — Postgres has no
cross-row `CHECK` — and is instead enforced by
`product/accounting/journal.py::post_journal_entry()`, inside the same
transaction as the status flip to `POSTED`, before any commit. This is
the one accounting invariant that is service-layer-only; every other
structural invariant in this ADR has a database constraint as well
(defense in depth), documented per-table in `product/accounting/models.py`.

## Decision 5 (Phase 24): period locking, and no implicit period creation

`accounting.periods` rows are tenant-owned, non-overlapping (Postgres
`EXCLUDE USING gist` over `daterange(start_date, end_date, '[]')` per
tenant, the same `btree_gist`-backed pattern
`product/appointments/models.py`'s own double-booking constraint already
established in this codebase — `btree_gist` is already installed,
confirmed by `scripts/check-migrations.sh`), with `status`
`OPEN`/`CLOSED`. Posting (`post_journal_entry()`) requires an existing
`OPEN` period whose date range contains the entry's `entry_date`;
**no period is ever silently created** by a posting call — if none
exists, posting fails with `AccountingPeriodNotFoundError`, a caller
must explicitly `create_period()` first. Closing/reopening a period is
its own permission (`accounting.period.manage`, distinct from
`accounting.journal.post`) — closing a period does not retroactively
invalidate anything already posted into it; it only rejects **new**
posts (`AccountingPeriodClosedError`) and reversals targeting it.
Concurrency: `post_journal_entry()` and `close_period()`/`reopen_period()`
both take `infra.db.acquire_tenant_advisory_lock(session, tenant_id,
f"accounting.period.{period_id}")` before reading the period's status —
the same transaction-scoped advisory-lock pattern
`core.usage.service.consume_quota()` already uses for its own
check-and-act race — so a period cannot be closed mid-post and a post
cannot land after a close call has started evaluating it.

## Decision 6 (Phase 25): CRM contact relationship — role tag, not a second identity table

`crm.contacts` remains the **only** person/organization identity table a
tenant maintains; `product/accounting/` never creates a duplicate
customer/supplier record. `accounting.contact_profiles` adds exactly one
thing CRM does not have: a `role` tag (`customer` / `supplier` / `both`)
scoped to one `(tenant_id, contact_id)`, created via
`product/accounting/contacts.py::tag_contact_role()` before that
contact can appear on an invoice (`customer`/`both` required) or a bill
(`supplier`/`both` required). `product.accounting` reads/writes
`crm.contacts` only through `product.crm.contacts`'s own published
functions (`get_contact()`) — the identical "reuse the aggregate's own
service layer, never touch its tables directly" rule
`product/templates/snapshots.py` already established for
`product.crm.pipelines`. Dependency direction: `product.accounting` may
depend on `product.crm`; `product.crm` never depends on
`product.accounting` (enforced by two `import-linter` contracts,
mirroring `product/templates/__init__.py`'s own pair exactly). No
marketing-specific CRM function (audience segmentation, campaign
tracking) is used or needed.

## Decision 7 (Phase 25): VAT/tax-code foundation — generic, no hardcoded country rates

`accounting.tax_codes` is a tenant-owned catalog (`code`, `name`,
`rate_percent NUMERIC(6,3)`, `tax_type` — `'sales'` or `'purchase'`,
generic enough to mean output VAT/TVA or input VAT/TVA in any
jurisdiction — `tax_account_id`, `is_active`, optional
`effective_from`/`effective_to`). No Dutch (21%/9%) or Moroccan
(20%/14%/10%/7%) rate is seeded anywhere in this module's migration or
code — a tenant (or a later localization "tax pack" seeding script,
deliberately not built here) creates its own codes. `tax_account_id` is
a required composite FK into the tenant's own `accounting.accounts` —
the GL account a tax code's collected/paid amounts post to when an
invoice/bill line using it is posted — so tax amounts are real ledger
entries, not a side-channel total. This is the one place this phase
makes a firm decision a future localization layer must respect: a tax
code always resolves to exactly one posting account; per-jurisdiction
multi-account VAT schemes (e.g. reverse-charge splitting) are deferred,
not precluded — a later phase can add columns, not redesign the table.

## Decision 8 (Phase 25): payments/allocations are a foundation, not yet part of the ledger

A `Payment` (direction `inbound`/`outbound`, amount, currency, contact,
reference) and its `PaymentAllocation`s (against an `invoice` or a
`bill`, by `document_type` + `document_id` — deliberately **not** a hard
per-type foreign key: a payment allocates against exactly one of two
different tables, and this codebase's own composite-tenant-FK pattern
only expresses "one specific table" per constraint; enforcing "table A
or table B, in this tenant" would need either two nullable FK columns
with an exactly-one-set `CHECK` or an application-level check — this
phase chooses the latter, validated by
`product/accounting/payments.py::create_allocation()` re-reading the
target row through the same tenant's `tenant_session_scope()` before
allocating, which makes a cross-tenant target simply not exist rather
than merely unauthorized) reduce `Invoice.outstanding_amount`/
`Bill.outstanding_amount` and `Payment.unallocated_amount`, all three
updated in the same transaction under
`acquire_tenant_advisory_lock(session, tenant_id, f"accounting.document.{document_id}")`
to make concurrent allocation races safe (mirrors Decision 5's period
lock exactly). **This phase deliberately does not generate a journal
entry for the cash/bank leg of a payment** — doing so would require
designating a tenant's own bank/cash GL account, a decision this phase
defers (no bank integration exists yet, `docs/ROADMAP.md`'s own scope
exclusions already rule out bank sync/reconciliation this phase). A
payment today is a receivables/payables-tracking fact, not yet a
ledger-posting one; `journal_lines.source_document_type`/
`source_document_id` (nullable, soft reference, unenforced by FK for the
same polymorphism reason as above) lets a caller manually link a
hand-created journal entry to a payment if it wants the cash movement in
the ledger before this gap is closed in a later phase.

## Decision 9 (Phase 24 for accounts/periods/journals; extended at Phase 25 for documents/payments): retention — accounting data is financial evidence, not casually purged

`core/tenancy/retention.py::RetentionClass.FINANCIAL_RETAIN` already
classifies `core.billing_subscriptions` this way; this module's own
purge participant (`product/accounting/purge.py`) applies the identical
posture to the **entire** `accounting` schema: **`purge_tenant_data()`
is a documented no-op — no accounting row is ever deleted by tenant
purge.** This is a deliberate, conservative default, not an oversight:
once any `JournalEntry` is `POSTED`, deleting `accounting.accounts`/
`accounting.periods` rows referenced by it is already impossible
(`ondelete="RESTRICT"` on every posted-line-carrying FK — see
"Prevent deletion of accounts referenced by posted journal entries" in
the phase brief), so a partial purge would either violate that
constraint or require special-casing "delete only what was never
posted," which this phase declines to build without a real legal-
retention policy to build it against. **Explicit boundary** (this
ADR's own required disclosure): a future compliance phase must decide
(a) how long financial records must be retained after a tenant closes,
(b) whether/how they are eventually anonymized or hard-deleted once that
window passes, and (c) whether draft-only, never-posted accounting
configuration (an unused chart of accounts, a tax code no invoice ever
referenced) should purge normally even before that policy exists. This
phase does not pretend (c) is solved either — it is left undone
alongside (a)/(b) rather than half-solved in a way that would need
unwinding later.

## Decision 10 (journal events: Phase 24; invoice/bill/payment events: Phase 25): events — plain in-process, not durable

Every other product module's own domain events
(`templates.snapshot.created`, `reputation.review.responded`, ...) use
`product/foundation/events.py`'s plain `subscribe()`/`publish()` —
synchronous, in-process, no current cross-process consumer. The durable
variant (`subscribe_durable()`/`publish_durable()`, backed by
`infra.jobs`) exists for a fundamentally different need (delivery must
survive a process restart/run in a different worker), which
`product/automation/durable/triggers.py` uses for its own reason. No
accounting event has that requirement yet — the only current consumer of
`agency.role_provisioned` (permission grants) and of accounting's own
events (`accounting.journal.posted`, `accounting.journal.reversed`,
`accounting.invoice.created`, `accounting.invoice.posted`,
`accounting.bill.created`, `accounting.payment.created`,
`accounting.payment.allocated`, `accounting.period.closed`) is,
today, nothing outside this module's own tests — so this phase follows
every other module's own precedent rather than reaching for the durable
path speculatively. `accounting.invoice.voided`/`accounting.bill.voided`
were considered and dropped: voiding a `draft` document has no
downstream consequence worth an event (Decision 2 — it never touched the
ledger), so publishing one would be exactly the "speculative event
noise" the phase brief warns against.

## Decision 11 (journal posting/reversal: Phase 24; invoice/bill/payment creation: Phase 25): idempotency — the existing fully-atomic primitive, no new mechanism

`post_journal_entry()`, `reverse_journal_entry()`,
`create_invoice()`/`post_invoice()`, `create_bill()`/`post_bill()`,
`create_payment()`, and `create_allocation()` each accept an optional
`idempotency_key` and, when supplied, run their entire mutation through
`core.idempotency.run_idempotent()` — the fully atomic, single-
transaction primitive (`core.usage.service.consume_quota_idempotent()`
is the model to follow exactly: the business function receives the
*same* session the reservation was inserted through, never opens a
second `tenant_session_scope()`). No two-step
`begin_idempotent_operation()`/`finalize_idempotent_operation()` path is
needed anywhere in this module — every one of these operations is a
pure database mutation with no external call in the middle. `Idempotency-
Key` is read at the API layer exactly like every other endpoint that
supports it, via `api.dependencies.get_idempotency_key()` — no second
header-reading mechanism.

## Deferred / explicitly out of scope

Bank aggregation, PSD2/Open Banking, automatic bank reconciliation, full
Dutch VAT filing, Moroccan TVA filing, annual accounts/bilan generation,
payroll, fixed assets, inventory accounting, depreciation, a
multi-currency FX engine, OCR/document AI, Peppol/e-invoicing,
payment-provider integration, a full accounting UI, an accountant
portal, and an AI accounting agent are all explicitly out of scope for
this phase (`docs/ROADMAP.md` Phase 15's own exclusion list) and nothing
in this data model requires a rewrite to add any of them later: a bank
account is just another `accounting.accounts` row of a new
`account_type`; a payment gaining a real ledger posting
(Decision 8) only needs that designation, not a schema change; a tax
pack is seed data against the existing `accounting.tax_codes` shape
(Decision 7); e-invoicing/OCR are producers that would call
`create_invoice()`/`create_bill()` exactly like a human-driven API
client does today.
