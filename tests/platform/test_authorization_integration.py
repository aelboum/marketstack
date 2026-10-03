"""Integration tests for product/platform/authorization.py. Marked
`integration`, excluded from the default `pytest` run.

Covers docs/ROADMAP.md Phase 31's own security requirements: platform-owner
authorization is real and deterministic; the platform layer's mere
existence grants nothing extra to, or takes nothing away from, existing
Agency -> Client isolation; explicit deny still overrides an otherwise-
valid platform-owner role; and the foundation genuinely generalizes to a
future descendant with zero further code change.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from core.authority import SystemAuthority, SystemCaller, UserCaller
from core.identity.models import User
from core.rbac import (
    RoleScope,
    can,
    create_deny,
    get_role_permission,
    grant_permission,
    register_permission,
)
from core.tenancy import TenantStatus, create_tenant, transition_tenant_status
from product.agency.provisioning import provision_agency, provision_client
from product.platform.authorization import has_platform_authority, require_platform_authority
from product.platform.errors import PlatformAccessDeniedError
from product.platform.provisioning import (
    PLATFORM_TENANT_ID_ENV_VAR,
    PlatformTenant,
    attach_agency_to_platform,
    bootstrap_platform_tenant,
)
from product.platform.roles import PLATFORM_ADMINISTRATION_RESOURCE, get_platform_owner_role

from tests.platform._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[User, PlatformTenant]]:
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    owner = make_user()
    platform_tenant = bootstrap_platform_tenant(owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform_tenant.tenant_id))
    try:
        yield owner, platform_tenant
    finally:
        cleanup_tenant_tree(platform_tenant.tenant_id)
        cleanup_users(owner.id)


def test_platform_owner_has_platform_authority(platform: tuple[User, PlatformTenant]) -> None:
    owner, _platform_tenant = platform
    assert has_platform_authority(owner.id, action="read")
    assert has_platform_authority(owner.id, action="administer")
    require_platform_authority(owner.id, action="read")  # does not raise


def test_unrelated_user_has_no_platform_authority(platform: tuple[User, PlatformTenant]) -> None:
    """Unauthorized platform access is denied, deterministically."""
    _owner, _platform_tenant = platform
    stranger = make_user()
    try:
        assert not has_platform_authority(stranger.id, action="read")
        with pytest.raises(PlatformAccessDeniedError):
            require_platform_authority(stranger.id, action="read")
    finally:
        cleanup_users(stranger.id)


def test_agency_owner_does_not_gain_platform_authority(
    platform: tuple[User, PlatformTenant],
) -> None:
    """Agency isolation: an agency owner has zero relationship to the
    platform tenant -- the platform layer's mere existence grants nothing
    extra (Phase 31's own "one agency cannot gain platform-owner
    privileges" requirement)."""
    _owner, _platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        assert not has_platform_authority(agency_owner.id, action="read")
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(agency_owner.id)


def test_platform_owner_cannot_reach_an_existing_unrelated_agency(
    platform: tuple[User, PlatformTenant],
) -> None:
    """The mirror case: bootstrapping a platform tenant grants its owner
    no reach into any pre-existing agency -- the platform tenant's own
    subtree contains nothing but itself until a future, separately-scoped
    phase deliberately places a tenant under it."""
    owner, _platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        assert not can(
            actor_id=owner.id,
            tenant_id=agency.tenant_id,
            action="read",
            resource=PLATFORM_ADMINISTRATION_RESOURCE,
        )
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(agency_owner.id)


def test_sibling_agencies_remain_isolated_under_the_platform_layer(
    platform: tuple[User, PlatformTenant],
) -> None:
    """Regression, re-verified here: the platform layer's mere existence
    changes nothing about agency-to-agency isolation."""
    _owner, _platform_tenant = platform
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    try:
        assert not can(
            actor_id=owner_a.id,
            tenant_id=agency_b.tenant_id,
            action="read",
            resource=PLATFORM_ADMINISTRATION_RESOURCE,
        )
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_platform_owner_subtree_reaches_a_tenant_placed_under_the_platform_tenant(
    platform: tuple[User, PlatformTenant],
) -> None:
    """Proves the foundation generalizes with zero further code change
    (Phase 31 requirement 10): a plain tenant made a child of the platform
    tenant is reached by the platform owner's existing SUBTREE role
    immediately, exactly like product.agency's own SUBTREE role already
    reaches a newly-created client with no further grant
    (tests/agency/test_provisioning_integration.py
    ::test_subtree_role_reaches_a_client_created_after_the_role_was_assigned).
    This tenant is created directly via core.tenancy, never through
    product.agency -- no existing agency is touched, and this is not a
    reparenting of anything that already existed."""
    owner, platform_tenant = platform
    child = create_tenant(_name("future-descendant"), parent_id=platform_tenant.tenant_id)
    transition_tenant_status(child.id, TenantStatus.ACTIVE)
    try:
        assert can(
            actor_id=owner.id,
            tenant_id=child.id,
            action="read",
            resource=PLATFORM_ADMINISTRATION_RESOURCE,
        )
    finally:
        # Leaf (child) before root (platform tenant) -- the fixture's own
        # teardown repeats the platform tenant id afterward, a harmless
        # no-op second pass (cleanup_tenant_tree() deletes by id).
        cleanup_tenant_tree(child.id, platform_tenant.tenant_id)


def test_explicit_deny_still_overrides_platform_owner_authority(
    platform: tuple[User, PlatformTenant],
) -> None:
    """Verifies this module's own authorization gate does not bypass
    core.rbac's explicit-deny mechanism (Phase 31's own "existing
    authorization... explicit deny" requirement) -- has_platform_authority()
    delegates entirely to can(), which checks deny before any allow path.

    `product.platform` deliberately grants no `deny_grant` capability to
    the `platform_owner` role itself (`product/platform/roles.py`'s own
    documented scope limit) -- this test exercises `core.rbac.create_deny()`
    directly, exactly as a test fixture for any other module's deny
    scenario would, to prove the underlying mechanism this module relies
    on is genuinely consulted, not merely assumed."""
    owner, platform_tenant = platform
    role = get_platform_owner_role(platform_tenant.tenant_id)
    assert role is not None

    # Test-only elevation via core.rbac primitives (no product.platform
    # code change) so create_deny()'s own grantor-authorization check
    # passes.
    deny_grant_create = register_permission("deny_grant", "create")
    if get_role_permission(platform_tenant.tenant_id, role.id, deny_grant_create.id) is None:
        grant_permission(
            platform_tenant.tenant_id,
            role.id,
            deny_grant_create.id,
            caller=SystemCaller(SystemAuthority.PROVISIONING),
        )

    administration_read = register_permission(PLATFORM_ADMINISTRATION_RESOURCE, "read")
    assert has_platform_authority(owner.id, action="read")

    create_deny(
        caller=UserCaller(owner.id),
        principal_user_id=owner.id,
        tenant_id=platform_tenant.tenant_id,
        scope_mode=RoleScope.SELF,
        permission_id=administration_read.id,
    )

    assert not has_platform_authority(owner.id, action="read")
    with pytest.raises(PlatformAccessDeniedError):
        require_platform_authority(owner.id, action="read")
    # A different action, not named by the deny, is unaffected -- the deny
    # is exact, not a blanket revocation of the whole role.
    assert has_platform_authority(owner.id, action="administer")


# --- Phase 31 completion: Platform -> Agency -> Client ownership relationship ----
#
# `attach_agency_to_platform()` is the mechanism `product/platform/provisioning.py`
# adds to make an Agency (and every Client beneath it) a genuine descendant
# of the platform tenant, and `has_platform_authority()`'s new `tenant_id`
# parameter is what lets a caller actually ask the question against that
# descendant instead of only the platform tenant itself. The tests above
# this line prove the *pre*-attachment isolation guarantees (unchanged);
# the tests below prove the *post*-attachment relationship is real,
# bounded, and does not leak in either direction.


def test_platform_owner_reaches_agency_after_attachment(
    platform: tuple[User, PlatformTenant],
) -> None:
    owner, platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        assert not has_platform_authority(owner.id, action="read", tenant_id=agency.tenant_id)

        attach_agency_to_platform(owner.id, agency.tenant_id)

        assert has_platform_authority(owner.id, action="read", tenant_id=agency.tenant_id)
        assert has_platform_authority(owner.id, action="administer", tenant_id=agency.tenant_id)
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(agency_owner.id)


def test_platform_owner_reaches_client_under_an_attached_agency(
    platform: tuple[User, PlatformTenant],
) -> None:
    owner, platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    try:
        assert not has_platform_authority(owner.id, action="read", tenant_id=client.tenant_id)

        attach_agency_to_platform(owner.id, agency.tenant_id)

        # No further grant anywhere -- the client was already beneath the
        # agency before it was attached, and can()'s SUBTREE walk now
        # reaches it transitively (platform -> agency -> client).
        assert has_platform_authority(owner.id, action="read", tenant_id=client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(agency_owner.id)


def test_agency_owner_does_not_gain_platform_authority_after_attachment(
    platform: tuple[User, PlatformTenant],
) -> None:
    """Attachment is one-directional: the agency owner's own role lives at
    the agency tenant, a *descendant* of the platform tenant now -- `can()`
    only walks a target tenant's ancestors upward, so the agency owner
    gains no reach toward the platform tenant (or any sibling agency) by
    virtue of the platform tenant becoming an ancestor of their own."""
    owner, platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        attach_agency_to_platform(owner.id, agency.tenant_id)

        assert not has_platform_authority(agency_owner.id, action="read")
        assert not has_platform_authority(
            agency_owner.id, action="read", tenant_id=platform_tenant.tenant_id
        )
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_users(agency_owner.id)


def test_sibling_agency_remains_isolated_after_one_is_attached(
    platform: tuple[User, PlatformTenant],
) -> None:
    """Attaching Agency A grants the platform owner no reach into Agency B
    (not attached), and grants Agency A's own owner no reach into Agency B
    either -- attachment does not create any Agency-to-Agency edge."""
    owner, _platform_tenant = platform
    owner_a = make_user()
    owner_b = make_user()
    agency_a = provision_agency(owner_a.id, _name("agency-a"))
    agency_b = provision_agency(owner_b.id, _name("agency-b"))
    try:
        attach_agency_to_platform(owner.id, agency_a.tenant_id)

        assert has_platform_authority(owner.id, action="read", tenant_id=agency_a.tenant_id)
        assert not has_platform_authority(owner.id, action="read", tenant_id=agency_b.tenant_id)
        assert not can(
            actor_id=owner_a.id,
            tenant_id=agency_b.tenant_id,
            action="read",
            resource=PLATFORM_ADMINISTRATION_RESOURCE,
        )
    finally:
        cleanup_tenant_tree(agency_a.tenant_id)
        cleanup_tenant_tree(agency_b.tenant_id)
        cleanup_users(owner_a.id, owner_b.id)


def test_explicit_deny_at_the_agency_overrides_platform_owner_reach_there_only(
    platform: tuple[User, PlatformTenant],
) -> None:
    """A deny registered by the Agency's own owner, at the Agency tenant,
    still overrides the platform owner's SUBTREE-inherited allow -- proving
    `attach_agency_to_platform()` grants the platform owner ordinary,
    deny-respecting reach, never a bypass. Scoped exactly to that one
    agency: the platform owner's authority at the platform tenant itself,
    and at an unrelated agency, is untouched."""
    owner, platform_tenant = platform
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    other_owner = make_user()
    other_agency = provision_agency(other_owner.id, _name("other-agency"))
    try:
        attach_agency_to_platform(owner.id, agency.tenant_id)
        attach_agency_to_platform(owner.id, other_agency.tenant_id)
        assert has_platform_authority(owner.id, action="read", tenant_id=agency.tenant_id)

        administration_read = register_permission(PLATFORM_ADMINISTRATION_RESOURCE, "read")
        # The agency's own owner already holds `deny_grant create` at its
        # own tenant (product/agency/roles.py::ensure_agency_owner_role()) --
        # no test-only elevation needed, unlike the platform-tenant deny
        # test above.
        create_deny(
            caller=UserCaller(agency_owner.id),
            principal_user_id=owner.id,
            tenant_id=agency.tenant_id,
            scope_mode=RoleScope.SELF,
            permission_id=administration_read.id,
        )

        assert not has_platform_authority(owner.id, action="read", tenant_id=agency.tenant_id)
        # Unaffected: the platform tenant itself, and an unrelated attached
        # agency, are untouched by a deny scoped to one specific agency.
        assert has_platform_authority(owner.id, action="read")
        assert has_platform_authority(owner.id, action="read", tenant_id=other_agency.tenant_id)
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_tenant_tree(other_agency.tenant_id)
        cleanup_users(agency_owner.id, other_owner.id)
