"""Product-owned exceptions for `product/approvals/` (docs/ROADMAP.md
Phase 29). SaaS-OS's own `control_plane.approvals` errors
(`ApprovalRequestNotFoundError`, `ApprovalNotPendingError`,
`SelfApprovalNotAllowedError`) are used unchanged wherever they propagate
from a `control_plane.approvals` call this module makes -- this module
only adds the one exception genuinely specific to its own authorization
gate (`control_plane.approvals` itself performs no `core.rbac.can()`
check at all -- see `product/approvals/__init__.py`'s own module
docstring)."""

from __future__ import annotations

import uuid


class ApprovalAccessDeniedError(Exception):
    """Raised by `product/approvals/permissions.py::require()` when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id`. Mapped to the same non-enumerating 404
    `product/approvals/routes.py` uses for
    `control_plane.approvals.ApprovalRequestNotFoundError` -- a caller
    must not be able to distinguish "that approval doesn't exist" from
    "it exists in another tenant" from "you can't see it.\""""

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


__all__ = ["ApprovalAccessDeniedError"]
