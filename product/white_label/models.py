"""This product's own ORM models for the `white_label` schema
(docs/WHITE-LABEL.md sections 2-3; docs/ROADMAP.md Phase 2.3/2.4).
Declared on the installed saas-os package's shared `infra.db` base and
primitives, mirroring saas-os/examples/reference-consumer's own pattern
exactly. Row-Level Security on both tables is established by their own
migrations.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import Base, DateTime, ForeignKey, Mapped, String, Text, mapped_column, now


class TenantBranding(Base):
    """One row per tenant that has customized branding (docs/WHITE-LABEL
    .md section 1: absence means "inherit from parent"). A deliberately
    fixed, generous set of columns -- not an open-ended theme editor
    (docs/WHITE-LABEL.md section 5's own explicit out-of-scope note).

    `logo_asset_ref`/`favicon_asset_ref` are bare string references
    (e.g. a future object-storage key or an external URL) -- this phase
    does not build any object-storage/upload mechanism (no such
    subphase exists in docs/ROADMAP.md Phase 2; deferred to whichever
    future phase first needs one, per docs/RESPONSIBILITY-MATRIX.md's
    "Object/file storage" row)."""

    __tablename__ = "tenant_branding"
    __table_args__ = {"schema": "white_label"}

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.tenants.id"), primary_key=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_asset_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    favicon_asset_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    color_primary: Mapped[str | None] = mapped_column(String(32), nullable=True)
    color_secondary: Mapped[str | None] = mapped_column(String(32), nullable=True)
    color_accent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    typography: Mapped[str | None] = mapped_column(String(255), nullable=True)
    login_branding_overrides: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    support_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_terms_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    legal_privacy_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class TenantDomain(Base):
    """One row per custom domain mapped to a tenant (docs/WHITE-LABEL.md
    section 3). `domain` is the primary key -- a domain maps to exactly
    one tenant, and a lookup is always by domain, never reverse. TLS
    certificate provisioning is an external/operational concern
    (docs/WHITE-LABEL.md section 3: "an external integration concern")
    -- `tls_status` here is metadata only (e.g. "pending"/"issued"/
    "failed"), never a certificate or key material itself.

    **Deliberately NOT Row-Level-Security-scoped** -- this table must be
    readable *before* a tenant context exists at all (the whole point of
    a domain lookup is to discover which tenant a request belongs to),
    so it cannot be read through `infra.db.tenant_session_scope(tenant_id)`,
    which requires already knowing `tenant_id`. This mirrors
    `core.tenancy.TenantAncestry`'s own documented precedent exactly
    (its own docstring: "not RLS-scoped... read directly... untenanted")
    -- read via plain `infra.db.session_scope()` (see
    `product/white_label/domains.py::resolve_tenant_for_domain`), never
    `tenant_session_scope()`."""

    __tablename__ = "tenant_domains"
    __table_args__ = {"schema": "white_label"}

    domain: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    tls_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
