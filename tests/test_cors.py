"""CORS policy tests (docs/ROADMAP.md UI Track -- UI-1 remediation).

Verifies actual browser-relevant response *behavior*, not just that
`CORSMiddleware` is present: whether a response for an allowed origin
carries the headers a browser needs to read it under `credentials:
"include"`, whether a disallowed origin does not, and whether a real
preflight for this frontend's own request shape (GET, JSON body on
writes, `Content-Type` header) succeeds or is rejected. No database is
required -- `create_app()` stays callable with none configured
(`product/api/main.py`'s own module docstring), and a CORS preflight
never reaches routing/DB at all (`CORSMiddleware` answers it directly).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from product.api.main import create_app

ALLOWED_ORIGIN = "http://localhost:3000"
DISALLOWED_ORIGIN = "http://evil.example.com"
# A real product route -- exercises the actual frontend/backend contract
# path shape, not just the platform-provided /healthz.
CRM_CONTACTS_PATH = "/v1/crm/tenants/00000000-0000-0000-0000-000000000000/contacts"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FRONTEND_ORIGINS", ALLOWED_ORIGIN)
    return TestClient(create_app())


def test_request_with_no_origin_header_is_unaffected(client: TestClient) -> None:
    """A same-origin browser request or a server-to-server call never
    carries an Origin header for CORS purposes -- must not be touched."""
    response = client.get("/healthz")

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_receives_the_headers_a_credentialed_fetch_needs(
    client: TestClient,
) -> None:
    response = client.get("/healthz", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_disallowed_origin_receives_no_allow_origin_header(client: TestClient) -> None:
    """The server still answers -- CORS is enforced by the browser, not
    the server -- but omits the header that would let a disallowed
    origin's browser actually read the response body."""
    response = client.get("/healthz", headers={"Origin": DISALLOWED_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert response.headers.get("access-control-allow-origin") != DISALLOWED_ORIGIN


def test_preflight_for_the_frontends_actual_request_shape_succeeds(client: TestClient) -> None:
    """Mirrors what a browser actually sends before
    `frontend/lib/api/client.ts`'s credentialed `fetch(..., {method:
    "GET", credentials: "include"})` against a real product route."""
    response = client.options(
        CRM_CONTACTS_PATH,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed_methods = response.headers["access-control-allow-methods"]
    for method in ("GET", "POST", "PATCH", "PUT", "DELETE"):
        assert method in allowed_methods


def test_preflight_for_a_write_request_with_json_content_type_succeeds(
    client: TestClient,
) -> None:
    """The frontend client sets `Content-Type: application/json` on every
    POST/PATCH/PUT (lib/api/client.ts) -- the preflight for that header
    must actually be allowed, not just the bare GET case above."""
    response = client.options(
        CRM_CONTACTS_PATH,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_preflight_for_disallowed_origin_is_rejected(client: TestClient) -> None:
    response = client.options(
        CRM_CONTACTS_PATH,
        headers={
            "Origin": DISALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_unset_frontend_origins_allows_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed default: no configuration means no origin is granted
    access, never `*` -- every environment, local dev included, must set
    `FRONTEND_ORIGINS` explicitly (mirrors this product's existing
    `ENVIRONMENT`-must-be-explicit posture, infra.secrets)."""
    monkeypatch.delenv("FRONTEND_ORIGINS", raising=False)
    client = TestClient(create_app())

    response = client.get("/healthz", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_multiple_configured_origins_are_each_individually_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second_origin = "https://app.example-agency.com"
    monkeypatch.setenv("FRONTEND_ORIGINS", f"{ALLOWED_ORIGIN},{second_origin}")
    client = TestClient(create_app())

    first = client.get("/healthz", headers={"Origin": ALLOWED_ORIGIN})
    second = client.get("/healthz", headers={"Origin": second_origin})

    assert first.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert second.headers["access-control-allow-origin"] == second_origin
