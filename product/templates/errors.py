"""Product-owned exceptions for `product/templates/` (docs/ROADMAP.md
Phase 14). Mirrors `product/reputation/errors.py`'s own discipline
exactly. SaaS-OS's own errors, and `product.crm`'s own errors
(`CrmReferenceNotFoundError`, `CrmAccessDeniedError`), are used unchanged
wherever they propagate from a `product.crm.pipelines` call this module
makes -- this module only adds exceptions genuinely specific to its own
snapshot capture/apply logic.
"""

from __future__ import annotations

import uuid


class TemplatesAccessDeniedError(Exception):
    """Raised by every `product/templates/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/templates/permissions.py
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


class SnapshotNotFoundError(Exception):
    """Raised when a caller-supplied snapshot id does not resolve to a
    real, in-tenant row. Mapped to the same non-enumerating 404 as
    `TemplatesAccessDeniedError` at the API layer -- a caller must not be
    able to distinguish "that id doesn't exist" from "it exists in
    another tenant" from "you can't see it.\""""

    def __init__(self, snapshot_id: object) -> None:
        self.snapshot_id = snapshot_id
        super().__init__(f"snapshot {snapshot_id} not found in this tenant.")


class TemplatesValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an empty/unsupported domain list, an unsupported `schema_version`, an
    oversized payload) -- a 400-shaped client error, never an
    authorization or lookup failure."""


class SnapshotApplyError(Exception):
    """Raised when applying a snapshot fails partway through
    (docs/ADR/0013-...'s own "Decision 3" section: a genuine
    infrastructure-level failure after all upfront validation already
    passed). Carries only a bounded, non-sensitive reason -- never a raw
    underlying exception's full text, which could echo internal detail."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"applying the snapshot failed: {reason}")


__all__ = [
    "SnapshotApplyError",
    "SnapshotNotFoundError",
    "TemplatesAccessDeniedError",
    "TemplatesValidationError",
]
