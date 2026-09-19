"""Product-owned exceptions for `product/crm/` (docs/ROADMAP.md Phase 4).

Mirrors `product/agency/errors.py`'s own discipline: SaaS-OS's own error
types (`TenantNotFoundError`, etc.) are used unchanged wherever they
apply; this module only adds exceptions genuinely specific to this
product's own CRM authorization/integrity checks.
"""

from __future__ import annotations

import uuid


class CrmAccessDeniedError(Exception):
    """Raised by every `product/crm/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/crm/permissions.py::require()`
    and `docs/ADR/0002-...`'s Phase 4 addendum for why this check exists
    in the product's own service layer rather than at the ingress layer."""

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


class CrmReferenceNotFoundError(Exception):
    """Raised when a caller-supplied related-entity id (a contact/company/
    pipeline/stage referenced from another entity) does not resolve to a
    real row in the acting tenant -- e.g. creating an opportunity with a
    `stage_id` that does not exist, or belongs to a different tenant's
    pipeline. Mapped to the same non-enumerating 404 as
    `CrmAccessDeniedError` at the API layer -- a caller must not be able
    to distinguish "that id doesn't exist" from "it exists in another
    tenant" from "you can't see it.\""""

    def __init__(self, entity: str, entity_id: uuid.UUID) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class CrmValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (e.g. an attachment reference specifying zero or more than one of
    contact/company/opportunity) -- a 400-shaped client error, never an
    authorization or lookup failure."""
