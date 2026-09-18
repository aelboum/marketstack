"""This product's own ORM models for the `foundation` schema, declared on
the installed saas-os package's shared `infra.db` base and primitives --
exactly the way saas-os/examples/reference-consumer/reference_consumer
/models.py declares its own table, so this module never imports
`sqlalchemy` directly (docs/REPOSITORY-STRATEGY.md; mirrors the proven
reference pattern). Row-Level Security on this table is established by
the migration (`infra.db.tenant_rls_statements`); this model only maps
the columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import Base, DateTime, ForeignKey, Mapped, String, mapped_column, now


class TenantSetting(Base):
    """One tenant-scoped key/value setting (docs/ROADMAP.md Phase 2.1).

    Deliberately a plain string value, not a typed-value system --
    Phase 2.1's own scope is "read/write helpers," not a settings
    schema/validation framework. A later phase needing a typed or
    structured setting stores its own JSON-encoded string here, or (if
    that becomes a recurring need) revisits this table's shape then,
    not speculatively now.
    """

    __tablename__ = "tenant_settings"
    __table_args__ = {"schema": "foundation"}

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.tenants.id"), primary_key=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )
