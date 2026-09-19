"""Tenant purge participant for the `crm` schema (mirrors
saas-os/examples/reference-consumer/reference_consumer/purge.py's proven
pattern). Registered from `product/api/main.py::create_app()`.

**One consolidated participant for all twelve `crm.*` tables, not twelve
separate ones** -- unlike `product/foundation`/`product/white_label`
(whose tables have no cross-table foreign keys between them),
`crm.tasks`/`crm.notes`/`crm.custom_field_values`/`crm.entity_tags`
reference `crm.opportunities`/`crm.contacts`/`crm.companies`, which
reference `crm.pipeline_stages`/`crm.pipelines`, and
`crm.custom_field_values`/`crm.entity_tags` additionally reference
`crm.custom_field_definitions`/`crm.tags`.
`core.tenancy.purge_participants.TenantPurgeParticipantRegistry` does not
document a guaranteed execution order between separately-registered
participants, so deletion order within this one module is handled
explicitly, in a single `purge_tenant_data()` call, children before
parents -- correct regardless of what `ON DELETE` behavior each
individual FK happens to carry (every cross-table FK here is in fact
`ON DELETE CASCADE`, so Postgres itself would clean up a child row the
instant its parent is deleted even without this explicit ordering; the
explicit order is kept anyway so this participant's own correctness does
not silently depend on that DB-level detail continuing to hold), and not
dependent on inter-participant ordering this registry does not promise.
`crm.import_jobs` has no FK to any other `crm.*` table -- it can be
purged in any position.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.crm.models import (
    Company,
    Contact,
    CustomFieldDefinition,
    CustomFieldValue,
    EntityTag,
    ImportJob,
    Note,
    Opportunity,
    Pipeline,
    PipelineStage,
    Tag,
    Task,
)

_PURGE_ORDER = (
    Task,
    Note,
    CustomFieldValue,
    EntityTag,
    ImportJob,
    Opportunity,
    Contact,
    PipelineStage,
    Company,
    Pipeline,
    CustomFieldDefinition,
    Tag,
)


class CrmDataPurgeParticipant:
    """Deletes every `crm.*` row belonging to the tenant being purged,
    in dependency order. Idempotent -- a second call finds nothing left
    in any table and deletes zero rows, never an error."""

    @property
    def name(self) -> str:
        return "crm.*"

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> None:
        with tenant_session_scope(tenant_id) as session:
            for model in _PURGE_ORDER:
                rows = (
                    session.execute(
                        select(model).where(model.tenant_id == tenant_id).with_for_update()
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    session.delete(row)
                session.flush()


def register(registry: TenantPurgeParticipantRegistry | None = None) -> None:
    """See reference_consumer/purge.py::register()'s own docstring for
    the re-registration/idempotency reasoning."""
    active_registry = registry if registry is not None else default_registry()
    try:
        active_registry.register(CrmDataPurgeParticipant())
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, CrmDataPurgeParticipant) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise
