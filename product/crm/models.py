"""ORM models for the `crm` schema (docs/ROADMAP.md Phase 4.1-4.3).

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like every other product table (`product/foundation/
models.py`, `product/white_label/models.py`) -- this module never imports
`sqlalchemy` directly.

**Composite-FK discipline, mirroring `core/rbac/models.py::Role`/
`MembershipRole`'s own pattern exactly**: every cross-table reference
within this schema (a contact's `company_id`, an opportunity's
`contact_id`/`company_id`/`stage_id`, a task/note's entity references) is
a `ForeignKeyConstraint(["tenant_id", "<col>_id"], ["crm.<table>.tenant_id",
"crm.<table>.id"])`, never a bare `ForeignKey` on the id column alone --
this is what makes it structurally impossible, at the database level, for
a row in one tenant to reference a row in another tenant, not merely an
application-level check that could be forgotten somewhere. Every
referenced table therefore carries its own `UniqueConstraint(tenant_id,
id)` as the composite-FK target (redundant with the primary key alone,
but required by Postgres as the exact tuple a composite FK references).

**Deletion behavior** (a deliberate, documented choice, not left
implicit): `crm.tasks`/`crm.notes` `ON DELETE CASCADE` on whichever of
their three entity-FKs is set -- a task/note has no independent meaning
without the one entity it is attached to (the `CHECK` constraint below
requires exactly one to be set; if that one entity is deleted, the row
attached to it goes too). `crm.opportunities.contact_id`/`company_id`
`ON DELETE SET NULL` -- deleting a contact/company must not destroy an
in-progress deal, only unlink it. `crm.contacts.company_id` `ON DELETE
SET NULL` -- deleting a company unlinks, never deletes, its contacts.
`crm.opportunities.pipeline_id`/`stage_id` and `crm.pipeline_stages
.pipeline_id` have no `ON DELETE` clause (the default `RESTRICT`) --
this phase ships no pipeline/stage DELETE endpoint at all (see
`product/crm/pipelines.py`'s own docstring for why), so this path is
never exercised, but `RESTRICT` is the correct, safe default should a
later phase add one without revisiting this file.

**Phase 4.4 additions** (`CustomFieldDefinition`/`CustomFieldValue`,
`Tag`/`EntityTag`) reuse the identical composite-FK and
`_exactly_one_entity_check()` discipline above -- `CustomFieldValue` and
`EntityTag` both carry the same three-nullable-composite-FK-plus-CHECK
shape as `Task`/`Note`, `ON DELETE CASCADE` on all three (a field value
or tag attachment has no independent meaning without its one entity),
plus `ON DELETE CASCADE` on their own `field_definition_id`/`tag_id`
(deleting a field definition or tag removes every value/attachment
referencing it -- no orphaned rows). `CustomFieldValue`'s own typed
`value_text`/`value_number`/`value_date`/`value_boolean` columns are
deliberately NOT constrained by a `CHECK` to "exactly one populated,
matching the definition's `field_type`" -- unlike the entity-FK triple
above, that would require a `CHECK` to read another table's row
(`field_definition_id`'s own `field_type`), which Postgres `CHECK`
constraints cannot do. This is enforced at the service layer instead
(`product/crm/custom_fields.py`), a deliberate, narrower application-level
boundary, not an oversight -- the tenant-isolation FKs remain fully
database-enforced.

**Phase 4.5 addition** (`ImportJob`) has no FK to any other `crm.*`
table -- it records a bulk-import operation's own progress/outcome, not
a business record.
"""

from __future__ import annotations

import uuid
from datetime import datetime

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
    Text,
    UniqueConstraint,
    mapped_column,
    now,
)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_companies_tenant_id_id"),
        Index("ix_crm_companies_tenant_id", "tenant_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_contacts_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_contacts_tenant_company",
            ondelete="SET NULL",
        ),
        Index("ix_crm_contacts_tenant_id", "tenant_id"),
        Index("ix_crm_contacts_company_id", "company_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_pipelines_tenant_id_id"),
        Index("ix_crm_pipelines_tenant_id", "tenant_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_pipeline_stages_tenant_id_id"),
        UniqueConstraint(
            "pipeline_id", "position", name="uq_crm_pipeline_stages_pipeline_position"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "pipeline_id"],
            ["crm.pipelines.tenant_id", "crm.pipelines.id"],
            name="fk_crm_pipeline_stages_tenant_pipeline",
        ),
        CheckConstraint("NOT (is_won AND is_lost)", name="ck_crm_pipeline_stages_not_won_and_lost"),
        Index("ix_crm_pipeline_stages_tenant_id", "tenant_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_won: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_opportunities_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_crm_opportunities_tenant_contact",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_opportunities_tenant_company",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "pipeline_id"],
            ["crm.pipelines.tenant_id", "crm.pipelines.id"],
            name="fk_crm_opportunities_tenant_pipeline",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "stage_id"],
            ["crm.pipeline_stages.tenant_id", "crm.pipeline_stages.id"],
            name="fk_crm_opportunities_tenant_stage",
        ),
        CheckConstraint(
            "(amount_minor_units IS NULL) = (amount_currency IS NULL)",
            name="ck_crm_opportunities_amount_both_or_neither",
        ),
        Index("ix_crm_opportunities_tenant_id", "tenant_id"),
        Index("ix_crm_opportunities_contact_id", "contact_id"),
        Index("ix_crm_opportunities_company_id", "company_id"),
        Index("ix_crm_opportunities_stage_id", "stage_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    amount_minor_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


ENTITY_TYPE_CONTACT = "contact"
ENTITY_TYPE_COMPANY = "company"
ENTITY_TYPE_OPPORTUNITY = "opportunity"

FIELD_TYPE_TEXT = "text"
FIELD_TYPE_NUMBER = "number"
FIELD_TYPE_DATE = "date"
FIELD_TYPE_BOOLEAN = "boolean"


def _exactly_one_entity_check(name: str) -> CheckConstraint:
    return CheckConstraint(
        "(CASE WHEN contact_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN company_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN opportunity_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
        name=name,
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_tasks_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_crm_tasks_tenant_contact",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_tasks_tenant_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["crm.opportunities.tenant_id", "crm.opportunities.id"],
            name="fk_crm_tasks_tenant_opportunity",
            ondelete="CASCADE",
        ),
        _exactly_one_entity_check("ck_crm_tasks_exactly_one_entity"),
        Index("ix_crm_tasks_tenant_id", "tenant_id"),
        Index("ix_crm_tasks_contact_id", "contact_id"),
        Index("ix_crm_tasks_company_id", "company_id"),
        Index("ix_crm_tasks_opportunity_id", "opportunity_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_notes_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_crm_notes_tenant_contact",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_notes_tenant_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["crm.opportunities.tenant_id", "crm.opportunities.id"],
            name="fk_crm_notes_tenant_opportunity",
            ondelete="CASCADE",
        ),
        _exactly_one_entity_check("ck_crm_notes_exactly_one_entity"),
        Index("ix_crm_notes_tenant_id", "tenant_id"),
        Index("ix_crm_notes_contact_id", "contact_id"),
        Index("ix_crm_notes_company_id", "company_id"),
        Index("ix_crm_notes_opportunity_id", "opportunity_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_custom_field_definitions_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "name",
            name="uq_crm_custom_field_definitions_tenant_entity_name",
        ),
        Index("ix_crm_custom_field_definitions_tenant_id", "tenant_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_custom_field_values_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "field_definition_id",
            "contact_id",
            "company_id",
            "opportunity_id",
            name="uq_crm_custom_field_values_one_per_entity",
            # NULLS NOT DISTINCT (Postgres 16): without this, standard SQL
            # NULL != NULL semantics mean this constraint would silently
            # never fire -- company_id/opportunity_id are always NULL for
            # every row (exactly one of the three entity FKs is ever set),
            # so two rows for the same (tenant, definition, contact) would
            # otherwise never be considered duplicates. Verified by a
            # dedicated test (tests/crm/test_custom_fields_and_tags_integration.py)
            # that failed before this was added.
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "field_definition_id"],
            ["crm.custom_field_definitions.tenant_id", "crm.custom_field_definitions.id"],
            name="fk_crm_custom_field_values_tenant_definition",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_crm_custom_field_values_tenant_contact",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_custom_field_values_tenant_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["crm.opportunities.tenant_id", "crm.opportunities.id"],
            name="fk_crm_custom_field_values_tenant_opportunity",
            ondelete="CASCADE",
        ),
        _exactly_one_entity_check("ck_crm_custom_field_values_exactly_one_entity"),
        Index("ix_crm_custom_field_values_tenant_id", "tenant_id"),
        Index("ix_crm_custom_field_values_contact_id", "contact_id"),
        Index("ix_crm_custom_field_values_company_id", "company_id"),
        Index("ix_crm_custom_field_values_opportunity_id", "opportunity_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    field_definition_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    # DateTime, not a true Date -- infra.db's curated re-export surface does
    # not expose sqlalchemy.Date (product code never imports sqlalchemy
    # directly, per this module's own established discipline); a date-typed
    # custom field's value is stored at UTC midnight and treated as
    # date-only by the service layer (product/crm/custom_fields.py).
    value_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_tags_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_crm_tags_tenant_name"),
        Index("ix_crm_tags_tenant_id", "tenant_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class EntityTag(Base):
    __tablename__ = "entity_tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_entity_tags_tenant_id_id"),
        UniqueConstraint(
            "tag_id",
            "contact_id",
            "company_id",
            "opportunity_id",
            name="uq_crm_entity_tags_tag_per_entity",
            # NULLS NOT DISTINCT -- see the identical note on
            # CustomFieldValue's own uq_crm_custom_field_values_one_per_entity
            # above; the same NULL-column subtlety applies here.
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tag_id"],
            ["crm.tags.tenant_id", "crm.tags.id"],
            name="fk_crm_entity_tags_tenant_tag",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_crm_entity_tags_tenant_contact",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            ["crm.companies.tenant_id", "crm.companies.id"],
            name="fk_crm_entity_tags_tenant_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["crm.opportunities.tenant_id", "crm.opportunities.id"],
            name="fk_crm_entity_tags_tenant_opportunity",
            ondelete="CASCADE",
        ),
        _exactly_one_entity_check("ck_crm_entity_tags_exactly_one_entity"),
        Index("ix_crm_entity_tags_tenant_id", "tenant_id"),
        Index("ix_crm_entity_tags_tag_id", "tag_id"),
        Index("ix_crm_entity_tags_contact_id", "contact_id"),
        Index("ix_crm_entity_tags_company_id", "company_id"),
        Index("ix_crm_entity_tags_opportunity_id", "opportunity_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    tag_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


_IMPORT_JOB_STATUSES = ("pending", "running", "completed", "failed")


class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_import_jobs_tenant_id_id"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_crm_import_jobs_status",
        ),
        Index("ix_crm_import_jobs_tenant_id", "tenant_id"),
        {"schema": "crm"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    total_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    succeeded_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
