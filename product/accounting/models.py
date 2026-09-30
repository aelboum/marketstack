"""ORM models for the `accounting` schema. Phase 24 (docs/ROADMAP.md --
"Mini Accounting Foundation") established `Account`/`Period`/
`JournalEntry`/`JournalLine` below; Phase 25 ("Revenue & Money Workflow")
adds `ContactProfile`/`TaxCode`/`Invoice`/`InvoiceLine`/`Bill`/
`BillLine`/`Payment`/`PaymentAllocation` further down, per
`docs/ADR/0014-mini-accounting-foundation.md` Decisions 6-8 and 12
(still PROPOSED -- see that document's own Status section); Phase 15.3
("Credit notes") adds `CreditNote`/`CreditNoteLine` below, once Phase 25's
invoice/payment foundation existed to reference -- the original Phase 15
numbering (`docs/ROADMAP.md`'s own "Credit notes (original 15.3)... remain
separately sequenced, deferred" note on Phase 25) is the authoritative
phase identifier for this addition, since Phase 25 explicitly replaced
only 15.2/15.4, never 15.3.

**Scope discipline (Phase 25)**: exactly ADR-0014 Decisions 6, 7, 8, and
12 -- customer/supplier role-tagging on existing `crm.contacts` rows
(never a second identity table, never `crm.companies`), a generic
tax-code catalog, invoices/bills with their line items, and payments/
allocations. No banking/reconciliation, no reports, no external provider
-- all explicitly deferred, per the ADR's own "Deferred / explicitly out
of scope" section. Credit notes are added by Phase 15.3 below, not Phase
25 -- see `CreditNote`'s own class docstring for that addition's own,
separately-scoped boundary.

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like `product/appointments/models.py`/`product/crm
/models.py` -- this module never imports `sqlalchemy` directly. `infra.db`
exports no `Date` column type, so `Account`/`Period`/`JournalEntry`'s
date-only fields (`Period.start_date`/`end_date`, `JournalEntry.entry_date`)
are plain `DateTime(timezone=True)` stored at UTC midnight and treated as
date-only by the service layer -- the identical substitution
`product/crm/models.py::CustomFieldValue.value_date`'s own module comment
already documents for the same reason ("infra.db's curated re-export
surface does not expose sqlalchemy.Date").

**Composite-FK discipline**, mirroring every other product module
exactly: every cross-table reference here is a `ForeignKeyConstraint`
against the target table's own `UniqueConstraint(tenant_id, id)`, never a
bare `ForeignKey` on the id column alone.

**Money representation (ADR-0014 Decision 4)**: `journal_lines
.debit_amount`/`credit_amount` are `Numeric(18, 2)` -- never floating
point, never integer minor units (deliberately *not*
`product/crm/models.py::Opportunity`'s own `amount_minor_units`
convention; see Decision 4's own reasoning). Exactly one of the two
columns is strictly positive on any given line, enforced by
`ck_accounting_journal_lines_exactly_one_side` below -- the schema itself
makes "a negative debit" or "a line that is its own debit and credit"
structurally impossible, not merely discouraged.

**Immutability (Decision 3)**: `JournalEntry.status` lifecycle is
`draft -> posted`, `draft -> voided`, `posted -> reversed`. No service
function in this module ever updates or deletes a `posted` entry's own
rows -- `product/accounting/journal.py` has no `update_journal_entry()`/
`delete_journal_line()` once status is `posted`; the ORM classes below
carry no delete-cascade path that could reach a posted row's lines either
(`journal_lines.journal_entry_id` is `ON DELETE CASCADE` for referential
cleanliness, but no service function ever deletes a `JournalEntry` row at
all -- draft correction is `void_journal_entry()`, a status flip, never a
delete).

**Deletion behavior**: `journal_lines.account_id` has no `ON DELETE`
behavior decided (the default `RESTRICT`) -- deliberately, per Decision
9's own explicit requirement ("prevent deletion of accounts referenced by
posted journal entries"); this module ships no account-delete function at
all this phase (see `product/accounting/accounts.py`'s own module
docstring), so the constraint is declared defensively, matching
`product/appointments/models.py::Appointment.calendar_id`'s own
identical "no delete path exists yet, but the FK behavior is decided
anyway" precedent.

**Period non-overlap (Decision 5) -- declared entirely in the migration,
never in this ORM model**, mirroring `product/appointments/models.py`'s
own "the double-booking prevention constraint... declared entirely in the
migration" precedent exactly: a PostgreSQL `EXCLUDE USING gist (tenant_id
WITH =, period_range WITH &&)` constraint (no partial `WHERE` predicate --
unlike a cancelled appointment's slot, a `CLOSED` period's date range is
never freed for reuse), backed by a `GENERATED ALWAYS AS
(daterange((start_date AT TIME ZONE 'UTC')::date, (end_date AT TIME ZONE
'UTC')::date, '[]')) STORED` column (`btree_gist` extension, already
installed by migration `0026`, left installed on every downgrade since --
this migration adds no second `CREATE EXTENSION`). The generated
`period_range` column is deliberately **not mapped on the `Period` class
below**, for the identical reason
`Appointment.time_range` is not mapped: Postgres rejects any explicit
value for a `GENERATED ALWAYS` column, so SQLAlchemy must never see it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from infra.db import (
    Base,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Mapped,
    Numeric,
    String,
    UniqueConstraint,
    mapped_column,
    now,
)

ACCOUNT_TYPE_ASSET = "asset"
ACCOUNT_TYPE_LIABILITY = "liability"
ACCOUNT_TYPE_EQUITY = "equity"
ACCOUNT_TYPE_REVENUE = "revenue"
ACCOUNT_TYPE_EXPENSE = "expense"
# The universal five-category double-entry classification -- not a
# jurisdiction-specific policy choice (unlike VAT rates or a chart-of-
# accounts numbering convention, both correctly left undecided by this
# phase), so choosing it is not "inventing accounting policy": every
# double-entry bookkeeping system distinguishes at least these five
# categories to know what a balanced ledger even means. No numbering
# range (e.g. "1000s = assets") is imposed on `Account.code` -- that
# would be a real, undecided policy choice this phase does not make.
VALID_ACCOUNT_TYPES = (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_LIABILITY,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_REVENUE,
    ACCOUNT_TYPE_EXPENSE,
)

PERIOD_STATUS_OPEN = "open"
PERIOD_STATUS_CLOSED = "closed"
VALID_PERIOD_STATUSES = (PERIOD_STATUS_OPEN, PERIOD_STATUS_CLOSED)

JOURNAL_ENTRY_STATUS_DRAFT = "draft"
JOURNAL_ENTRY_STATUS_POSTED = "posted"
JOURNAL_ENTRY_STATUS_VOIDED = "voided"
JOURNAL_ENTRY_STATUS_REVERSED = "reversed"
VALID_JOURNAL_ENTRY_STATUSES = (
    JOURNAL_ENTRY_STATUS_DRAFT,
    JOURNAL_ENTRY_STATUS_POSTED,
    JOURNAL_ENTRY_STATUS_VOIDED,
    JOURNAL_ENTRY_STATUS_REVERSED,
)

MAX_ACCOUNT_CODE_LENGTH = 32
MAX_ACCOUNT_NAME_LENGTH = 255
MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH = 500

ZERO = Decimal("0")


class Account(Base):
    """A chart-of-accounts entry (ADR-0014 Decision 2's own ledger
    target). `code`/`name` are tenant-customizable -- this phase seeds no
    default chart of accounts (`docs/ACCOUNTING-SCOPE.md`'s "a sensible
    small default set" is a future UX convenience, not this phase's own
    scope, which the roadmap's own Objective line does not name)."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_accounts_tenant_id_id"),
        UniqueConstraint("tenant_id", "code", name="uq_accounting_accounts_tenant_code"),
        CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')",
            name="ck_accounting_accounts_account_type",
        ),
        Index("ix_accounting_accounts_tenant_id", "tenant_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(MAX_ACCOUNT_CODE_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_ACCOUNT_NAME_LENGTH), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class Period(Base):
    """An accounting period (ADR-0014 Decision 5). `start_date`/`end_date`
    are inclusive on both ends (`daterange(..., '[]')`, module docstring)
    -- a single-day period has `start_date == end_date`. Non-overlap
    across a tenant's own periods is enforced entirely in the migration
    (module docstring); this class declares no `CHECK` for it (Postgres
    has no cross-row `CHECK`, the identical reason
    `product/appointments/models.py::Appointment`'s own double-booking
    constraint lives only in its migration)."""

    __tablename__ = "periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_periods_tenant_id_id"),
        CheckConstraint("end_date >= start_date", name="ck_accounting_periods_end_after_start"),
        CheckConstraint("status IN ('open', 'closed')", name="ck_accounting_periods_status"),
        Index("ix_accounting_periods_tenant_id", "tenant_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default=PERIOD_STATUS_OPEN)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )
    # Deliberately NOT mapped here: the generated `period_range` column
    # and the EXCLUDE constraint that references it -- see module
    # docstring.


class JournalEntry(Base):
    """A journal entry header (ADR-0014 Decisions 2-3). `period_id` is
    `NULL` for a `draft` entry -- it is resolved and populated only by
    `post_journal_entry()`, by looking up the `OPEN` period whose date
    range contains `entry_date` (Decision 5: "no period is ever silently
    created"); never chosen directly by the caller. `reverses_entry_id`
    is set only on the *new* entry a reversal creates, pointing back at
    the original -- never the other way around."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_journal_entries_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["accounting.periods.tenant_id", "accounting.periods.id"],
            name="fk_accounting_journal_entries_tenant_period",
            # No ON DELETE behavior decided (default RESTRICT) -- this
            # phase ships no period-delete function at all (only
            # open/closed status changes), mirroring
            # `Appointment.calendar_id`'s own identical disclosed shape.
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reverses_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_journal_entries_tenant_reverses_entry",
            # Self-referential; no ON DELETE behavior decided (default
            # RESTRICT) -- no service function ever deletes a
            # JournalEntry row (module docstring).
        ),
        CheckConstraint(
            "status IN ('draft', 'posted', 'voided', 'reversed')",
            name="ck_accounting_journal_entries_status",
        ),
        Index("ix_accounting_journal_entries_tenant_id", "tenant_id"),
        Index("ix_accounting_journal_entries_period_id", "period_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    entry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 3-letter uppercase ISO-4217-shaped code, validated at creation via
    # `product.foundation.values.Money`'s own `InvalidCurrencyCodeError`
    # check (product/accounting/journal.py::create_journal_entry()) --
    # reusing that module's existing validation, never a second currency-
    # shape regex. One currency per entry -- multi-currency/FX is out of
    # scope for this phase (ADR-0014 Decision 4).
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(
        String(MAX_JOURNAL_ENTRY_DESCRIPTION_LENGTH), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default=JOURNAL_ENTRY_STATUS_DRAFT
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    posted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.users.id"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class JournalLine(Base):
    """One debit or credit line of a `JournalEntry` (ADR-0014 Decision
    4). Exactly one of `debit_amount`/`credit_amount` is strictly
    positive; the other is exactly zero -- `ck_accounting_journal_lines
    _exactly_one_side` makes the alternative (both zero, both positive,
    either negative) structurally impossible. Entry-level balance
    (`sum(debits) == sum(credits)` across a whole entry's lines) is
    **not** expressed here -- Postgres has no cross-row `CHECK`; it is
    enforced by `product/accounting/journal.py::post_journal_entry()`
    inside the same transaction as the status flip to `posted`, before
    any commit (Decision 4's own disclosed exception: the one accounting
    invariant in this module that is service-layer-only)."""

    __tablename__ = "journal_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_journal_lines_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_journal_lines_tenant_journal_entry",
            # A line has no meaning without its entry -- mirrors
            # `availability_rules.calendar_id`'s own CASCADE precedent.
            # No service function ever deletes a JournalEntry row today
            # (module docstring), so this path is declared, not
            # currently reachable.
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_journal_lines_tenant_account",
            # No ON DELETE behavior decided (default RESTRICT) --
            # deliberately, per ADR-0014 Decision 9's own explicit
            # requirement: an account referenced by any journal line must
            # never be deletable out from under it. This phase ships no
            # account-delete function at all (module docstring), so this
            # is declared defensively, not currently reachable.
        ),
        CheckConstraint(
            "(debit_amount > 0 AND credit_amount = 0) OR (credit_amount > 0 AND debit_amount = 0)",
            name="ck_accounting_journal_lines_exactly_one_side",
        ),
        Index("ix_accounting_journal_lines_tenant_id", "tenant_id"),
        Index("ix_accounting_journal_lines_journal_entry_id", "journal_entry_id"),
        Index("ix_accounting_journal_lines_account_id", "account_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


CONTACT_ROLE_CUSTOMER = "customer"
CONTACT_ROLE_SUPPLIER = "supplier"
CONTACT_ROLE_BOTH = "both"
VALID_CONTACT_ROLES = (CONTACT_ROLE_CUSTOMER, CONTACT_ROLE_SUPPLIER, CONTACT_ROLE_BOTH)

TAX_TYPE_SALES = "sales"
TAX_TYPE_PURCHASE = "purchase"
VALID_TAX_TYPES = (TAX_TYPE_SALES, TAX_TYPE_PURCHASE)

DOCUMENT_STATUS_DRAFT = "draft"
DOCUMENT_STATUS_POSTED = "posted"
DOCUMENT_STATUS_CANCELLED = "cancelled"
DOCUMENT_STATUS_VOIDED = "voided"
VALID_DOCUMENT_STATUSES = (
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_POSTED,
    DOCUMENT_STATUS_CANCELLED,
    DOCUMENT_STATUS_VOIDED,
)

PAYMENT_DIRECTION_INBOUND = "inbound"
PAYMENT_DIRECTION_OUTBOUND = "outbound"
VALID_PAYMENT_DIRECTIONS = (PAYMENT_DIRECTION_INBOUND, PAYMENT_DIRECTION_OUTBOUND)

ALLOCATION_DOCUMENT_TYPE_INVOICE = "invoice"
ALLOCATION_DOCUMENT_TYPE_BILL = "bill"
VALID_ALLOCATION_DOCUMENT_TYPES = (ALLOCATION_DOCUMENT_TYPE_INVOICE, ALLOCATION_DOCUMENT_TYPE_BILL)

MAX_TAX_CODE_LENGTH = 32
MAX_TAX_NAME_LENGTH = 255
MAX_LINE_DESCRIPTION_LENGTH = 500
MAX_DOCUMENT_DESCRIPTION_LENGTH = 500
MAX_SUPPLIER_REFERENCE_LENGTH = 100
MAX_PAYMENT_REFERENCE_LENGTH = 255

# docs/ROADMAP.md Phase 15.5 ("Banking -- manual import and reconciliation").
BANK_LINE_STATUS_UNMATCHED = "unmatched"
BANK_LINE_STATUS_RECONCILED = "reconciled"
VALID_BANK_LINE_STATUSES = (BANK_LINE_STATUS_UNMATCHED, BANK_LINE_STATUS_RECONCILED)

MAX_BANK_ACCOUNT_NAME_LENGTH = 255
MAX_IBAN_LENGTH = 34  # ISO 13616 maximum IBAN length across all countries.
MAX_BANK_STATEMENT_REFERENCE_LENGTH = 255
MAX_BANK_LINE_DESCRIPTION_LENGTH = 500
MAX_COUNTERPARTY_REFERENCE_LENGTH = 255
BANK_LINE_HASH_LENGTH = 64  # sha256 hex digest length.


class ContactProfile(Base):
    """ADR-0014 Decision 6: the *only* thing this module adds to CRM's own
    contact identity -- a `(tenant_id, contact_id)`-scoped role tag.
    `crm.contacts` remains the sole identity table; `crm.companies` is
    explicitly not a supported counterparty (Decision 6's own addendum) --
    a company is represented through the company's own billing contact
    (`crm.contacts.company_id`), never a second, parallel reference here.
    One profile per contact (`uq_accounting_contact_profiles_tenant_contact`)
    -- a contact is tagged once, not once per role.

    **Deletion (Decision 6 addendum)**: the FK to `crm.contacts` carries no
    `ON DELETE` clause (default `RESTRICT`) -- once a contact is tagged, or
    ever referenced by an `Invoice`/`Bill`, `product.crm.contacts
    .delete_contact()` fails with a raw, untranslated `IntegrityError`.
    This is a disclosed, accepted trade-off, not a gap -- see the ADR's
    own addendum for the full reasoning and its `Appointment.calendar_id`
    precedent. `product/crm/` is not modified to add a friendlier error."""

    __tablename__ = "contact_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_contact_profiles_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "contact_id", name="uq_accounting_contact_profiles_tenant_contact"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_accounting_contact_profiles_tenant_contact",
            # RESTRICT (default) -- see class docstring / ADR-0014
            # Decision 6 addendum.
        ),
        CheckConstraint(
            "role IN ('customer', 'supplier', 'both')",
            name="ck_accounting_contact_profiles_role",
        ),
        Index("ix_accounting_contact_profiles_tenant_id", "tenant_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class TaxCode(Base):
    """ADR-0014 Decision 7: a tenant-owned tax-rate catalog. No rate is
    ever seeded by this module's own migration or code -- a tenant (or a
    later, deliberately-not-built-here localization "tax pack") creates
    its own codes. `tax_account_id` is required: a tax code's collected/
    paid amounts always post to a real GL account when an invoice/bill
    line using it is posted (Decision 7's own "not a side-channel total"
    requirement)."""

    __tablename__ = "tax_codes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_tax_codes_tenant_id_id"),
        UniqueConstraint("tenant_id", "code", name="uq_accounting_tax_codes_tenant_code"),
        ForeignKeyConstraint(
            ["tenant_id", "tax_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_tax_codes_tenant_account",
            # No ON DELETE decided (default RESTRICT) -- a tax code's
            # posting account must never be deletable out from under it,
            # mirroring journal_lines.account_id's own Decision 9 logic.
        ),
        CheckConstraint("tax_type IN ('sales', 'purchase')", name="ck_accounting_tax_codes_type"),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_accounting_tax_codes_effective_range",
        ),
        Index("ix_accounting_tax_codes_tenant_id", "tenant_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(MAX_TAX_CODE_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_TAX_NAME_LENGTH), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    tax_type: Mapped[str] = mapped_column(String(8), nullable=False)
    tax_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Date-only, stored at UTC midnight -- infra.db exports no Date type,
    # mirrors Period.start_date/end_date's own identical substitution
    # (module docstring).
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class Invoice(Base):
    """A customer invoice header (ADR-0014 Decision 12). `invoice_number`
    is `NULL` while `draft` -- assigned only by `post_invoice()`, under
    the tenant-wide gapless-numbering advisory lock (Decision 12's own
    numbering mechanism), exactly mirroring `JournalEntry.period_id`'s own
    "resolved only at posting" shape. `subtotal`/`tax_total`/`total` are
    always derived (`SUM()` of `InvoiceLine` values, Decision 7 addendum),
    never caller-supplied. `outstanding_amount` is the one denormalized,
    transactionally-updated exception (Decision 2's own pattern, applied
    here exactly as it already is to `Payment.unallocated_amount`).
    `receivable_account_id`/`journal_entry_id` are what make Decision 2
    ("posted journal entries are the sole source of truth") concretely
    true for invoices, not merely asserted -- posting an invoice creates a
    real `JournalEntry` via the unmodified `product/accounting/journal.py
    ::post_journal_entry()`."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_invoices_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_accounting_invoices_tenant_contact",
            # RESTRICT (default) -- defense in depth alongside
            # ContactProfile's own RESTRICT, per ADR-0014 Decision 6
            # addendum: a posted invoice must never lose its counterparty.
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receivable_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_invoices_tenant_receivable_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["accounting.periods.tenant_id", "accounting.periods.id"],
            name="fk_accounting_invoices_tenant_period",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_invoices_tenant_journal_entry",
        ),
        CheckConstraint(
            "status IN ('draft', 'posted', 'cancelled', 'voided')",
            name="ck_accounting_invoices_status",
        ),
        CheckConstraint("due_date >= issue_date", name="ck_accounting_invoices_due_after_issue"),
        Index("ix_accounting_invoices_tenant_id", "tenant_id"),
        Index("ix_accounting_invoices_contact_id", "contact_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    invoice_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    receivable_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(9), nullable=False, default=DOCUMENT_STATUS_DRAFT)
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    outstanding_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=ZERO
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(
        String(MAX_DOCUMENT_DESCRIPTION_LENGTH), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    posted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.users.id"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )
    # Deliberately NOT mapped here: the partial unique index on
    # (tenant_id, invoice_number) WHERE invoice_number IS NOT NULL --
    # declared entirely in the migration (mirrors Period.period_range's
    # own "declared entirely in the migration" precedent), since
    # SQLAlchemy's declarative UniqueConstraint has no partial-index
    # predicate vocabulary in this codebase's own established usage.


class InvoiceLine(Base):
    """One line of an `Invoice` (ADR-0014 Decision 12). Fully immutable
    once the parent invoice posts -- no service function in this module
    updates or deletes a line belonging to a non-`draft` invoice,
    mirroring `JournalLine`'s own complete-immutability shape exactly."""

    __tablename__ = "invoice_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_invoice_lines_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["accounting.invoices.tenant_id", "accounting.invoices.id"],
            name="fk_accounting_invoice_lines_tenant_invoice",
            # A line has no meaning without its invoice -- mirrors
            # `journal_lines.journal_entry_id`'s own CASCADE precedent.
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_invoice_lines_tenant_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tax_code_id"],
            ["accounting.tax_codes.tenant_id", "accounting.tax_codes.id"],
            name="fk_accounting_invoice_lines_tenant_tax_code",
        ),
        CheckConstraint("quantity > 0", name="ck_accounting_invoice_lines_quantity_positive"),
        CheckConstraint(
            "unit_price >= 0", name="ck_accounting_invoice_lines_unit_price_non_negative"
        ),
        Index("ix_accounting_invoice_lines_tenant_id", "tenant_id"),
        Index("ix_accounting_invoice_lines_invoice_id", "invoice_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(MAX_LINE_DESCRIPTION_LENGTH), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tax_code_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    line_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class CreditNote(Base):
    """A credit note correcting an already-posted `Invoice` (docs/ROADMAP.md
    Phase 15.3, deferred by Phase 25's own explicit scope note and
    implemented separately once Phase 25's invoice/payment foundation
    existed to reference). **Never mutates the `Invoice` it references** --
    no service function in this module writes to any `Invoice`/`InvoiceLine`
    column; `invoice_id` is a plain, immutable reference, RESTRICT on
    delete (an invoice a credit note references must never disappear out
    from under it, mirroring `Invoice.contact_id`'s own RESTRICT
    reasoning). `credit_note_number` is `NULL` while `draft`, assigned only
    by `post_credit_note()` under this table's own tenant-wide
    gapless-numbering advisory lock -- a genuinely separate numbering
    sequence from `Invoice.invoice_number` (Dutch legal numbering
    requirements are satisfied per-document-type; sharing one counter
    across two different document types would not itself violate
    gaplessness, but conflates two legally distinct sequences for no
    benefit), exactly mirroring `Invoice.invoice_number`'s own "resolved
    only at posting" mechanism.

    **Deliberately narrow scope, matching Phase 15.3's own literal Tests
    requirement** ("a credit note never mutates the original invoice; the
    reference is always resolvable") **and nothing broader**: posting a
    credit note does NOT adjust `Invoice.outstanding_amount` -- reconciling
    a credit note against what a customer still owes (or carrying a credit
    balance forward when an invoice is already fully paid) is a real,
    separate accounts-receivable-netting decision Phase 15.3's own spec
    does not make, and this implementation does not invent it. A future
    phase that wires credit notes into `outstanding_amount`/reporting
    reads this table and `Payment`/`PaymentAllocation`'s own existing
    pattern (`payments.py::_create_allocation_in_session()`'s locked
    read-validate-subtract shape) as its starting point, not a fresh
    design."""

    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_credit_notes_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["accounting.invoices.tenant_id", "accounting.invoices.id"],
            name="fk_accounting_credit_notes_tenant_invoice",
            # RESTRICT (default) -- a credit note must never outlive the
            # invoice it corrects; mirrors Invoice.contact_id's own
            # RESTRICT reasoning (class docstring).
        ),
        ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["accounting.periods.tenant_id", "accounting.periods.id"],
            name="fk_accounting_credit_notes_tenant_period",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_credit_notes_tenant_journal_entry",
        ),
        CheckConstraint(
            "status IN ('draft', 'posted', 'voided')",
            name="ck_accounting_credit_notes_status",
        ),
        Index("ix_accounting_credit_notes_tenant_id", "tenant_id"),
        Index("ix_accounting_credit_notes_invoice_id", "invoice_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    credit_note_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(6), nullable=False, default=DOCUMENT_STATUS_DRAFT)
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    period_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(
        String(MAX_DOCUMENT_DESCRIPTION_LENGTH), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    posted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.users.id"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )
    # Deliberately NOT mapped here: the partial unique index on
    # (tenant_id, credit_note_number) WHERE credit_note_number IS NOT NULL
    # -- mirrors Invoice's own identical "declared entirely in the
    # migration" precedent.


class CreditNoteLine(Base):
    """One line of a `CreditNote` (class docstring above). Fully immutable
    once the parent credit note posts, mirroring `InvoiceLine`'s own
    complete-immutability shape exactly."""

    __tablename__ = "credit_note_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_credit_note_lines_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "credit_note_id"],
            ["accounting.credit_notes.tenant_id", "accounting.credit_notes.id"],
            name="fk_accounting_credit_note_lines_tenant_credit_note",
            # A line has no meaning without its credit note -- mirrors
            # invoice_lines.invoice_id's own CASCADE precedent.
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_credit_note_lines_tenant_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tax_code_id"],
            ["accounting.tax_codes.tenant_id", "accounting.tax_codes.id"],
            name="fk_accounting_credit_note_lines_tenant_tax_code",
        ),
        CheckConstraint("quantity > 0", name="ck_accounting_credit_note_lines_quantity_positive"),
        CheckConstraint(
            "unit_price >= 0", name="ck_accounting_credit_note_lines_unit_price_non_negative"
        ),
        Index("ix_accounting_credit_note_lines_tenant_id", "tenant_id"),
        Index("ix_accounting_credit_note_lines_credit_note_id", "credit_note_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    credit_note_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(MAX_LINE_DESCRIPTION_LENGTH), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tax_code_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    line_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class Bill(Base):
    """A supplier bill header (ADR-0014 Decision 12) -- the purchase-side
    mirror of `Invoice`, with one deliberate asymmetry: no internally
    generated gapless number. Gapless sequential numbering is a legal
    requirement for invoices a tenant *issues*, never for bills a tenant
    *receives* -- a bill already carries the supplier's own
    `supplier_reference`, used for the roadmap's own "duplicate checked"
    step (`uq_accounting_bills_tenant_contact_reference`)."""

    __tablename__ = "bills"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_bills_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "contact_id",
            "supplier_reference",
            name="uq_accounting_bills_tenant_contact_reference",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_accounting_bills_tenant_contact",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "payable_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_bills_tenant_payable_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["accounting.periods.tenant_id", "accounting.periods.id"],
            name="fk_accounting_bills_tenant_period",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_bills_tenant_journal_entry",
        ),
        CheckConstraint(
            "status IN ('draft', 'posted', 'cancelled', 'voided')",
            name="ck_accounting_bills_status",
        ),
        CheckConstraint("due_date >= bill_date", name="ck_accounting_bills_due_after_bill_date"),
        Index("ix_accounting_bills_tenant_id", "tenant_id"),
        Index("ix_accounting_bills_contact_id", "contact_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    supplier_reference: Mapped[str] = mapped_column(
        String(MAX_SUPPLIER_REFERENCE_LENGTH), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    payable_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(9), nullable=False, default=DOCUMENT_STATUS_DRAFT)
    bill_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    outstanding_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=ZERO
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(
        String(MAX_DOCUMENT_DESCRIPTION_LENGTH), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    posted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.users.id"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class BillLine(Base):
    """One line of a `Bill` -- identical shape to `InvoiceLine`, with an
    expense/liability-side `account_id` instead of a revenue one."""

    __tablename__ = "bill_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_bill_lines_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "bill_id"],
            ["accounting.bills.tenant_id", "accounting.bills.id"],
            name="fk_accounting_bill_lines_tenant_bill",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_bill_lines_tenant_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tax_code_id"],
            ["accounting.tax_codes.tenant_id", "accounting.tax_codes.id"],
            name="fk_accounting_bill_lines_tenant_tax_code",
        ),
        CheckConstraint("quantity > 0", name="ck_accounting_bill_lines_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_accounting_bill_lines_unit_price_non_negative"),
        Index("ix_accounting_bill_lines_tenant_id", "tenant_id"),
        Index("ix_accounting_bill_lines_bill_id", "bill_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    bill_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(MAX_LINE_DESCRIPTION_LENGTH), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tax_code_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    line_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=ZERO)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class Payment(Base):
    """ADR-0014 Decision 8 (+ addendum). No separate lifecycle/status
    column -- `unallocated_amount` is the single source of truth (a view
    layer may present `== 0` as "fully allocated"); this is a derivation
    rule, not a modeling gap. No cash-leg journal entry is created for a
    payment this phase (Decision 8's own explicit exclusion)."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_payments_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_accounting_payments_tenant_contact",
        ),
        CheckConstraint(
            "direction IN ('inbound', 'outbound')", name="ck_accounting_payments_direction"
        ),
        CheckConstraint("amount > 0", name="ck_accounting_payments_amount_positive"),
        CheckConstraint(
            "unallocated_amount >= 0 AND unallocated_amount <= amount",
            name="ck_accounting_payments_unallocated_bounds",
        ),
        Index("ix_accounting_payments_tenant_id", "tenant_id"),
        Index("ix_accounting_payments_contact_id", "contact_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unallocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reference: Mapped[str | None] = mapped_column(
        String(MAX_PAYMENT_REFERENCE_LENGTH), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class PaymentAllocation(Base):
    """ADR-0014 Decision 8 (+ addendum). `document_type`/`document_id` is
    a deliberately soft, application-level polymorphic reference (never a
    hard FK -- a payment allocates against exactly one of two different
    tables; `product/accounting/payments.py::create_allocation()`
    re-reads the target row through the same tenant's
    `tenant_session_scope()` before allocating, which makes a cross-tenant
    target simply not exist rather than merely unauthorized, exactly as
    the ADR specifies). Immutable once created -- `reverses_allocation_id`
    (nullable, self-referential) is set only on the new row a reversal
    creates; a reversal's own `amount` restores the same magnitude back to
    both the payment and the document, never a signed/negative amount."""

    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_payment_allocations_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["accounting.payments.tenant_id", "accounting.payments.id"],
            name="fk_accounting_payment_allocations_tenant_payment",
            # A allocation has no meaning without its payment -- mirrors
            # invoice_lines/journal_lines' own CASCADE precedent. No
            # service function ever deletes a Payment row today.
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reverses_allocation_id"],
            [
                "accounting.payment_allocations.tenant_id",
                "accounting.payment_allocations.id",
            ],
            name="fk_accounting_payment_allocations_tenant_reverses",
        ),
        CheckConstraint(
            "document_type IN ('invoice', 'bill')",
            name="ck_accounting_payment_allocations_document_type",
        ),
        CheckConstraint("amount > 0", name="ck_accounting_payment_allocations_amount_positive"),
        Index("ix_accounting_payment_allocations_tenant_id", "tenant_id"),
        Index("ix_accounting_payment_allocations_payment_id", "payment_id"),
        Index(
            "ix_accounting_payment_allocations_document",
            "tenant_id",
            "document_type",
            "document_id",
        ),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_type: Mapped[str] = mapped_column(String(7), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reverses_allocation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class BankAccount(Base):
    """Bank-account metadata (docs/ROADMAP.md Phase 15.5,
    `docs/ACCOUNTING-SCOPE.md` "Banking": "Bank accounts (metadata only
    initially -- not live aggregation)"). Deliberately thin: a display
    name and an optional IBAN, plus the one field that actually matters
    for double-entry correctness -- `ledger_account_id`, the tenant's own
    chart-of-accounts `Account` (always `asset`-typed) this bank account's
    real-money balance posts against. This is NOT a live-balance/
    aggregation entity (`docs/ACCOUNTING-SCOPE.md`'s own "Bank Integration
    Phasing" step 2, a PSD2 AIS provider integration, is a distinct,
    deliberately deferred future phase -- Category D, provider-abstracted
    from day one of *that* phase, never assumed here). One `BankAccount`
    per ledger `Account` (`uq_accounting_bank_accounts_tenant_ledger_account`)
    -- designating the same GL account as two different bank accounts
    would make reconciliation postings ambiguous."""

    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_bank_accounts_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "ledger_account_id",
            name="uq_accounting_bank_accounts_tenant_ledger_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ledger_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_bank_accounts_tenant_ledger_account",
        ),
        Index("ix_accounting_bank_accounts_tenant_id", "tenant_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_BANK_ACCOUNT_NAME_LENGTH), nullable=False)
    iban: Mapped[str | None] = mapped_column(String(MAX_IBAN_LENGTH), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class BankStatement(Base):
    """One imported bank statement (docs/ROADMAP.md Phase 15.5,
    `docs/ACCOUNTING-SCOPE.md` "Bank Integration Phasing" step 1: "manual
    bank statement import (CSV, and MT940 if a target bank commonly
    exports it)... No live aggregation."). `product/accounting/banking.py`
    ships only the CSV importer this phase -- MT940 (a distinct SWIFT
    text format needing its own parser) is deliberately not built yet;
    nothing here assumes CSV-only, so an MT940 importer can be added later
    as a second, independent parser feeding the identical normalized
    line-import path, never a schema change (`banking.py`'s own module
    docstring)."""

    __tablename__ = "bank_statements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_bank_statements_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "bank_account_id"],
            ["accounting.bank_accounts.tenant_id", "accounting.bank_accounts.id"],
            name="fk_accounting_bank_statements_tenant_bank_account",
        ),
        CheckConstraint(
            "period_end_date >= period_start_date",
            name="ck_accounting_bank_statements_period_valid",
        ),
        Index("ix_accounting_bank_statements_tenant_id", "tenant_id"),
        Index("ix_accounting_bank_statements_bank_account_id", "bank_account_id"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reference: Mapped[str | None] = mapped_column(
        String(MAX_BANK_STATEMENT_REFERENCE_LENGTH), nullable=True
    )
    period_start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class BankStatementLine(Base):
    """One line of an imported `BankStatement` (docs/ROADMAP.md Phase
    15.5). `amount` is signed exactly as it appears on a real bank
    statement -- positive for an inflow/credit, negative for an
    outflow/debit -- never split into separate debit/credit columns the
    way `JournalLine` is (a statement line is a raw import fact, not yet
    a ledger posting).

    **Reconciliation state (`status`)** is deliberately two-valued, not
    three: `unmatched` -> `reconciled`. The "semi-automatic matching with
    a manual confirm step" the roadmap describes
    (`docs/ACCOUNTING-SCOPE.md` "Bank Integration Phasing" step 1) is a
    stateless, read-only *suggestion* (`banking.py::suggest_matches()`,
    never persisted) followed by one of two explicit, mutating confirm
    calls (`confirm_match_to_document()`/`assign_line_to_account()`) that
    both transition a line directly from `unmatched` to `reconciled` --
    there is no intermediate "system-suggested, not yet confirmed"
    database state to keep synchronized, because the suggestion is
    recomputed fresh on every read rather than cached.

    **Duplicate detection**: `line_hash` (`sha256(bank_account_id |
    transaction_date | amount | description)`, module docstring) backs
    `uq_accounting_bank_statement_lines_tenant_account_hash` -- re-
    importing a statement whose date range overlaps a previous import
    re-computes the identical hash for the overlapping lines, so
    `product/accounting/banking.py::import_bank_statement_csv()` can skip
    them (never re-insert, never double-count) rather than rejecting the
    whole file. `bank_account_id` is denormalized from the parent
    `BankStatement` (copied at import time) purely so this uniqueness
    constraint and duplicate-detection query never need a join back to
    the parent -- the same "one denormalized, transactionally-set field"
    discipline `Invoice.outstanding_amount` already establishes.

    **Reconciliation posting**: confirming a match or assigning an
    unmatched line to an account both post a real cash-leg `JournalEntry`
    (`journal_entry_id`) -- closing the gap `Payment`'s own module
    docstring names explicitly ("no bank/cash GL account is designated
    yet... this phase"): Phase 15.5 is what designates it, via
    `BankAccount.ledger_account_id`."""

    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_accounting_bank_statement_lines_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "bank_account_id",
            "line_hash",
            name="uq_accounting_bank_statement_lines_tenant_account_hash",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "bank_statement_id"],
            ["accounting.bank_statements.tenant_id", "accounting.bank_statements.id"],
            name="fk_accounting_bank_statement_lines_tenant_statement",
            # A line has no meaning without its statement -- mirrors
            # invoice_lines.invoice_id's own CASCADE precedent.
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "bank_account_id"],
            ["accounting.bank_accounts.tenant_id", "accounting.bank_accounts.id"],
            name="fk_accounting_bank_statement_lines_tenant_bank_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "matched_payment_id"],
            ["accounting.payments.tenant_id", "accounting.payments.id"],
            name="fk_accounting_bank_statement_lines_tenant_payment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "matched_account_id"],
            ["accounting.accounts.tenant_id", "accounting.accounts.id"],
            name="fk_accounting_bank_statement_lines_tenant_matched_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "journal_entry_id"],
            ["accounting.journal_entries.tenant_id", "accounting.journal_entries.id"],
            name="fk_accounting_bank_statement_lines_tenant_journal_entry",
        ),
        CheckConstraint("amount != 0", name="ck_accounting_bank_statement_lines_amount_nonzero"),
        CheckConstraint(
            "status IN ('unmatched', 'reconciled')",
            name="ck_accounting_bank_statement_lines_status",
        ),
        CheckConstraint(
            "matched_document_type IS NULL OR matched_document_type IN ('invoice', 'bill')",
            name="ck_accounting_bank_statement_lines_matched_document_type",
        ),
        Index("ix_accounting_bank_statement_lines_tenant_id", "tenant_id"),
        Index("ix_accounting_bank_statement_lines_bank_statement_id", "bank_statement_id"),
        Index("ix_accounting_bank_statement_lines_status", "tenant_id", "status"),
        {"schema": "accounting"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    bank_statement_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    description: Mapped[str] = mapped_column(
        String(MAX_BANK_LINE_DESCRIPTION_LENGTH), nullable=False
    )
    counterparty_reference: Mapped[str | None] = mapped_column(
        String(MAX_COUNTERPARTY_REFERENCE_LENGTH), nullable=True
    )
    line_hash: Mapped[str] = mapped_column(String(BANK_LINE_HASH_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=BANK_LINE_STATUS_UNMATCHED
    )
    matched_document_type: Mapped[str | None] = mapped_column(String(7), nullable=True)
    matched_document_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    matched_payment_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    matched_account_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reconciled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.users.id"), nullable=True
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


__all__ = [
    "ACCOUNT_TYPE_ASSET",
    "ACCOUNT_TYPE_EQUITY",
    "ACCOUNT_TYPE_EXPENSE",
    "ACCOUNT_TYPE_LIABILITY",
    "ACCOUNT_TYPE_REVENUE",
    "ALLOCATION_DOCUMENT_TYPE_BILL",
    "ALLOCATION_DOCUMENT_TYPE_INVOICE",
    "BANK_LINE_STATUS_RECONCILED",
    "BANK_LINE_STATUS_UNMATCHED",
    "CONTACT_ROLE_BOTH",
    "CONTACT_ROLE_CUSTOMER",
    "CONTACT_ROLE_SUPPLIER",
    "DOCUMENT_STATUS_CANCELLED",
    "DOCUMENT_STATUS_DRAFT",
    "DOCUMENT_STATUS_POSTED",
    "DOCUMENT_STATUS_VOIDED",
    "JOURNAL_ENTRY_STATUS_DRAFT",
    "JOURNAL_ENTRY_STATUS_POSTED",
    "JOURNAL_ENTRY_STATUS_REVERSED",
    "JOURNAL_ENTRY_STATUS_VOIDED",
    "PAYMENT_DIRECTION_INBOUND",
    "PAYMENT_DIRECTION_OUTBOUND",
    "PERIOD_STATUS_CLOSED",
    "PERIOD_STATUS_OPEN",
    "TAX_TYPE_PURCHASE",
    "TAX_TYPE_SALES",
    "VALID_ACCOUNT_TYPES",
    "VALID_ALLOCATION_DOCUMENT_TYPES",
    "VALID_BANK_LINE_STATUSES",
    "VALID_CONTACT_ROLES",
    "VALID_DOCUMENT_STATUSES",
    "VALID_JOURNAL_ENTRY_STATUSES",
    "VALID_PAYMENT_DIRECTIONS",
    "VALID_PERIOD_STATUSES",
    "VALID_TAX_TYPES",
    "Account",
    "BankAccount",
    "BankStatement",
    "BankStatementLine",
    "Bill",
    "BillLine",
    "ContactProfile",
    "CreditNote",
    "CreditNoteLine",
    "Invoice",
    "InvoiceLine",
    "JournalEntry",
    "JournalLine",
    "Payment",
    "PaymentAllocation",
    "Period",
    "TaxCode",
]
