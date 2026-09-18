# Mini Accounting / Bookkeeping — Scope and Boundaries

Status: PROPOSED. This document exists specifically to prevent the scope
creep the brief warns against: "the roadmap must explicitly decide the
minimum viable accounting scope rather than allowing accounting to grow
uncontrollably."

## The One Mistake to Avoid

`core.billing` (SaaS-OS, already implemented) models **this platform's own
SaaS revenue** — an agency paying for its subscription to use this product.
Its `Plan`/`Subscription`/`Invoice`/`Payment` concepts are about the
relationship between this product and its tenants.

The accounting module models **a tenant's own bookkeeping** — an agency's
(or its client's) own customers, its own sales invoices, its own expenses,
its own bank account. This is a completely different business relationship
with completely different data, that happens to reuse similar-sounding
words ("invoice," "payment").

**These must never share a table, a model class, or a service module.**
`accounting.invoices` (a tenant's own customer invoice) and `core.billing
.Subscription`'s invoicing (this platform charging the tenant) are unrelated
concepts that happen to both involve money. Confusing them is the single
most likely design mistake in this area, named here explicitly so no phase
in `docs/ROADMAP.md` accidentally does it.

## In Scope (Mini Bookkeeping)

### Core bookkeeping
- Chart of accounts (a sensible small default set, tenant-customizable)
- Journal entries, debit/credit, double-entry
- Accounting periods (open/closed)
- General ledger, account balances
- Transaction history

### Sales
- Customers (the tenant's own customers — a separate concept from CRM
  contacts, though a customer record may reference a CRM contact/company for
  convenience; accounting's customer record is the one this module owns and
  is authoritative for invoicing)
- Invoices, invoice lines, invoice numbering (sequential, gapless per legal
  requirement — see Dutch considerations below), VAT/tax fields, invoice
  status, payments against invoices, outstanding balances
- Credit notes, if the numbering/audit-trail requirement below is met

### Purchases
- Suppliers, purchase invoices/expenses, expense categories, payments

### Banking
- Bank accounts (metadata only initially — not live aggregation)
- Imported bank transactions (manual CSV/MT940 import at launch — see "Bank
  Integration Phasing" below)
- Transaction matching against invoices/expenses
- Reconciliation workflow

### Reports
- Profit & loss
- Balance sheet
- VAT/tax summary
- General ledger export
- Accounts receivable / accounts payable aging
- Cash overview

## Explicitly Out of Scope (Initial and Foreseeable Phases)

Named explicitly, per the brief's requirement, so no phase quietly grows into
these:

- **Payroll.** Not a bookkeeping concern in the sense scoped here; a
  materially different regulatory domain (wage tax, social security
  contributions) requiring its own specialized system.
- **Full ERP** (procurement workflows, multi-warehouse, manufacturing,
  project costing beyond simple expense categorization).
- **Inventory / warehouse management.**
- **Complex multi-entity consolidation** (parent/subsidiary consolidated
  financial statements). The agency/client hierarchy (`docs/ARCHITECTURE.md`
  §3) is an *authorization* hierarchy, not an accounting consolidation
  hierarchy — each tenant's books remain its own, independent set, never
  automatically rolled up into a combined statement.
- **Advanced financial planning** (budgeting, forecasting, scenario
  modeling).
- **Full tax advisory** (this module calculates and reports what the data
  says; it does not give tax advice, and its output is not a substitute for
  a qualified accountant's review — see the disclaimer requirement below).
- **Complex international accounting** (multi-jurisdiction consolidated tax
  reporting, transfer pricing). Initial scope is the Netherlands; a second
  jurisdiction is a deliberate future phase, not an assumed extension.
- **Advanced fixed-asset management** (depreciation schedules beyond a
  simple straight-line default, asset disposal accounting, revaluation).

If a future need genuinely requires one of these, it is scoped as its own
explicit roadmap phase with its own review — never absorbed silently into an
existing accounting phase.

## Dutch Market Considerations (Architecture-Relevant, Not a Compliance Claim)

**No claim of legal/tax compliance is made anywhere in this document.**
Everything below is flagged so the *architecture* accommodates these
requirements when a qualified accountant/legal reviewer specifies the exact
rules — not as a substitute for that review.

- **VAT (BTW)**: multiple rates (standard, reduced, exempt/reverse-charge)
  must be a first-class field on invoice lines and chart-of-accounts
  mapping, not bolted on later. The VAT summary report's exact box structure
  (matching the Dutch tax authority's own return categories) needs
  accountant sign-off before Phase 15's report-generation subphase is
  considered complete.
- **Invoice numbering**: Dutch requirements expect sequential, gapless
  invoice numbers per legal entity/tenant. The data model must make a
  numbering gap structurally difficult (e.g. numbers assigned at commit
  time from a per-tenant sequence, never pre-allocated and potentially
  discarded) — this is a Phase 15 acceptance-criteria item, not a report
  formatting detail.
- **Credit notes**: must reference the original invoice and preserve the
  original invoice's own immutability (a credit note corrects, it never
  edits, an already-issued invoice).
- **Accounting periods**: Dutch fiscal-year conventions (typically calendar
  year, but not always) — the period model must not hardcode a calendar-year
  assumption.
- **Audit trail**: every posted journal entry, once posted, is immutable —
  correction is by reversing entry, never by editing history. This is a
  stronger guarantee than `core.audit_log` provides by itself (that logs
  *actions*; this is about the *ledger data itself* being append-only) and
  is this product's own data-model discipline to build, following the same
  pattern `core.audit_log` already demonstrates rather than inventing a new
  one.
- **Retention**: Dutch bookkeeping retention is commonly cited as seven
  years — the exact requirement (and any exceptions) needs accountant
  confirmation, but the architecture must support configurable,
  long-horizon retention independent of `core.tenancy`'s own tenant-data
  retention/purge policy (a tenant's accounting records may need to outlive
  the tenant's own SaaS subscription under some circumstances — this is a
  genuine tension with `core.tenancy.purge_tenant()`'s participant model
  that Phase 15 must resolve explicitly, not by default deletion).
- **Future VAT reporting integration**: architecture should not preclude a
  later direct-to-tax-authority submission integration (Category D, not
  built at launch).
- **Future bank integration**: a PSD2 Account Information Service provider
  covering Dutch banks (see "Bank Integration Phasing" below).
- **GDPR/privacy**: accounting data contains PII (customer names, addresses)
  and is financial data — both are already-anticipated sensitive-data
  classes in `saas-os` `docs/SECURITY.md` §9 ("platform account data,"
  "financial information" is explicitly named in §6.1 rule 6 as a class
  never sent to an external AI provider without explicit policy). Retention
  requirements here may conflict with a tenant's own GDPR erasure request —
  this is a real, unresolved tension (financial retention law vs. erasure
  right) that needs the same accountant/legal review flagged above, not an
  architectural guess.
- **Exportability**: every report and the underlying ledger must be
  exportable (CSV/PDF at minimum) — a tenant's own accountant needs to be
  able to work with this data outside the platform; this is an acceptance
  criterion for Phase 15, not an afterthought.

## Bank Integration Phasing

1. **Launch**: manual bank statement import (CSV, and MT940 if a target
   bank commonly exports it), matched semi-automatically against open
   invoices/expenses by amount/reference/date proximity, with a manual
   confirm step. No live aggregation.
2. **Later, explicit phase**: a PSD2 AIS (Account Information Service)
   provider integration for live transaction pull — Category D, provider
   abstraction from day one of that phase (never assume one aggregator),
   mirroring `core.billing`'s own Stripe-adapter pattern.

## Reuse From SaaS-OS (Category A — Consume, Don't Rebuild)

- `core.crypto` for field-level encryption of sensitive financial data
  (bank account numbers, if stored; tax identifiers).
- `core.idempotency` for payment-webhook processing (a payment provider or
  bank-import job retried must never double-post a journal entry).
- `core.audit_log` for the action-level audit trail (who changed what,
  when) — additive to, never a replacement for, the ledger's own
  posted-entry immutability discipline above.
- `infra.db` tenant-scoping — accounting tables are ordinary tenant-owned
  tables, isolated exactly like every other module's.

## Acceptance Criteria for "Mini" Staying Mini

Each Phase 15 subphase (`docs/ROADMAP.md`) must be checked against this
document's Out-of-Scope list before merge. Any request to add a capability
from that list is a scope-change decision requiring your explicit sign-off,
not a judgment call made mid-implementation.
