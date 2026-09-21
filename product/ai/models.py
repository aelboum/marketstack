"""This product's own ORM models for the `ai` schema (docs/ROADMAP.md
Phase 9.4) -- declared on the installed saas-os package's shared
`infra.db` base and primitives, exactly the way every other
`product/*/models.py` in this repository does, so this module never
imports `sqlalchemy` directly (docs/REPOSITORY-STRATEGY.md). Row-Level
Security is established by the migration
(`infra.db.tenant_rls_statements`); this model only maps the columns.

**One row per tenant, and the row's absence is meaningful.** No row means
no policy, which `control_plane.data_authorization` already treats as an
unconditional deny (`NO_TENANT_POLICY` is its own first check). So the
default state of every tenant that has never been explicitly configured
is "no tenant data may reach an LLM provider" -- the same posture Phase
9.1-9.3 had, now persisted and per-tenant rather than hardcoded.

**Why the approved capabilities are a JSON list rather than a child
table.** The set is bounded by `product/ai/capabilities.py`'s own closed
production vocabulary (one entry today, and widening it is a reviewed
decision), every read wants the whole set at once, and nothing ever
queries "which tenants approved capability X" -- the same bounded-JSON-
on-row reasoning `product/automation/durable/models.py` already applies
to its own step list, rather than a table that exists only to be joined
back together on every read.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import JSON, Base, Boolean, DateTime, ForeignKey, Mapped, mapped_column, now


class TenantAIPolicy(Base):
    """One tenant's own persisted AI policy (docs/ROADMAP.md Phase 9.4).

    Resolved into `control_plane.data_authorization.TenantAIDataPolicy`
    by `product/ai/policy.py::resolve_tenant_ai_policy()` -- this table is
    the Product-owned *storage* for that already-existing typed shape,
    never a second policy model competing with it, and never a second
    authorization mechanism.
    """

    __tablename__ = "tenant_policies"
    __table_args__ = {"schema": "ai"}

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.tenants.id"), primary_key=True, nullable=False
    )
    #: A tenant-level kill switch. `False` resolves to *no* policy at all
    #: (not an empty one), so disabling is indistinguishable from never
    #: having configured one -- both deny.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    #: Bounded list of approved capability keys, every one of which must be
    #: in `product/ai/capabilities.py::PRODUCTION_CAPABILITIES`, validated
    #: at the service layer on every write.
    approved_capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: Provider names this tenant permits. Intersected with the
    #: platform-wide eligibility list by Data Authorization itself, so a
    #: tenant can only ever narrow, never widen, what the platform allows.
    allowed_providers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


__all__ = ["TenantAIPolicy"]
