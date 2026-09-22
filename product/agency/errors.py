"""Product-owned exceptions for `product/agency/`.

Every authorization/lookup failure that SaaS-OS's own `core.*` functions
already raise (`TenantNotFoundError`, `RoleAssignmentNotAuthorizedError`,
`InvitationNotAuthorizedError`, `DelegationNotAuthorizedError`,
`DenyNotAuthorizedError`, `SupportAccessNotAuthorizedError`,
`TenantClosedError`, `TenantInaccessibleError`) is used unchanged -- this
module only adds the small number of exceptions genuinely specific to
this product's own additional checks, never a parallel copy of a
SaaS-OS error type.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from product.agency.provisioning import Client


class AgencyAccessDeniedError(Exception):
    """Raised by `product.agency.provisioning.provision_client()` (and
    `list_clients()`) when `actor_user_id` does not hold this product's
    own `(resource="agency.client", action=...)` capability at
    `agency_tenant_id` -- see `docs/ADR/0002-agency-cross-tenant-route-
    authorization.md` and `product/agency/provisioning.py`'s own
    docstring for why this check exists at all: `core.tenancy
    .create_tenant()` performs no authorization check of its own, so
    this product must supply one before calling it."""

    def __init__(self, actor_user_id: uuid.UUID, agency_tenant_id: uuid.UUID) -> None:
        self.actor_user_id = actor_user_id
        self.agency_tenant_id = agency_tenant_id
        super().__init__(
            f"{actor_user_id} is not authorized to manage clients under agency tenant "
            f"{agency_tenant_id}."
        )


class ClientProvisioningSetupFailedError(Exception):
    """Raised by `product.agency.provisioning.provision_client()`
    (docs/ROADMAP.md Phase 21) when the client tenant itself was created
    successfully but applying the chosen business-setup snapshot failed.
    Carries the already-created `client` so a caller can represent this
    honestly as a partial result -- "the client exists and is usable, the
    chosen setup was not applied" -- rather than receiving a bare
    `templates.errors.SnapshotApplyError`/`SnapshotNotFoundError`/
    `TemplatesAccessDeniedError` with no way to know the tenant exists.
    `reason` is always a bounded exception-class name, never a raw
    message, mirroring `SnapshotApplyError`'s own "never echo internal
    detail" discipline."""

    def __init__(self, client: Client, reason: str) -> None:
        self.client = client
        self.reason = reason
        super().__init__(
            f"client {client.tenant_id} was created but applying the chosen "
            f"business setup failed: {reason}."
        )


class UnknownDelegatablePermissionError(Exception):
    """Raised by `product.agency.delegation` when a caller names a
    `(resource, action)` pair that is not already a real, registered
    `core.rbac` permission. A delegator may only delegate a permission
    that already exists -- this function never conjures a new one on a
    caller's say-so (mass-assignment-adjacent risk: an arbitrary
    caller-supplied resource/action pair must never silently become a
    new capability)."""

    def __init__(self, resource: str, action: str) -> None:
        self.resource = resource
        self.action = action
        super().__init__(f"No registered permission for resource={resource!r} action={action!r}.")
