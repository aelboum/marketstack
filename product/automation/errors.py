"""Product-owned exceptions for `product/automation/` (docs/ROADMAP.md
Phase 10.2). Mirrors `product/telephony/errors.py`'s own discipline.
"""

from __future__ import annotations

import uuid


class AutomationAccessDeniedError(Exception):
    """Raised when `actor_user_id` does not hold the required
    `(resource, action)` capability at `tenant_id` -- gates the workflow
    CRUD API. Never used to gate *execution* -- see
    `product/automation/actions.py`'s own module docstring for why
    execution authorization is delegated entirely to the underlying CRM
    function each action calls."""

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


class AutomationReferenceNotFoundError(Exception):
    """Raised when a caller-supplied workflow id does not resolve to a
    real, in-tenant row."""

    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class AutomationValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an unknown trigger/action type, an oversized config, a malformed
    condition) -- a 400-shaped client error."""


class AutomationConditionError(ValueError):
    """Raised when a condition definition itself is malformed (unknown
    operator, non-comparable types) -- distinct from
    `AutomationValidationError` so callers can tell "bad workflow
    definition" apart from "bad API request shape" if they ever need to."""


class AutomationActionError(RuntimeError):
    """Raised when an action's own execution fails (the underlying CRM
    call raised, the webhook target refused/timed out) -- never a raw
    exception from the underlying call; normalized here mirroring every
    other provider-error discipline in this codebase."""
