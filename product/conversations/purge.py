"""Tenant purge participant for the `conversations` schema (mirrors
`product/crm/purge.py`'s proven consolidated-participant pattern).
Registered from `product/api/main.py::create_app()`.

One consolidated participant for all three `conversations.*` tables --
`messages` references `threads`, so deletion order matters (children
before parents), the identical reasoning `product/crm/purge.py`'s own
docstring already gives for its own twelve tables. `message_templates`
has no FK to any other table in this schema and can be purged in any
position.
"""

from __future__ import annotations

import uuid

from core.tenancy.purge_participants import (
    DuplicateTenantPurgeParticipantError,
    TenantPurgeParticipantRegistry,
    default_registry,
)
from infra.db import select, tenant_session_scope

from product.conversations.models import ConversationMessage, ConversationThread, MessageTemplate

_PURGE_ORDER = (ConversationMessage, ConversationThread, MessageTemplate)


class ConversationsDataPurgeParticipant:
    """Deletes every `conversations.*` row belonging to the tenant being
    purged, in dependency order. Idempotent -- a second call finds
    nothing left and deletes zero rows, never an error."""

    @property
    def name(self) -> str:
        return "conversations.*"

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
        active_registry.register(ConversationsDataPurgeParticipant())
    except DuplicateTenantPurgeParticipantError:
        if not any(
            isinstance(p, ConversationsDataPurgeParticipant) for p in active_registry.list()
        ):  # pragma: no cover -- would mean a *different* type reused this name
            raise
