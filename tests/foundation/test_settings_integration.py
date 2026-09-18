"""Integration test for product/foundation/settings.py against a real,
already-migrated PostgreSQL database (foundation.tenant_settings must
already exist -- see scripts/check-integration.sh, which runs
scripts/bootstrap-db.py first). Marked `integration`, excluded from the
default `pytest` run.

How to run this locally: see scripts/check-integration.sh, or
    docker compose up -d db
    python scripts/bootstrap-db.py
    DATABASE_URL=... MIGRATIONS_DATABASE_URL=... pytest -m integration tests/foundation/
"""

from __future__ import annotations

import uuid

import pytest
from core.tenancy import create_tenant
from infra.db import session_scope, tenant_session_scope
from product.foundation.settings import get_setting, set_setting
from sqlalchemy import text

pytestmark = pytest.mark.integration


class _Fixture:
    def __init__(self) -> None:
        self.tenant = create_tenant(f"settings-test-{uuid.uuid4().hex[:8]}")

    def cleanup(self) -> None:
        with tenant_session_scope(self.tenant.id) as session:
            session.execute(
                text("DELETE FROM foundation.tenant_settings WHERE tenant_id = :t"),
                {"t": str(self.tenant.id)},
            )
        with session_scope() as session:
            session.execute(
                text("DELETE FROM core.tenants WHERE id = :id"), {"id": str(self.tenant.id)}
            )


@pytest.fixture
def fx():
    fixture = _Fixture()
    yield fixture
    fixture.cleanup()


def test_get_unset_setting_returns_none(fx: _Fixture) -> None:
    assert get_setting(fx.tenant.id, "default_pipeline_template") is None


def test_set_then_get_round_trip(fx: _Fixture) -> None:
    set_setting(fx.tenant.id, "default_sender_name", "Acme Support")
    assert get_setting(fx.tenant.id, "default_sender_name") == "Acme Support"


def test_set_overwrites_existing_value(fx: _Fixture) -> None:
    set_setting(fx.tenant.id, "k", "first")
    set_setting(fx.tenant.id, "k", "second")
    assert get_setting(fx.tenant.id, "k") == "second"


def test_settings_are_isolated_per_tenant(fx: _Fixture) -> None:
    other = create_tenant(f"settings-test-other-{uuid.uuid4().hex[:8]}")
    try:
        set_setting(fx.tenant.id, "shared_key", "tenant-a-value")
        set_setting(other.id, "shared_key", "tenant-b-value")

        assert get_setting(fx.tenant.id, "shared_key") == "tenant-a-value"
        assert get_setting(other.id, "shared_key") == "tenant-b-value"
    finally:
        with tenant_session_scope(other.id) as session:
            session.execute(
                text("DELETE FROM foundation.tenant_settings WHERE tenant_id = :t"),
                {"t": str(other.id)},
            )
        with session_scope() as session:
            session.execute(text("DELETE FROM core.tenants WHERE id = :id"), {"id": str(other.id)})
