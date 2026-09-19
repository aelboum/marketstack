"""Product-owned exceptions for `product/marketing/` (docs/ROADMAP.md
Phase 6). Mirrors `product/crm/errors.py`/`product/conversations
/errors.py`'s own discipline exactly.
"""

from __future__ import annotations

import uuid


class MarketingAccessDeniedError(Exception):
    """Raised by every `product/marketing/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/marketing/permissions.py
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


class MarketingReferenceNotFoundError(Exception):
    """Raised when a caller-supplied related-entity id (a campaign,
    recipient, suppression, or a CRM contact/tag/custom-field-definition
    referenced from a segment query) does not resolve to a real row in
    the acting tenant. Mapped to the same non-enumerating 404 as
    `MarketingAccessDeniedError` at the API layer."""

    def __init__(self, entity: str, entity_id: uuid.UUID) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class MarketingValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (e.g. an unknown channel, a campaign not in `draft` status when an
    operation requires it, a malformed `segment_query`) -- a 400-shaped
    client error, never an authorization or lookup failure."""


class MarketingFormTokenInvalidError(Exception):
    """Raised by `product/marketing/forms.py::submit_form()` for an
    unknown/malformed `form_token`. Deliberately its own type, distinct
    from `MarketingReferenceNotFoundError` -- the public submission route
    maps this to the identical non-enumerating 404 shape every other
    lookup failure in this product uses, but keeping it separate makes
    clear at the call site that this is the one public, unauthenticated
    lookup path, not an authenticated caller referencing a wrong id."""
