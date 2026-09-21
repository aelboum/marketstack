"""Product-owned exceptions for `product/reputation/` (docs/ROADMAP.md
Phase 12). Mirrors `product/websites/errors.py`'s own discipline exactly.
"""

from __future__ import annotations

import uuid


class ReputationAccessDeniedError(Exception):
    """Raised by every `product/reputation/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/reputation/permissions.py
    ::require()`, the one authorization chokepoint every mutating and read
    function here calls first, before any database access."""

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


class ReputationReferenceNotFoundError(Exception):
    """Raised when a caller-supplied review-request/review/response id (or
    a referenced contact id) does not resolve to a real, in-tenant row.
    Mapped to the same non-enumerating 404 as `ReputationAccessDeniedError`
    at the API layer -- a caller must not be able to distinguish "that id
    doesn't exist" from "it exists in another tenant" from "you can't see
    it.\""""

    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class ReputationValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an invalid rating, an unsupported channel/provider, an invalid
    lifecycle transition) -- a 400-shaped client error, never an
    authorization or lookup failure."""


class ReputationConflictError(Exception):
    """Raised for a genuine state conflict this module's own logic
    detects (e.g. a duplicate `external_review_id` for the same tenant/
    provider) -- the service-layer translation of the real,
    database-enforced `UNIQUE` constraint violation, never a race-prone
    SELECT-then-INSERT check. Mapped to `409` at the API layer."""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} {value!r} is already in use.")


class ReputationProviderNotConfiguredError(Exception):
    """Raised when an action requires posting to a real external review
    platform (`product/reputation/providers.py::resolve_provider()`) and
    no adapter is configured for that provider -- true for every
    non-`manual` provider today, by design (docs/ROADMAP.md Phase 12.2 is
    deliberately deferred; see that module's own docstring). Never
    silently no-ops -- a caller must see a clear, explicit failure, never
    a response that appears to have posted when it did not."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"no review-provider adapter is configured for {provider!r}.")


__all__ = [
    "ReputationAccessDeniedError",
    "ReputationConflictError",
    "ReputationProviderNotConfiguredError",
    "ReputationReferenceNotFoundError",
    "ReputationValidationError",
]
