"""Product-owned exceptions for `product/conversations/` (docs/ROADMAP.md
Phase 5). Mirrors `product/crm/errors.py`'s own discipline exactly.
"""

from __future__ import annotations

import uuid


class ConversationAccessDeniedError(Exception):
    """Raised by every `product/conversations/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- mirrors `product.crm.errors
    .CrmAccessDeniedError` exactly; see `product/conversations/permissions
    .py::require()` and `docs/ADR/0002-...`'s Phase 4 addendum (applies
    unchanged to this module)."""

    def __init__(
        self, actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str
    ) -> None:
        self.actor_user_id = actor_user_id
        self.tenant_id = tenant_id
        self.resource = resource
        self.action = action
        super().__init__(
            f"{actor_user_id} is not authorized for {action!r} on {resource!r} "
            f"in tenant {tenant_id}."
        )


class ConversationReferenceNotFoundError(Exception):
    """Raised when a caller-supplied related-entity id (a contact, a
    thread, an assignee, a template) does not resolve to a real row this
    actor's tenant can see. Mapped to the same non-enumerating 404 as
    `ConversationAccessDeniedError` at the API layer."""

    def __init__(self, entity: str, entity_id: uuid.UUID) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class ConversationValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an unknown channel/direction, an oversized message body, a thread
    with no contact being asked to send an email). A 400-shaped client
    error, never an authorization or lookup failure."""
