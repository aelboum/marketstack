"""Product-owned exceptions for `product/appointments/` (docs/ROADMAP.md
Phase 7). Mirrors `product/crm/errors.py`/`product/marketing/errors.py`'s
own discipline exactly.
"""

from __future__ import annotations

import uuid


class AppointmentAccessDeniedError(Exception):
    """Raised by every `product/appointments/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/appointments/permissions.py
    ::require()` and `docs/ADR/0002-...`'s Phase 4 addendum for why this
    check exists in the product's own service layer rather than at the
    ingress layer."""

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


class AppointmentReferenceNotFoundError(Exception):
    """Raised when a caller-supplied related-entity id (a calendar,
    availability rule, appointment, or the assignee `owner_user_id` for a
    calendar) does not resolve to a real, in-tenant row. Mapped to the
    same non-enumerating 404 as `AppointmentAccessDeniedError` at the API
    layer."""

    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class AppointmentValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an unknown/invalid timezone identifier, an invalid day_of_week or
    time range, an invalid status transition, an oversized date-range
    query) -- a 400-shaped client error, never an authorization or lookup
    failure."""


class AppointmentSlotUnavailableError(Exception):
    """Raised when a booking/reschedule attempt collides with an existing
    `'confirmed'` appointment on the same calendar -- the service-layer
    translation of the real, database-enforced `EXCLUDE` constraint
    violation (`product/appointments/models.py`'s own module docstring).
    Never a raw `IntegrityError`/psycopg exception reaches a caller."""

    def __init__(self, calendar_id: uuid.UUID) -> None:
        self.calendar_id = calendar_id
        super().__init__(f"the requested slot on calendar {calendar_id} is no longer available.")


class AppointmentTokenInvalidError(Exception):
    """Raised for an unknown/malformed public `link_token` (booking) or
    `manage_token` (reschedule/cancel) -- deliberately its own type,
    mirroring `product/marketing/errors.py::MarketingFormTokenInvalidError`'s
    own reasoning: the public routes map this to the identical
    non-enumerating 404 shape every other lookup failure in this product
    uses, but keeping it separate makes clear at the call site that this
    is a public, unauthenticated lookup path."""
