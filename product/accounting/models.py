"""ORM models for the `accounting` schema (docs/ROADMAP.md Phase 24 --
"Mini Accounting Foundation"; `docs/ADR/0014-mini-accounting-foundation.md`,
currently PROPOSED -- see that document's own Status section).

**Scope discipline**: this module implements exactly ADR-0014 Decisions
1-5 (plus the journal/ledger-only slice of 9-11) -- chart of accounts,
accounting periods, journal entries, double-entry immutability, and
period locking. It deliberately does **not** implement Decisions 6-8
(customers/suppliers, tax codes, payments/allocations) -- those are
Phase 25's own `Invoice`/`Bill`/`Payment` surface, per the ADR's own
"Phase 24 / Phase 25 scope boundary" section. No table here references a
CRM contact, a tax code, or an invoice/bill/payment row.

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


__all__ = [
    "ACCOUNT_TYPE_ASSET",
    "ACCOUNT_TYPE_EQUITY",
    "ACCOUNT_TYPE_EXPENSE",
    "ACCOUNT_TYPE_LIABILITY",
    "ACCOUNT_TYPE_REVENUE",
    "JOURNAL_ENTRY_STATUS_DRAFT",
    "JOURNAL_ENTRY_STATUS_POSTED",
    "JOURNAL_ENTRY_STATUS_REVERSED",
    "JOURNAL_ENTRY_STATUS_VOIDED",
    "PERIOD_STATUS_CLOSED",
    "PERIOD_STATUS_OPEN",
    "VALID_ACCOUNT_TYPES",
    "VALID_JOURNAL_ENTRY_STATUSES",
    "VALID_PERIOD_STATUSES",
    "Account",
    "JournalEntry",
    "JournalLine",
    "Period",
]
