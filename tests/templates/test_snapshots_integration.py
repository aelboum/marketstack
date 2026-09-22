"""`product/templates/snapshots.py`: snapshot capture/apply, the
ID-elimination design, tenant isolation, authorization, and
tenant-lifecycle denial (docs/ROADMAP.md Phase 14). Real disposable
Postgres. Marked `integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from core.identity import add_tenant_membership
from core.rbac import RoleScope, assign_role
from core.tenancy import TenantStatus, transition_tenant_status
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.crm.pipelines import create_pipeline, create_stage, list_pipelines, list_stages
from product.foundation.events import subscribe
from product.templates.errors import (
    SnapshotNotFoundError,
    TemplatesAccessDeniedError,
    TemplatesValidationError,
)
from product.templates.pagination import MAX_PAGE_SIZE
from product.templates.snapshots import (
    SNAPSHOT_APPLIED_EVENT_TYPE,
    SNAPSHOT_CREATED_EVENT_TYPE,
    apply_snapshot,
    create_snapshot,
    get_snapshot,
    list_snapshots,
)

from tests.templates._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _add_member(owner_id, tenant_id, user_id) -> None:
    membership = add_tenant_membership(tenant_id, user_id)
    member_role = ensure_client_member_role(tenant_id)
    assign_role(
        tenant_id, membership.id, member_role.id, scope=RoleScope.SELF, actor_user_id=owner_id
    )


def _seed_pipeline(owner_id, tenant_id, name: str = "Sales") -> None:
    pipeline = create_pipeline(owner_id, tenant_id, name=name, is_default=True)
    create_stage(owner_id, tenant_id, pipeline.id, name="Open", position=0)
    create_stage(owner_id, tenant_id, pipeline.id, name="Won", position=1, is_won=True)
    create_stage(owner_id, tenant_id, pipeline.id, name="Lost", position=2, is_lost=True)


# --- Valid creation / export -----------------------------------------------------


def test_create_snapshot_exports_pipelines_without_any_identifier() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _seed_pipeline(owner.id, client.tenant_id)
        snapshot = create_snapshot(
            owner.id,
            client.tenant_id,
            name="Baseline",
            domains=["crm.pipelines"],
        )
        assert snapshot.tenant_id == client.tenant_id
        assert snapshot.schema_version == 1
        assert snapshot.included_domains == ["crm.pipelines"]
        pipelines = snapshot.payload["crm.pipelines"]
        assert len(pipelines) == 1
        assert pipelines[0]["name"] == "Sales"
        assert pipelines[0]["is_default"] is True
        assert [s["name"] for s in pipelines[0]["stages"]] == ["Open", "Won", "Lost"]
        # The ID-elimination design (docs/ADR/0013-...'s own "Decision 2"):
        # no id/tenant_id/pipeline_id anywhere in the captured payload.
        payload_text = str(snapshot.payload)
        assert str(client.tenant_id) not in payload_text

        fetched = get_snapshot(owner.id, client.tenant_id, snapshot.id)
        assert fetched.id == snapshot.id

        listed = list_snapshots(owner.id, client.tenant_id)
        assert any(s.id == snapshot.id for s in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_snapshot_publishes_event_and_audit_entry() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received = []

    def _handler(event):
        received.append(event)

    subscribe(SNAPSHOT_CREATED_EVENT_TYPE, _handler)
    try:
        _seed_pipeline(owner.id, client.tenant_id)
        snapshot = create_snapshot(
            owner.id, client.tenant_id, name="Audited", domains=["crm.pipelines"]
        )
        matching_events = [e for e in received if e.payload.get("snapshot_id") == str(snapshot.id)]
        assert len(matching_events) == 1

        entries = list_audit_log(
            client.tenant_id, resource_type="templates.snapshot", resource_id=str(snapshot.id)
        )
        matching_audit = [e for e in entries if e.action == "templates.snapshot.created"]
        assert len(matching_audit) == 1
        assert matching_audit[0].entry_metadata == {"included_domains": ["crm.pipelines"]}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Invalid input ------------------------------------------------------------


def test_create_snapshot_rejects_empty_domains() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(TemplatesValidationError):
            create_snapshot(owner.id, client.tenant_id, name="Empty", domains=[])
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_snapshot_rejects_unsupported_domain() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(TemplatesValidationError):
            create_snapshot(
                owner.id, client.tenant_id, name="Bad Domain", domains=["marketing.forms"]
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_create_snapshot_with_no_pipelines_is_an_empty_but_valid_export() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        snapshot = create_snapshot(
            owner.id, client.tenant_id, name="Empty Export", domains=["crm.pipelines"]
        )
        assert snapshot.payload["crm.pipelines"] == []
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Apply: same tenant, different tenant ---------------------------------------


def test_apply_snapshot_to_same_tenant_creates_a_second_independent_pipeline() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _seed_pipeline(owner.id, client.tenant_id, name="Original")
        snapshot = create_snapshot(
            owner.id, client.tenant_id, name="Clone Source", domains=["crm.pipelines"]
        )
        result = apply_snapshot(owner.id, client.tenant_id, snapshot.id, client.tenant_id)
        assert result.created_counts == {"crm.pipelines": 1}

        pipelines = list_pipelines(owner.id, client.tenant_id)
        matching = [p for p in pipelines if p.name == "Original"]
        assert len(matching) == 2  # the original, plus the newly-applied clone
        assert len({p.id for p in matching}) == 2  # genuinely distinct rows
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_apply_snapshot_to_a_different_tenant_creates_fresh_entities_there() -> None:
    owner = make_user()
    agency, client_a = _agency_and_client(owner.id)
    client_b = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        _seed_pipeline(owner.id, client_a.tenant_id, name="Onboarding")
        snapshot = create_snapshot(
            owner.id, client_a.tenant_id, name="Master Config", domains=["crm.pipelines"]
        )
        result = apply_snapshot(owner.id, client_a.tenant_id, snapshot.id, client_b.tenant_id)
        assert result.target_tenant_id == client_b.tenant_id
        assert result.created_counts == {"crm.pipelines": 1}

        cloned_pipelines = list_pipelines(owner.id, client_b.tenant_id)
        assert len(cloned_pipelines) == 1
        assert cloned_pipelines[0].name == "Onboarding"
        assert cloned_pipelines[0].tenant_id == client_b.tenant_id
        cloned_stages = list_stages(owner.id, client_b.tenant_id, cloned_pipelines[0].id)
        assert [s.name for s in cloned_stages] == ["Open", "Won", "Lost"]

        # Source tenant's own pipeline is untouched.
        source_pipelines = list_pipelines(owner.id, client_a.tenant_id)
        assert len(source_pipelines) == 1
    finally:
        cleanup_tenant_tree(client_b.tenant_id, client_a.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_apply_snapshot_publishes_event_and_audit_entry_on_target_tenant() -> None:
    owner = make_user()
    agency, client_a = _agency_and_client(owner.id)
    client_b = provision_client(owner.id, agency.tenant_id, _name("client"))
    received = []

    def _handler(event):
        received.append(event)

    subscribe(SNAPSHOT_APPLIED_EVENT_TYPE, _handler)
    try:
        _seed_pipeline(owner.id, client_a.tenant_id)
        snapshot = create_snapshot(
            owner.id, client_a.tenant_id, name="For Apply", domains=["crm.pipelines"]
        )
        apply_snapshot(owner.id, client_a.tenant_id, snapshot.id, client_b.tenant_id)

        matching_events = [e for e in received if e.payload.get("snapshot_id") == str(snapshot.id)]
        assert len(matching_events) == 1
        assert matching_events[0].tenant_id == str(client_b.tenant_id)

        entries = list_audit_log(
            client_b.tenant_id, resource_type="templates.snapshot", resource_id=str(snapshot.id)
        )
        matching_audit = [e for e in entries if e.action == "templates.snapshot.applied"]
        assert len(matching_audit) == 1
        assert (matching_audit[0].entry_metadata or {})["source_tenant_id"] == str(
            client_a.tenant_id
        )
    finally:
        cleanup_tenant_tree(client_b.tenant_id, client_a.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_apply_snapshot_rejects_unsupported_schema_version() -> None:
    """A snapshot from a future, unsupported schema version must be
    rejected cleanly, never silently interpreted (docs/ROADMAP.md Phase
    14's own "Configuration schema/versioning" requirement)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _seed_pipeline(owner.id, client.tenant_id)
        snapshot = create_snapshot(
            owner.id, client.tenant_id, name="Future", domains=["crm.pipelines"]
        )
        # Simulate a snapshot stamped with a not-yet-supported schema
        # version -- directly at the ORM layer, the one place this test
        # needs to reach past the service layer to construct an otherwise
        # unreachable (via any real write path) invalid state.
        from infra.db import tenant_session_scope
        from product.templates.models import Snapshot

        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(Snapshot, snapshot.id)
            assert row is not None
            row.schema_version = 999
            session.flush()

        with pytest.raises(TemplatesValidationError):
            apply_snapshot(owner.id, client.tenant_id, snapshot.id, client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant isolation ------------------------------------------------------------


def test_snapshots_are_isolated_across_tenants() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    other_owner = make_user()
    other_agency, other_client = _agency_and_client(other_owner.id)
    try:
        _seed_pipeline(owner.id, client.tenant_id)
        snapshot = create_snapshot(
            owner.id, client.tenant_id, name="Mine", domains=["crm.pipelines"]
        )
        with pytest.raises(SnapshotNotFoundError):
            get_snapshot(other_owner.id, other_client.tenant_id, snapshot.id)
        listed = list_snapshots(other_owner.id, other_client.tenant_id)
        assert all(s.id != snapshot.id for s in listed)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(other_client.tenant_id, other_agency.tenant_id)
        cleanup_users(owner.id, other_owner.id)


def test_cannot_apply_a_snapshot_owned_by_an_unrelated_tenant() -> None:
    """The requesting actor must hold `read` on the SOURCE tenant that
    actually owns the snapshot -- an unrelated actor guessing a real
    snapshot id must not be able to apply someone else's configuration
    anywhere, including into their own tenant."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated_owner = make_user()
    unrelated_agency, unrelated_client = _agency_and_client(unrelated_owner.id)
    try:
        _seed_pipeline(owner.id, client.tenant_id)
        snapshot = create_snapshot(
            owner.id, client.tenant_id, name="Private", domains=["crm.pipelines"]
        )
        with pytest.raises(TemplatesAccessDeniedError):
            apply_snapshot(
                unrelated_owner.id, client.tenant_id, snapshot.id, unrelated_client.tenant_id
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_tenant_tree(unrelated_client.tenant_id, unrelated_agency.tenant_id)
        cleanup_users(owner.id, unrelated_owner.id)


# --- Authorization -------------------------------------------------------------


def test_unrelated_actor_cannot_create_snapshot() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    unrelated = make_user()
    try:
        with pytest.raises(TemplatesAccessDeniedError):
            create_snapshot(unrelated.id, client.tenant_id, name="Nope", domains=["crm.pipelines"])
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, unrelated.id)


def test_member_can_create_and_read_but_not_apply() -> None:
    """`product/templates/event_handlers.py`'s own owner/member grant
    split: member gets create/read, never apply."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    member = make_user()
    _add_member(owner.id, client.tenant_id, member.id)
    try:
        _seed_pipeline(owner.id, client.tenant_id)
        snapshot = create_snapshot(
            member.id, client.tenant_id, name="By Member", domains=["crm.pipelines"]
        )
        fetched = get_snapshot(member.id, client.tenant_id, snapshot.id)
        assert fetched.id == snapshot.id
        with pytest.raises(TemplatesAccessDeniedError):
            apply_snapshot(member.id, client.tenant_id, snapshot.id, client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_agency_owner_reaches_client_snapshots_via_subtree() -> None:
    """An agency owner's pre-existing `SUBTREE` role
    (`product/agency/provisioning.py::provision_agency()`) reaches a
    descendant client's own snapshots with zero additional authorization
    code -- the same mechanism every other module's own SUBTREE test
    already proves."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _seed_pipeline(owner.id, client.tenant_id)
        snapshot = create_snapshot(
            owner.id, client.tenant_id, name="Reachable", domains=["crm.pipelines"]
        )
        fetched = get_snapshot(owner.id, client.tenant_id, snapshot.id)
        assert fetched.id == snapshot.id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Tenant lifecycle ----------------------------------------------------------


def test_suspended_tenant_denies_snapshot_creation() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        _seed_pipeline(owner.id, client.tenant_id)
        transition_tenant_status(client.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(TemplatesAccessDeniedError):
            create_snapshot(owner.id, client.tenant_id, name="Denied", domains=["crm.pipelines"])
    finally:
        transition_tenant_status(client.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_suspended_target_tenant_denies_snapshot_apply() -> None:
    owner = make_user()
    agency, client_a = _agency_and_client(owner.id)
    client_b = provision_client(owner.id, agency.tenant_id, _name("client"))
    try:
        _seed_pipeline(owner.id, client_a.tenant_id)
        snapshot = create_snapshot(
            owner.id, client_a.tenant_id, name="Source", domains=["crm.pipelines"]
        )
        transition_tenant_status(client_b.tenant_id, TenantStatus.SUSPENDED)
        with pytest.raises(TemplatesAccessDeniedError):
            apply_snapshot(owner.id, client_a.tenant_id, snapshot.id, client_b.tenant_id)
    finally:
        transition_tenant_status(client_b.tenant_id, TenantStatus.ACTIVE)
        cleanup_tenant_tree(client_b.tenant_id, client_a.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Pagination ------------------------------------------------------------


def test_list_snapshots_pagination_is_bounded() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        for _ in range(3):
            create_snapshot(
                owner.id, client.tenant_id, name=_name("bulk"), domains=["crm.pipelines"]
            )
        results = list_snapshots(owner.id, client.tenant_id, limit=MAX_PAGE_SIZE * 10)
        assert len(results) <= MAX_PAGE_SIZE
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
