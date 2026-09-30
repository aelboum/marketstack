"""Integration tests for product/platform/provisioning.py against a real,
already-migrated PostgreSQL database. Marked `integration`, excluded from
the default `pytest` run (see scripts/check-integration.sh).

Covers docs/ROADMAP.md Phase 31's own provisioning-side requirements:
deterministic resolution of "the" platform tenant with no new table
(`PLATFORM_TENANT_ID`, never a name lookup -- module docstring's own
"Resolving 'the' platform tenant" section), a one-time bootstrap that
never silently re-runs, and -- the single most important safety property
this phase's own roadmap text names -- that bootstrapping the platform
tenant never reparents any existing agency.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from core.audit_log import list as list_audit_entries
from core.tenancy import TenantNotFoundError, create_tenant, get_ancestor_chain, get_tenant
from product.agency.provisioning import provision_agency, provision_client
from product.platform.errors import (
    PlatformAccessDeniedError,
    PlatformAttachTargetNotRootTenantError,
    PlatformSelfAttachError,
    PlatformTenantAlreadyBootstrappedError,
    PlatformTenantNotBootstrappedError,
    PlatformTenantNotRootError,
)
from product.platform.provisioning import (
    PLATFORM_TENANT_ID_ENV_VAR,
    attach_agency_to_platform,
    bootstrap_platform_tenant,
    get_platform_tenant,
)

from tests.platform._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_get_platform_tenant_raises_when_env_var_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    with pytest.raises(PlatformTenantNotBootstrappedError):
        get_platform_tenant()


def test_get_platform_tenant_raises_when_env_var_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed value fails closed identically to "unset" -- module
    docstring's own reasoning -- rather than raising a bare ValueError
    from deep inside an authorization check."""
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, "not-a-uuid")
    with pytest.raises(PlatformTenantNotBootstrappedError):
        get_platform_tenant()


def test_get_platform_tenant_raises_tenant_not_found_for_a_nonexistent_configured_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit remediation Finding A, state 3: a syntactically valid UUID
    that names no real tenant is a genuine misconfiguration, distinct
    from "not configured" -- `core.tenancy.TenantNotFoundError` must
    surface unchanged, never silently collapsed into
    `PlatformTenantNotBootstrappedError` (module docstring)."""
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(uuid.uuid4()))
    with pytest.raises(TenantNotFoundError):
        get_platform_tenant()


def test_get_platform_tenant_rejects_a_valid_non_root_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit remediation Finding A, state 5: a configured id that names a
    real, existing, but NON-root tenant (a valid child) must be rejected
    -- distinct from every other failure mode above, and distinct from
    "not configured": this proves a valid child tenant specifically is
    refused, not merely that resolution fails somehow."""
    owner = make_user()
    agency = provision_agency(owner.id, _name("agency"))
    child = create_tenant(_name("child"), parent_id=agency.tenant_id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(child.id))
    try:
        with pytest.raises(PlatformTenantNotRootError):
            get_platform_tenant()
    finally:
        cleanup_tenant_tree(child.id, agency.tenant_id)
        cleanup_users(owner.id)


def test_bootstrap_then_resolve_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    owner = make_user()
    platform = bootstrap_platform_tenant(owner.id)
    try:
        monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
        resolved = get_platform_tenant()
        assert resolved.id == platform.tenant_id
        # The platform tenant is itself a root -- not a child of anything.
        assert resolved.parent_id is None
    finally:
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(owner.id)


def test_bootstrap_refuses_when_already_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """One-time bootstrap, never a silent re-run (module docstring's
    documented provisioning gap: adding a second owner is deliberately a
    separate, not-yet-built operation)."""
    owner = make_user()
    already_configured_id = uuid.uuid4()
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(already_configured_id))
    try:
        with pytest.raises(PlatformTenantAlreadyBootstrappedError):
            bootstrap_platform_tenant(owner.id)
    finally:
        cleanup_users(owner.id)


def test_bootstrap_does_not_reparent_any_existing_agency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 31's own "do not silently reparent tenants" requirement,
    verified directly: an agency created BEFORE the platform tenant exists
    remains exactly where it was -- still a root, still with an empty
    ancestor chain -- after bootstrap."""
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    try:
        assert get_ancestor_chain(agency.tenant_id) == []
        assert platform.tenant_id not in get_ancestor_chain(agency.tenant_id)
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id)


# --- Phase 31 completion: attach_agency_to_platform() ----------------------
#
# Phase 31's own foundation deliberately leaves the platform tenant reaching
# nothing (test above). These tests cover the one function this completion
# pass adds to make Platform -> Agency -> Client a real, established edge --
# on the explicit, gated, one-agency-at-a-time path the module docstring
# documents, never automatically.


def test_attach_agency_to_platform_moves_the_agency_under_the_platform_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        moved = attach_agency_to_platform(platform_owner.id, agency.tenant_id)

        assert moved.id == agency.tenant_id  # tenant id is preserved
        assert moved.parent_id == platform.tenant_id
        assert get_ancestor_chain(agency.tenant_id) == [platform.tenant_id]
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id)


def test_attach_agency_to_platform_preserves_the_agencys_own_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`move_tenant()`'s own documented guarantee, verified end to end:
    reparenting the agency does not touch a client already beneath it --
    same tenant id, same ancestry relative to the agency, still reachable
    through it (now with the platform tenant as one more ancestor)."""
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    try:
        attach_agency_to_platform(platform_owner.id, agency.tenant_id)

        client_ancestors = get_ancestor_chain(client.tenant_id)
        assert agency.tenant_id in client_ancestors
        assert platform.tenant_id in client_ancestors
        assert get_tenant(client.tenant_id).id == client.tenant_id  # untouched
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id)


def test_attach_agency_to_platform_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        attach_agency_to_platform(platform_owner.id, agency.tenant_id)
        moved_again = attach_agency_to_platform(platform_owner.id, agency.tenant_id)

        assert moved_again.parent_id == platform.tenant_id
        assert get_ancestor_chain(agency.tenant_id) == [platform.tenant_id]
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id)


def test_attach_agency_to_platform_requires_platform_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    stranger = make_user()
    try:
        with pytest.raises(PlatformAccessDeniedError):
            attach_agency_to_platform(stranger.id, agency.tenant_id)
        # Refused before any hierarchy write -- the agency is untouched.
        assert get_ancestor_chain(agency.tenant_id) == []
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id, stranger.id)


def test_agency_owner_cannot_attach_their_own_agency_without_platform_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit remediation Finding C: the *agency's own owner* -- an actor
    with full, real authority over that one agency, unlike the unrelated
    `stranger` above -- still holds no role at the platform tenant (a
    structurally separate tenant), so `can()` denies them identically.
    This proves owning the target agency is not itself a path around the
    platform-authority gate."""
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        with pytest.raises(PlatformAccessDeniedError):
            attach_agency_to_platform(agency_owner.id, agency.tenant_id)
        # Refused before any hierarchy write -- the agency's own parent is
        # unchanged, and no attachment audit event was created.
        assert get_ancestor_chain(agency.tenant_id) == []
        entries = list_audit_entries(agency.tenant_id, resource_id=str(agency.tenant_id))
        assert not any(e.action == "platform.agency_attached" for e in entries)
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id)


def test_attach_agency_to_platform_refuses_to_attach_the_platform_tenant_to_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    try:
        with pytest.raises(PlatformSelfAttachError):
            attach_agency_to_platform(platform_owner.id, platform.tenant_id)
    finally:
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(platform_owner.id)


def test_attach_agency_to_platform_refuses_a_tenant_that_is_not_a_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Client tenant (a child of some agency) is not itself an Agency
    root -- `attach_agency_to_platform()` refuses to move it, rather than
    silently detaching it from its own agency."""
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    client = provision_client(agency_owner.id, agency.tenant_id, _name("client"))
    try:
        with pytest.raises(PlatformAttachTargetNotRootTenantError):
            attach_agency_to_platform(platform_owner.id, client.tenant_id)
        # Refused before any hierarchy write -- the client stays exactly
        # where it was, still under its own agency only.
        assert get_ancestor_chain(client.tenant_id) == [agency.tenant_id]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id)


def test_attach_agency_to_platform_refuses_a_tenant_already_parented_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the same invariant as the Client case above, for a plain
    `core.tenancy` child tenant that is not a `product.agency` concept at
    all -- the check is purely structural (`parent_id`), not agency-
    specific."""
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    child = create_tenant(_name("child"), parent_id=agency.tenant_id)
    try:
        with pytest.raises(PlatformAttachTargetNotRootTenantError):
            attach_agency_to_platform(platform_owner.id, child.id)
    finally:
        cleanup_tenant_tree(child.id, agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id)


# --- Audit remediation Finding B/D: concurrent duplicate attachment --------
#
# Two real threads race to attach the SAME not-yet-attached Agency,
# synchronized with a `threading.Barrier` so they genuinely contend --
# mirrors tests/conversations/test_concurrency_integration.py's own exact
# shape. `move_tenant()`'s own hierarchy-wide advisory lock (core.tenancy)
# is what makes the resulting hierarchy safe; `core.idempotency`'s
# reservation (product/platform/provisioning.py::attach_agency_to_platform()'s
# own "Audit correctness" docstring section) is what makes the audit
# record count deterministic. This test proves both together against a
# real database, not just by source inspection.


def test_concurrent_duplicate_attachment_is_hierarchy_safe_and_audits_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLATFORM_TENANT_ID_ENV_VAR, raising=False)
    platform_owner = make_user()
    platform = bootstrap_platform_tenant(platform_owner.id)
    monkeypatch.setenv(PLATFORM_TENANT_ID_ENV_VAR, str(platform.tenant_id))
    agency_owner = make_user()
    agency = provision_agency(agency_owner.id, _name("agency"))
    try:
        barrier = threading.Barrier(2)
        results: dict[str, tuple[str, object]] = {}

        def _attempt(label: str) -> None:
            barrier.wait()
            try:
                moved = attach_agency_to_platform(platform_owner.id, agency.tenant_id)
                results[label] = ("ok", moved)
            except Exception as exc:  # noqa: BLE001 -- recorded for the assertion below
                results[label] = ("failed", exc)

        thread_a = threading.Thread(target=_attempt, args=("a",))
        thread_b = threading.Thread(target=_attempt, args=("b",))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=30)
        thread_b.join(timeout=30)

        # 1. Both attempts reached the attachment operation and completed
        # -- `attach_agency_to_platform()`'s own "safe to call more than
        # once, never raises" guarantee holds under real concurrency too.
        assert results["a"][0] == "ok", results["a"]
        assert results["b"][0] == "ok", results["b"]

        # 2. The resulting hierarchy contains the agency under the
        # platform tenant, exactly once, with no corruption.
        assert get_ancestor_chain(agency.tenant_id) == [platform.tenant_id]

        # 3. Idempotent: calling it again afterward is still a clean no-op.
        moved_again = attach_agency_to_platform(platform_owner.id, agency.tenant_id)
        assert moved_again.parent_id == platform.tenant_id

        # 4. Exactly one successful "platform.agency_attached" audit event
        # exists for this agency, despite two genuinely concurrent callers
        # (audit remediation Finding B) -- the real point of this test.
        entries = list_audit_entries(agency.tenant_id, resource_id=str(agency.tenant_id))
        attached_entries = [e for e in entries if e.action == "platform.agency_attached"]
        assert len(attached_entries) == 1, attached_entries
    finally:
        cleanup_tenant_tree(agency.tenant_id)
        cleanup_tenant_tree(platform.tenant_id)
        cleanup_users(agency_owner.id, platform_owner.id)
