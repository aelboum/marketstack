"""Cross-domain: `appointments.appointment.completed` ->
`product/reputation/event_handlers.py`'s new subscriber -> a real,
observable `ReviewRequest` (docs/ROADMAP.md Phase 23, "Customer Lifecycle
Loop"). Real disposable Postgres. Marked `integration`, excluded from the
default `pytest` run.

Combines `tests.appointments._cleanup` (this test creates real
`appointments.*` rows) with `tests.reputation._cleanup`'s own
`reputation.*` table cleanup -- mirrors the identical one-off combined-
cleanup pattern `tests/automation/test_dispatcher_integration.py`'s own
Phase 22 cross-domain test already established for the symmetric
websites/automation case.

Imports both `product.appointments.event_handlers` (for
`appointments.calendar`/`appointments.appointment` permission grants --
this file books/completes real appointments) and
`product.reputation.event_handlers` (for `reputation.review_request`
grants **and** this phase's own new `appointments.appointment.completed`
subscriber -- without this import, the subscriber this module actually
tests would never even be registered) -- mirrors
`tests/reputation/_cleanup.py`'s own identical, already-documented
precedent for a package "with no HTTP-level test of its own to trigger"
registration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core.audit_log import list as list_audit_log
from infra.db import tenant_session_scope
from product.agency.delegation import create_client_deny
from product.agency.provisioning import provision_agency, provision_client
from product.appointments import event_handlers as _appointments_event_handlers  # noqa: F401
from product.appointments.booking import book_appointment, staff_complete_appointment
from product.appointments.calendars import create_calendar
from product.reputation import event_handlers as _reputation_event_handlers  # noqa: F401
from product.reputation.permissions import REVIEW_REQUEST_RESOURCE
from product.reputation.review_requests import list_review_requests
from sqlalchemy import text

from tests.appointments._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _cleanup_reputation_rows(tenant_id: uuid.UUID) -> None:
    """One-off extension for this cross-domain test -- see module
    docstring. `tests.appointments._cleanup` (used below for everything
    else) has no reason to know about `reputation.*`."""
    with tenant_session_scope(tenant_id) as session:
        for table in ("review_responses", "reviews", "review_requests"):
            session.execute(
                text(f"DELETE FROM reputation.{table} WHERE tenant_id = :t"), {"t": str(tenant_id)}
            )


def _booked(owner_id, tenant_id, day: int):
    calendar = create_calendar(
        owner_id, tenant_id, name="Cal", owner_user_id=owner_id, timezone="UTC"
    )
    starts_at = datetime(2026, 8, day, 9, tzinfo=UTC)
    ends_at = starts_at + timedelta(hours=1)
    return book_appointment(
        tenant_id=tenant_id,
        calendar_id=calendar.id,
        contact_email=f"{_name('lead')}@example.com",
        contact_first_name="Life",
        contact_last_name="Cycle",
        starts_at=starts_at,
        ends_at=ends_at,
        actor_user_id=owner_id,
    )


def test_completing_an_appointment_automatically_creates_a_real_review_request() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        appt = _booked(owner.id, client.tenant_id, 1)
        staff_complete_appointment(owner.id, client.tenant_id, appt.id)

        requests = list_review_requests(owner.id, client.tenant_id, contact_id=appt.contact_id)
        assert len(requests) == 1
        assert requests[0].contact_id == appt.contact_id
        assert requests[0].requested_by_user_id == owner.id
    finally:
        _cleanup_reputation_rows(client.tenant_id)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_completing_an_appointment_with_no_linked_contact_creates_nothing() -> None:
    """Honest skip, not an error -- an appointment can legitimately have
    no contact (deleted via ON DELETE SET NULL, or never linked)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        appt = _booked(owner.id, client.tenant_id, 2)
        from product.crm.contacts import delete_contact

        assert appt.contact_id is not None
        delete_contact(owner.id, client.tenant_id, appt.contact_id)

        staff_complete_appointment(owner.id, client.tenant_id, appt.id)

        requests = list_review_requests(owner.id, client.tenant_id)
        assert requests == []
    finally:
        _cleanup_reputation_rows(client.tenant_id)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_review_request_creation_failure_never_aborts_the_completion_call() -> None:
    """The one real, exercised proof of the "never propagate" discipline
    (module docstring of `product/reputation/event_handlers.py`): deny
    the completing actor's own `reputation.review_request:create`
    permission first, so `create_review_request()` genuinely raises --
    `staff_complete_appointment()` must still return successfully, and
    the appointment must still be `completed`, not rolled back."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        appt = _booked(owner.id, client.tenant_id, 3)
        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource=REVIEW_REQUEST_RESOURCE,
            action="create",
        )

        completed = staff_complete_appointment(owner.id, client.tenant_id, appt.id)
        assert completed.status == "completed"

        requests = list_review_requests(owner.id, client.tenant_id, contact_id=appt.contact_id)
        assert requests == []

        entries = list_audit_log(
            client.tenant_id,
            resource_type="reputation.review_request",
            resource_id=str(appt.contact_id),
        )
        matching = [
            e for e in entries if e.action == "reputation.review_request.auto_create_failed"
        ]
        assert len(matching) == 1
        assert matching[0].entry_metadata == {"reason": "ReputationAccessDeniedError"}
    finally:
        # `core.deny_grants` is cleaned up by `cleanup_tenant_tree()`
        # itself (`tests/agency/_cleanup.py`'s own table list already
        # includes it) -- no separate deletion needed here.
        _cleanup_reputation_rows(client.tenant_id)
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
