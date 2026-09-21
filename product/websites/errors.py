"""Product-owned exceptions for `product/websites/` (docs/ROADMAP.md
Phase 11.1). Mirrors `product/appointments/errors.py`'s own discipline
exactly.
"""

from __future__ import annotations

import uuid


class WebsiteAccessDeniedError(Exception):
    """Raised by every `product/websites/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/websites/permissions.py
    ::require()`, the one authorization chokepoint every mutating and
    read function here calls first, before any database access."""

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


class WebsiteReferenceNotFoundError(Exception):
    """Raised when a caller-supplied website/page id does not resolve to
    a real, in-tenant row. Mapped to the same non-enumerating 404 as
    `WebsiteAccessDeniedError` at the API layer -- a caller must not be
    able to distinguish "that id doesn't exist" from "it exists in
    another tenant" from "you can't see it.\""""

    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class WebsiteValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an invalid/oversized slug, a malformed content block, an unsafe
    link URL, an invalid lifecycle transition) -- a 400-shaped client
    error, never an authorization or lookup failure."""


class WebsiteSlugTakenError(Exception):
    """Raised when a website slug or custom domain is already in use --
    the service-layer translation of the real, database-enforced
    `UNIQUE` constraint violation (`product/websites/models.py::Website`),
    never a race-prone SELECT-then-INSERT check. Deliberately its own
    type, distinct from `WebsiteValidationError` (a shape problem) and
    `WebsiteReferenceNotFoundError` (a lookup problem) -- this is neither,
    it is a genuine conflict, mapped to `409` at the API layer."""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} {value!r} is already in use.")


__all__ = [
    "WebsiteAccessDeniedError",
    "WebsiteReferenceNotFoundError",
    "WebsiteSlugTakenError",
    "WebsiteValidationError",
]
