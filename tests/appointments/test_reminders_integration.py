"""Appointment reminder sweep -- correct-offset firing, cancellation
suppression, idempotency, contact-with-no-email skip-without-abort,
cross-tenant isolation, authorization, and audit PII exclusion
(docs/ROADMAP.md Phase 7.3). Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core.audit_log import list as list_audit_log
from core.email.provider import FakeEmailProvider
from core.rbac import RoleScope
from infra.db import tenant_session_scope
from product.agency.delegation import create_client_deny
from product.agency.provisioning import provision_agency, provision_client
from product.appointments.booking import book_appointment, staff_cancel_appointment
from product.appointments.calendars import create_calendar
from product.appointments.errors import AppointmentAccessDeniedError
from product.appointments.models import Appointment
from product.appointments.permissions import APPOINTMENT_RESOURCE
from product.appointments.reminders import REMINDER_LEAD_TIME, send_due_reminders
from product.crm.models import Contact

from tests.appointments._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _email_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """`core.email.get_email_config()` requires `SMTP_HOST`/
    `EMAIL_DEFAULT_SENDER` with no default (mirrors `tests/conversations
    /test_email_sending_integration.py`'s own identical per-test setup) --
    `send_due_reminders()` calls it unconditionally even when a `provider`
    override is supplied for the actual send, the same established shape
    `product/conversations/email_sending.py`/`product/marketing/sending.py`
    already use. Applied `autouse=True` here (rather than repeated in each
    test) since every test in this module exercises the reminder-send
    path one way or another."""
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("EMAIL_DEFAULT_SENDER", "no-reply@example.test")


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _book(tenant_id, calendar_id, actor_id, *, starts_at, email="reminded@example.com"):
    return book_appointment(
        tenant_id=tenant_id,
        calendar_id=calendar_id,
        contact_email=email,
        contact_first_name="Rem",
        contact_last_name="Inder",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        actor_user_id=actor_id,
    )


def test_reminder_fires_inside_window_not_outside() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        inside = _book(
            client.tenant_id,
            calendar.id,
            owner.id,
            starts_at=now + REMINDER_LEAD_TIME - timedelta(minutes=1),
            email="inside@example.com",
        )
        outside = _book(
            client.tenant_id,
            calendar.id,
            owner.id,
            starts_at=now + REMINDER_LEAD_TIME + timedelta(hours=1),
            email="outside@example.com",
        )
        provider = FakeEmailProvider()
        result = send_due_reminders(owner.id, client.tenant_id, now=now, provider=provider)
        assert result.reminded_count == 1
        assert inside.id in result.appointment_ids
        assert outside.id not in result.appointment_ids
        assert len(provider.sent) == 1
        assert provider.sent[0].to == ("inside@example.com",)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cancelled_appointment_never_gets_a_reminder() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        appt = _book(client.tenant_id, calendar.id, owner.id, starts_at=now + timedelta(hours=2))
        staff_cancel_appointment(owner.id, client.tenant_id, appt.id)

        provider = FakeEmailProvider()
        result = send_due_reminders(owner.id, client.tenant_id, now=now, provider=provider)
        assert appt.id not in result.appointment_ids
        assert result.reminded_count == 0
        assert provider.sent == []

        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(Appointment, appt.id)
            assert row is not None
            assert row.reminder_sent_at is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_sweeping_twice_never_double_sends() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        appt = _book(client.tenant_id, calendar.id, owner.id, starts_at=now + timedelta(hours=2))

        provider = FakeEmailProvider()
        first = send_due_reminders(owner.id, client.tenant_id, now=now, provider=provider)
        assert first.reminded_count == 1
        second = send_due_reminders(owner.id, client.tenant_id, now=now, provider=provider)
        assert second.reminded_count == 0
        assert appt.id not in second.appointment_ids
        assert len(provider.sent) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_contact_with_no_email_is_skipped_without_aborting_the_batch() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

        # Booked via the trusted-source path with a real email, then the
        # contact's own email is cleared directly -- the no-email case
        # `create_or_update_contact_from_trusted_source()` itself cannot
        # produce (it requires an email to identify the contact by), but
        # a real CRM record can still end up with no email later (e.g. a
        # manual CRM edit) -- exactly the row this sweep must skip rather
        # than crash on.
        appt_no_email = _book(
            client.tenant_id, calendar.id, owner.id, starts_at=now + timedelta(hours=1)
        )
        appt_with_email = _book(
            client.tenant_id,
            calendar.id,
            owner.id,
            starts_at=now + timedelta(hours=3),
            email="has-email@example.com",
        )

        with tenant_session_scope(client.tenant_id) as session:
            assert appt_no_email.contact_id is not None
            contact_row = session.get(Contact, appt_no_email.contact_id)
            assert contact_row is not None
            contact_row.email = None

        provider = FakeEmailProvider()
        result = send_due_reminders(owner.id, client.tenant_id, now=now, provider=provider)
        assert appt_no_email.id not in result.appointment_ids
        assert appt_with_email.id in result.appointment_ids
        assert result.reminded_count == 1
        assert len(provider.sent) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_tenant_sweep_isolation() -> None:
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_a = create_calendar(
            owner_a.id, client_a.tenant_id, name="A", owner_user_id=owner_a.id, timezone="UTC"
        )
        calendar_b = create_calendar(
            owner_b.id, client_b.tenant_id, name="B", owner_user_id=owner_b.id, timezone="UTC"
        )
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        appt_a = _book(
            client_a.tenant_id, calendar_a.id, owner_a.id, starts_at=now + timedelta(hours=1)
        )
        appt_b = _book(
            client_b.tenant_id, calendar_b.id, owner_b.id, starts_at=now + timedelta(hours=1)
        )

        provider = FakeEmailProvider()
        result_a = send_due_reminders(owner_a.id, client_a.tenant_id, now=now, provider=provider)
        assert appt_a.id in result_a.appointment_ids
        assert appt_b.id not in result_a.appointment_ids
        assert result_a.reminded_count == 1
        assert len(provider.sent) == 1
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_unauthenticated_style_unrelated_actor_denied() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(AppointmentAccessDeniedError):
            send_due_reminders(stranger.id, client.tenant_id, provider=FakeEmailProvider())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_agency_owner_reaches_own_clients_sweep_via_inherited_subtree() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        appt = _book(client.tenant_id, calendar.id, owner.id, starts_at=now + timedelta(hours=1))
        result = send_due_reminders(
            owner.id, client.tenant_id, now=now, provider=FakeEmailProvider()
        )
        assert appt.id in result.appointment_ids
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_explicit_deny_overrides_inherited_subtree_reach_for_sweep() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_client_deny(
            grantor_user_id=owner.id,
            principal_user_id=owner.id,
            tenant_id=client.tenant_id,
            resource=APPOINTMENT_RESOURCE,
            action="read",
            scope_mode=RoleScope.SELF,
        )
        with pytest.raises(AppointmentAccessDeniedError):
            send_due_reminders(owner.id, client.tenant_id, provider=FakeEmailProvider())
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_audit_metadata_never_contains_contact_pii() -> None:
    """Personal-data requirement: reminder metadata must never carry a
    contact's email/name/appointment id -- proven by reading the real,
    persisted core.audit_log row back, mirroring
    tests/marketing/test_sending_integration.py's own marker-based
    proof."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    secret_marker = "reminder-pii-marker-xyz@example.com"
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        _book(
            client.tenant_id,
            calendar.id,
            owner.id,
            starts_at=now + timedelta(hours=1),
            email=secret_marker,
        )

        send_due_reminders(owner.id, client.tenant_id, now=now, provider=FakeEmailProvider())

        entries = list_audit_log(
            client.tenant_id,
            resource_type="appointments.appointment",
            resource_id=str(client.tenant_id),
        )
        matching = [e for e in entries if e.action == "appointments.reminders.sweep"]
        assert len(matching) >= 1
        for entry in matching:
            serialized = str(entry.metadata)
            assert secret_marker not in serialized
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reminder_send_failure_leaves_reminder_sent_at_null_for_retry() -> None:
    """A failed send must never mark `reminder_sent_at` -- the row stays
    eligible for the next sweep, and the failure must not abort the rest
    of the batch (module docstring)."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        failing = _book(
            client.tenant_id,
            calendar.id,
            owner.id,
            starts_at=now + timedelta(hours=1),
            email="failing@example.com",
        )
        succeeding = _book(
            client.tenant_id,
            calendar.id,
            owner.id,
            starts_at=now + timedelta(hours=2),
            email="succeeding@example.com",
        )

        result = send_due_reminders(
            owner.id, client.tenant_id, now=now, provider=FakeEmailProvider(fail=True)
        )
        assert result.reminded_count == 0
        assert failing.id not in result.appointment_ids
        assert succeeding.id not in result.appointment_ids

        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(Appointment, failing.id)
            assert row is not None
            assert row.reminder_sent_at is None
            row2 = session.get(Appointment, succeeding.id)
            assert row2 is not None
            assert row2.reminder_sent_at is None

        # Retried on the next sweep with a working provider.
        provider = FakeEmailProvider()
        retry = send_due_reminders(owner.id, client.tenant_id, now=now, provider=provider)
        assert retry.reminded_count == 2
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
