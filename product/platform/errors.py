"""Product-owned exceptions for `product/platform/`.

Every SaaS-OS failure this module's functions can surface unchanged
(`TenantNotFoundError`, `TenantClosedError`, `DuplicateRoleAssignmentError`,
...) is used as-is -- mirrors `product/agency/errors.py`'s own opening
discipline exactly. This module only adds the small number of exceptions
genuinely specific to the platform-ownership boundary itself.
"""

from __future__ import annotations

import uuid


class PlatformAccessDeniedError(Exception):
    """Raised by `product.platform.authorization.require_platform_authority()`
    when `actor_user_id` does not hold `(resource, action)` at the
    bootstrapped platform tenant -- the platform-level analogue of
    `product.agency.errors.AgencyAccessDeniedError`."""

    def __init__(self, actor_user_id: uuid.UUID, *, resource: str, action: str) -> None:
        self.actor_user_id = actor_user_id
        self.resource = resource
        self.action = action
        super().__init__(
            f"{actor_user_id} is not authorized for platform action "
            f"resource={resource!r} action={action!r}."
        )


class PlatformTenantNotBootstrappedError(Exception):
    """Raised by `product.platform.provisioning.get_platform_tenant()` when
    no platform tenant has been bootstrapped yet -- `PLATFORM_TENANT_ID` is
    unset, empty, or not a valid UUID. A normal, expected state before the
    one-time bootstrap step has run; not a data-integrity fault."""

    def __init__(self) -> None:
        super().__init__(
            "no platform tenant has been bootstrapped yet -- PLATFORM_TENANT_ID "
            "is not configured. See product/platform/provisioning.py::"
            "bootstrap_platform_tenant()'s own docstring."
        )


class PlatformTenantNotRootError(Exception):
    """Raised by `product.platform.provisioning.get_platform_tenant()` when
    `PLATFORM_TENANT_ID` resolves to a real, existing tenant that is NOT a
    root tenant (`parent_id is not None`). The platform tenant must always
    be a root of the hierarchy -- a `PLATFORM_TENANT_ID` misconfigured to
    name someone else's Agency or Client tenant is a genuine configuration
    defect, deliberately NOT collapsed into `PlatformTenantNotBootstrappedError`
    (that error means "no platform tenant configured at all"; this one
    means "one is configured, and names a real tenant, but not a root
    one" -- a materially different, louder failure, mirroring
    `get_platform_tenant()`'s own existing "a dangling id is a genuine
    misconfiguration that should surface loudly" treatment of
    `core.tenancy.TenantNotFoundError`)."""

    def __init__(self, tenant_id: uuid.UUID, parent_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        self.parent_id = parent_id
        super().__init__(
            f"configured platform tenant {tenant_id} is not a root tenant "
            f"(its own parent is {parent_id}) -- PLATFORM_TENANT_ID must name a root tenant."
        )


class PlatformTenantAlreadyBootstrappedError(Exception):
    """Raised by `product.platform.provisioning.bootstrap_platform_tenant()`
    when `PLATFORM_TENANT_ID` is already configured -- this function is a
    one-time bootstrap, never a second, competing "ensure" path (see its
    own docstring for why a second platform owner is a deliberately
    separate, not-yet-built operation)."""

    def __init__(self, existing_tenant_id: uuid.UUID) -> None:
        self.existing_tenant_id = existing_tenant_id
        super().__init__(
            f"a platform tenant is already bootstrapped ({existing_tenant_id}) -- "
            "bootstrap_platform_tenant() must not be called a second time."
        )


class PlatformSelfAttachError(Exception):
    """Raised by `product.platform.provisioning.attach_agency_to_platform()`
    when `agency_tenant_id` names the platform tenant itself -- the
    platform tenant can never become its own child."""

    def __init__(self, platform_tenant_id: uuid.UUID) -> None:
        self.platform_tenant_id = platform_tenant_id
        super().__init__(
            f"{platform_tenant_id} is the platform tenant itself -- it cannot be "
            "attached to itself."
        )


class PlatformAttachTargetNotRootTenantError(Exception):
    """Raised by `product.platform.provisioning.attach_agency_to_platform()`
    when `agency_tenant_id` already has a parent other than the platform
    tenant -- e.g. it is a Client tenant (a child of some agency), not an
    Agency root itself. `attach_agency_to_platform()` moves Agency roots
    under the platform tenant only; it is deliberately NOT a general
    `move_tenant()` wrapper for arbitrary tenants, so a caller cannot use
    it to detach a Client from its Agency by mistake."""

    def __init__(self, tenant_id: uuid.UUID, current_parent_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        self.current_parent_id = current_parent_id
        super().__init__(
            f"{tenant_id} already has a parent ({current_parent_id}) that is not "
            "the platform tenant -- attach_agency_to_platform() only moves root "
            "tenants (Agencies), never a tenant that already has some other parent."
        )
