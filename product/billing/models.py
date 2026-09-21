"""ORM models for the `billing` schema (docs/ROADMAP.md Phase 13.2).

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like every other `product/*/models.py` -- this module
never imports `sqlalchemy` directly.

**`ResalePlan` is the ONLY product-owned table this phase introduces** --
`docs/ADR/0012-resale-billing-ownership-model.md`'s own "Decision" section:
subscriptions themselves live entirely in `core.billing_subscriptions`
(SaaS-OS, Category A); this table is the product-specific commercial
catalog entry a reseller tenant (an agency, or any tenant that resells
downward -- `docs/ADR/0012-...` deliberately does not call this
"agency-only") defines for its descendants, mapped onto SaaS-OS's own
entitlement primitives rather than replacing them.

**Ordinary RLS-scoped, tenant-owned data** -- `tenant_id` is the
*reseller* (the tenant that defined this plan), not the eventual
subscriber; every read/write happens with an already-established
`tenant_id`, so there is no reason to deviate from the default RLS-scoped
shape (unlike `product/websites/models.py::Website`'s own unscoped
public-lookup case).

**`key`** is unique only within its own reseller tenant
(`UniqueConstraint(tenant_id, key)`) -- the reseller's own human-chosen
slug (e.g. `"starter"`, `"pro"`), never exposed to `core.billing` directly.

**`underlying_plan_key`** is the opaque, product-generated key
(`f"resale:{resale_plan.id}"`, `product/billing/resale_plans.py`'s own
convention) identifying the real, auto-created `core.billing.Plan` row
this resale plan maps to -- globally unique (SaaS-OS's own
`core.billing_plans.key` carries a global `UNIQUE` constraint), never
user-supplied.

**`entitlements`** mirrors `core.billing.Plan.entitlements`'s own shape
exactly (a generic entitlement-key-to-value mapping) -- this column is
what gets copied onto the auto-created `core.billing.Plan.entitlements`
at creation time, never a second, independently-evolving entitlement
representation. Validated against the reseller's own current
entitlements (the "resale-tier ceiling check",
`product/billing/resale_plans.py::_validate_entitlement_ceiling()`)
before ever being persisted here or copied onward.

**`price_amount`/`price_currency`/`billing_interval`** are the product's
own commercial/display metadata -- SaaS-OS's `core.billing.Plan` carries
no price column at all (`core/billing/models.py`'s own module docstring:
"`Plan` carries no... 'price' column"), so this is genuinely
product-specific state, not a duplicate of anything SaaS-OS already
tracks. Informational only in this phase -- no real Stripe Price is
attached (`docs/ADR/0012-...`'s own "Provider status" section); a real
charge amount is whatever the eventual `core.billing.Plan
.provider_price_id`'s own Stripe Price object says, once one is
configured.

**`status`**: `enabled`/`disabled` -- a disabled resale plan is not
offered to new subscribers (`product/billing/subscriptions.py
::create_resale_subscription()` checks this) but existing subscriptions
against its underlying `core.billing.Plan` are entirely unaffected (this
table has no relationship to `core.billing_subscriptions` at all; SaaS-OS
alone tracks who is currently subscribed to what).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import (
    JSON,
    Base,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    String,
    UniqueConstraint,
    mapped_column,
    now,
)

MAX_KEY_LENGTH = 100
MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 1000
MAX_CURRENCY_LENGTH = 3
MAX_UNDERLYING_PLAN_KEY_LENGTH = 255

BILLING_INTERVAL_MONTH = "month"
BILLING_INTERVAL_YEAR = "year"
BILLING_INTERVALS = (BILLING_INTERVAL_MONTH, BILLING_INTERVAL_YEAR)

RESALE_PLAN_STATUS_ENABLED = "enabled"
RESALE_PLAN_STATUS_DISABLED = "disabled"
RESALE_PLAN_STATUSES = (RESALE_PLAN_STATUS_ENABLED, RESALE_PLAN_STATUS_DISABLED)


class ResalePlan(Base):
    """A reseller tenant's own commercial offering for its descendants
    (docs/ROADMAP.md Phase 13.2). Ordinary RLS-scoped, tenant-owned data;
    see module docstring."""

    __tablename__ = "resale_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_billing_resale_plans_tenant_key"),
        UniqueConstraint("underlying_plan_key", name="uq_billing_resale_plans_underlying_plan_key"),
        CheckConstraint("status IN ('enabled', 'disabled')", name="ck_billing_resale_plans_status"),
        CheckConstraint(
            "billing_interval IN ('month', 'year')",
            name="ck_billing_resale_plans_billing_interval",
        ),
        CheckConstraint("price_amount >= 0", name="ck_billing_resale_plans_price_amount"),
        Index("ix_billing_resale_plans_tenant_id", "tenant_id"),
        {"schema": "billing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(MAX_KEY_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(String(MAX_DESCRIPTION_LENGTH))
    price_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    price_currency: Mapped[str] = mapped_column(String(MAX_CURRENCY_LENGTH), nullable=False)
    billing_interval: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=BILLING_INTERVAL_MONTH
    )
    entitlements: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=RESALE_PLAN_STATUS_ENABLED
    )
    underlying_plan_key: Mapped[str] = mapped_column(
        String(MAX_UNDERLYING_PLAN_KEY_LENGTH), nullable=False
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


__all__ = [
    "BILLING_INTERVALS",
    "BILLING_INTERVAL_MONTH",
    "BILLING_INTERVAL_YEAR",
    "MAX_CURRENCY_LENGTH",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_KEY_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_UNDERLYING_PLAN_KEY_LENGTH",
    "RESALE_PLAN_STATUSES",
    "RESALE_PLAN_STATUS_DISABLED",
    "RESALE_PLAN_STATUS_ENABLED",
    "ResalePlan",
]
