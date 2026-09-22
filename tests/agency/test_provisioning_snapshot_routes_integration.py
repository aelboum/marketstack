"""HTTP-level integration tests for docs/ROADMAP.md Phase 21's
`POST /v1/agency/agencies/{agency_tenant_id}/clients` extension --
optional `snapshot_id` in the request body, and the additive
`provisioning_status`/`setup_error` response fields. Real FastAPI
TestClient, real disposable PostgreSQL. Marked `integration`, excluded
from the default `pytest` run.

Uses `tests.templates._cleanup` (not `tests.agency._cleanup`) for the
same reason as `tests/agency/test_provisioning_snapshot_integration.py`:
these tests create real `crm.pipelines`/`templates.snapshots` rows.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity.sessions import issue_session
from core.tenancy import get_tenant
from fastapi.testclient import TestClient
from product.api.main import create_app
from product.crm.pipelines import create_pipeline, create_stage, list_pipelines
from product.templates.snapshots import create_snapshot

from tests.templates._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def _seed_pipeline(owner_id, tenant_id, name: str = "Sales") -> None:
    pipeline = create_pipeline(owner_id, tenant_id, name=name, is_default=True)
    create_stage(owner_id, tenant_id, pipeline.id, name="Open", position=0)


def test_create_client_with_snapshot_over_http_returns_completed_status() -> None:
    owner = make_user()
    api = TestClient(create_app())
    headers = _auth_headers(owner.id)
    agency_tenant_id = None
    client_tenant_id = None
    try:
        agency_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=headers
        )
        agency_tenant_id = uuid.UUID(agency_resp.json()["tenant_id"])
        _seed_pipeline(owner.id, agency_tenant_id, name="HTTP Setup Sales")
        snapshot = create_snapshot(
            owner.id, agency_tenant_id, name="HTTP setup", domains=["crm.pipelines"]
        )

        create_client_response = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("client"), "snapshot_id": str(snapshot.id)},
            headers=headers,
        )
        assert create_client_response.status_code == 201
        body = create_client_response.json()
        assert body["provisioning_status"] == "completed"
        assert body["setup_error"] is None
        client_tenant_id = uuid.UUID(body["tenant_id"])

        pipelines = list_pipelines(owner.id, client_tenant_id)
        assert any(p.name == "HTTP Setup Sales" for p in pipelines)
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_create_client_with_unknown_snapshot_over_http_reports_setup_failed_not_an_error() -> None:
    """The client tenant is real -- a 201, never a 404/500 that would
    suggest nothing was created."""
    owner = make_user()
    api = TestClient(create_app())
    headers = _auth_headers(owner.id)
    agency_tenant_id = None
    client_tenant_id = None
    try:
        agency_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=headers
        )
        agency_tenant_id = uuid.UUID(agency_resp.json()["tenant_id"])

        create_client_response = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("client"), "snapshot_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert create_client_response.status_code == 201
        body = create_client_response.json()
        assert body["provisioning_status"] == "setup_failed"
        assert body["setup_error"] == "SnapshotNotFoundError"
        client_tenant_id = uuid.UUID(body["tenant_id"])

        tenant = get_tenant(client_tenant_id)
        assert tenant.id == client_tenant_id
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)


def test_create_client_without_snapshot_over_http_is_additive_only() -> None:
    owner = make_user()
    api = TestClient(create_app())
    headers = _auth_headers(owner.id)
    agency_tenant_id = None
    client_tenant_id = None
    try:
        agency_resp = api.post(
            "/v1/agency/agencies", json={"name": _name("agency")}, headers=headers
        )
        agency_tenant_id = uuid.UUID(agency_resp.json()["tenant_id"])

        create_client_response = api.post(
            f"/v1/agency/agencies/{agency_tenant_id}/clients",
            json={"name": _name("client")},
            headers=headers,
        )
        assert create_client_response.status_code == 201
        body = create_client_response.json()
        assert body["provisioning_status"] == "completed"
        assert body["setup_error"] is None
        client_tenant_id = uuid.UUID(body["tenant_id"])
    finally:
        ids = [i for i in (client_tenant_id, agency_tenant_id) if i is not None]
        cleanup_tenant_tree(*ids)
        cleanup_users(owner.id)
