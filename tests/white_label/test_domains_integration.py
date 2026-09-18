"""Integration tests for product/white_label/domains.py against a real,
already-migrated PostgreSQL database (white_label.tenant_domains must
already exist -- see scripts/check-integration.sh). Marked `integration`.

The middleware tests build a small, isolated FastAPI app (not the full
product/api/main.py composition root, which pulls in the entire SaaS-OS
auth chain) -- this keeps these tests focused on
DomainResolutionMiddleware's own contract alone.
"""

from __future__ import annotations

import uuid

import pytest
from core.tenancy import create_tenant
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infra.db import session_scope
from product.white_label.domains import DomainResolutionMiddleware, resolve_tenant_for_domain
from product.white_label.models import TenantDomain
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _delete_tenant(tenant_id: uuid.UUID) -> None:
    with session_scope() as session:
        session.execute(
            text("DELETE FROM white_label.tenant_domains WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        session.execute(text("DELETE FROM core.tenants WHERE id = :id"), {"id": str(tenant_id)})


def _map_domain(domain: str, tenant_id: uuid.UUID) -> None:
    with session_scope() as session:
        session.add(TenantDomain(domain=domain, tenant_id=tenant_id))


class TestResolveTenantForDomain:
    def test_mapped_domain_resolves_correct_tenant(self) -> None:
        tenant = create_tenant(f"domain-test-{uuid.uuid4().hex[:8]}")
        domain = f"{uuid.uuid4().hex[:8]}.example-agency.com"
        try:
            _map_domain(domain, tenant.id)
            assert resolve_tenant_for_domain(domain) == tenant.id
        finally:
            _delete_tenant(tenant.id)

    def test_unmapped_domain_resolves_none(self) -> None:
        assert resolve_tenant_for_domain("never-mapped.example.com") is None

    def test_malformed_domain_resolves_none(self) -> None:
        assert resolve_tenant_for_domain("") is None
        assert resolve_tenant_for_domain("has/a/slash") is None


class TestDomainResolutionMiddleware:
    @pytest.fixture(autouse=True)
    def _public_domain_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PUBLIC_DOMAIN", "platform.example.com")

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        app.add_middleware(DomainResolutionMiddleware)

        @app.get("/probe")
        def probe() -> dict[str, bool]:
            return {"ok": True}

        return app

    def test_platform_domain_passes_through_untouched(self) -> None:
        app = self._build_app()
        client = TestClient(app, base_url="http://platform.example.com")
        response = client.get("/probe")
        assert response.status_code == 200

    def test_platform_subdomain_passes_through_untouched(self) -> None:
        app = self._build_app()
        client = TestClient(app, base_url="http://acme.platform.example.com")
        response = client.get("/probe")
        assert response.status_code == 200

    def test_unmapped_custom_domain_rejected_non_enumerating(self) -> None:
        app = self._build_app()
        client = TestClient(app, base_url="http://never-mapped-custom-domain.com")
        response = client.get("/probe")
        assert response.status_code == 404

    def test_mapped_custom_domain_resolves_and_passes_through(self) -> None:
        tenant = create_tenant(f"domain-mw-test-{uuid.uuid4().hex[:8]}")
        domain = f"{uuid.uuid4().hex[:8]}.custom-agency-domain.com"
        try:
            _map_domain(domain, tenant.id)
            app = FastAPI()
            app.add_middleware(DomainResolutionMiddleware)
            seen_tenant_ids: list[uuid.UUID] = []

            @app.get("/probe")
            def probe_with_state() -> dict[str, bool]:
                return {"ok": True}

            @app.middleware("http")
            async def _capture(request, call_next):
                response = await call_next(request)
                resolved = getattr(request.state, "resolved_tenant_id", None)
                if resolved is not None:
                    seen_tenant_ids.append(resolved)
                return response

            client = TestClient(app, base_url=f"http://{domain}")
            response = client.get("/probe")
            assert response.status_code == 200
            assert seen_tenant_ids == [tenant.id]
        finally:
            _delete_tenant(tenant.id)

    def test_no_public_domain_configured_disables_middleware(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No PUBLIC_DOMAIN set at all -- must never accidentally reject
        # every request (fail-open on missing config, not fail-closed on
        # every request -- misconfiguration should be loud elsewhere, not
        # a silent platform-wide 404).
        monkeypatch.delenv("PUBLIC_DOMAIN", raising=False)
        app = self._build_app()
        client = TestClient(app, base_url="http://anything-at-all.com")
        response = client.get("/probe")
        assert response.status_code == 200
