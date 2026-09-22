"""ORM models for the `templates` schema (docs/ROADMAP.md Phase 14.1).

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like every other `product/*/models.py` -- this module
never imports `sqlalchemy` directly.

**`Snapshot` is the only table this phase introduces** --
`docs/ADR/0013-templates-snapshot-scope-and-crm-dependency.md`'s own
"Decision 1" section: the roadmap defines one domain concept (a named,
appliable bundle of one tenant's configuration), not a separate
Template/Snapshot pair.

**Ordinary RLS-scoped, tenant-owned data** -- `tenant_id` is the *source*
tenant a snapshot was captured from; every read/write happens with an
already-established `tenant_id`, so there is no reason to deviate from
the default RLS-scoped shape.

**Immutable from creation** -- no `updated_at` column, and
`product/templates/snapshots.py` exposes no update/delete function for
this table at all (mirrors `product/crm/pipelines.py`'s own identical
"create+read only" shape, the exact source domain this phase snapshots).
A snapshot is superseded by creating a new one, never edited in place.

**`payload` never contains an identifier of any kind** --
`docs/ADR/0013-...`'s own "Decision 2" section: export captures only
portable attribute values (names, flags, ordering), never a source-
tenant id, so there is structurally nothing in this column that could
leak a cross-tenant reference when applied elsewhere. Bounded by
`ck_templates_snapshots_payload_size` (`MAX_PAYLOAD_BYTES`) -- the same
"bounded JSON, never an unbounded blob" discipline
`product/websites/models.py::Page.content_blocks` already establishes.

**`schema_version`** is this snapshot's own payload-shape version
(`docs/ROADMAP.md` Phase 14's own "schema_version" requirement) --
independent of the application's own version or any Git SHA. `apply()`
rejects an unsupported version cleanly (`product/templates/schema.py
::SUPPORTED_SCHEMA_VERSIONS`) rather than guessing at an incompatible
payload shape.

**`included_domains`** is a closed-vocabulary list of domain keys present
in `payload` (e.g. `["crm.pipelines"]`) -- validated against
`product/templates/schema.py::SUPPORTED_DOMAINS` at write time, not
enforced by a database `CHECK` (the same "closed vocabulary, service-
layer validated" discipline this codebase already applies to
`product/websites/content_blocks.py`).
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
    mapped_column,
    now,
)

MAX_NAME_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 1000
MAX_PAYLOAD_BYTES = 262_144  # 256 KiB -- generous, still bounded; see module docstring.


class Snapshot(Base):
    """A named, immutable, point-in-time bundle of one tenant's
    supported configuration (docs/ROADMAP.md Phase 14.1). Ordinary
    RLS-scoped, tenant-owned data; see module docstring."""

    __tablename__ = "snapshots"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="ck_templates_snapshots_schema_version"),
        CheckConstraint(
            "octet_length(payload::text) <= 262144", name="ck_templates_snapshots_payload_size"
        ),
        Index("ix_templates_snapshots_tenant_id", "tenant_id"),
        {"schema": "templates"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(String(MAX_DESCRIPTION_LENGTH))
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    included_domains: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


__all__ = ["MAX_DESCRIPTION_LENGTH", "MAX_NAME_LENGTH", "MAX_PAYLOAD_BYTES", "Snapshot"]
