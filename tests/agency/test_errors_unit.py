"""Unit tests for product/agency/errors.py -- pure logic, no database.
Runs in the default pytest suite (not marked `integration`)."""

from __future__ import annotations

import uuid

from product.agency.errors import AgencyAccessDeniedError, UnknownDelegatablePermissionError


def test_agency_access_denied_error_carries_both_ids() -> None:
    actor_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    error = AgencyAccessDeniedError(actor_id, agency_id)
    assert error.actor_user_id == actor_id
    assert error.agency_tenant_id == agency_id
    assert str(actor_id) in str(error)
    assert str(agency_id) in str(error)


def test_unknown_delegatable_permission_error_carries_resource_and_action() -> None:
    error = UnknownDelegatablePermissionError("crm.contact", "merge")
    assert error.resource == "crm.contact"
    assert error.action == "merge"
    assert "crm.contact" in str(error)
    assert "merge" in str(error)
