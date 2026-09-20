"""Booking, rescheduling, cancellation -- data integrity, scheduling
correctness (including real concurrency races against real disposable
Postgres), and API security (docs/ROADMAP.md Phase 7.2). Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core.identity.sessions import issue_session
from fastapi.testclient import TestClient
from infra.db import IntegrityError, select, session_scope, tenant_session_scope
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app
from product.appointments.booking import (
    book_appointment,
    public_book_appointment,
    public_cancel_appointment,
    public_reschedule_appointment,
    resolve_booking_link,
    resolve_manage_token,
    staff_cancel_appointment,
    staff_reschedule_appointment,
)
from product.appointments.calendars import create_calendar, get_or_create_booking_link
from product.appointments.errors import (
    AppointmentSlotUnavailableError,
    AppointmentTokenInvalidError,
    AppointmentValidationError,
)
from product.appointments.models import (
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
    Appointment,
    AppointmentManageToken,
)
from product.crm.contacts import create_contact, delete_contact, get_contact

from tests.appointments._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def _slot(day: int, hour: int) -> tuple[datetime, datetime]:
    start = datetime(2026, 6, day, hour, 0, tzinfo=UTC)
    return start, start + timedelta(hours=1)


# --- Booking, reuse of CRM contacts ------------------------------------------


def test_book_appointment_reuses_crm_contact_create_or_update() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(1, 9)
        appt = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="booker@example.com",
            contact_first_name="Book",
            contact_last_name="Er",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )
        assert appt.status == STATUS_CONFIRMED
        assert appt.contact_id is not None

        contact = get_contact(owner.id, client.tenant_id, appt.contact_id)
        assert contact.email == "booker@example.com"

        # Booking again with the same email must reuse, not duplicate,
        # the contact -- create_or_update_contact_from_trusted_source()'s
        # own idempotency, exercised through this module.
        starts_at2, ends_at2 = _slot(1, 11)
        appt2 = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="booker@example.com",
            contact_first_name="Book",
            contact_last_name="Er",
            starts_at=starts_at2,
            ends_at=ends_at2,
            actor_user_id=owner.id,
        )
        assert appt2.contact_id == appt.contact_id
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_double_booking_is_rejected_by_the_database_exclude_constraint() -> None:
    """The safety-critical proof: booking the identical/overlapping slot
    on the same calendar a second time must fail with
    AppointmentSlotUnavailableError -- never a raw IntegrityError, never
    a silent double-booking."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(2, 9)
        book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="first@example.com",
            contact_first_name="First",
            contact_last_name="Booker",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )
        # Exact same slot.
        with pytest.raises(AppointmentSlotUnavailableError):
            book_appointment(
                tenant_id=client.tenant_id,
                calendar_id=calendar.id,
                contact_email="second@example.com",
                contact_first_name="Second",
                contact_last_name="Booker",
                starts_at=starts_at,
                ends_at=ends_at,
                actor_user_id=owner.id,
            )
        # Partially overlapping slot.
        overlap_start = starts_at + timedelta(minutes=30)
        overlap_end = ends_at + timedelta(minutes=30)
        with pytest.raises(AppointmentSlotUnavailableError):
            book_appointment(
                tenant_id=client.tenant_id,
                calendar_id=calendar.id,
                contact_email="third@example.com",
                contact_first_name="Third",
                contact_last_name="Booker",
                starts_at=overlap_start,
                ends_at=overlap_end,
                actor_user_id=owner.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_back_to_back_appointments_at_exact_boundary_both_succeed() -> None:
    """`[)` half-open range semantics: 09:00-10:00 and 10:00-11:00 on the
    same calendar do not overlap and must both succeed."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        first_start, first_end = _slot(3, 9)
        second_start, second_end = first_end, first_end + timedelta(hours=1)
        book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="a@example.com",
            contact_first_name="A",
            contact_last_name="Booker",
            starts_at=first_start,
            ends_at=first_end,
            actor_user_id=owner.id,
        )
        second = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="b@example.com",
            contact_first_name="B",
            contact_last_name="Booker",
            starts_at=second_start,
            ends_at=second_end,
            actor_user_id=owner.id,
        )
        assert second.starts_at == second_start
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cancelled_slot_can_be_rebooked() -> None:
    """The partial WHERE (status = 'confirmed') predicate: a cancelled
    appointment's former slot is available again."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(4, 9)
        first = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="a@example.com",
            contact_first_name="A",
            contact_last_name="Booker",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )
        staff_cancel_appointment(owner.id, client.tenant_id, first.id)

        second = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="b@example.com",
            contact_first_name="B",
            contact_last_name="Booker",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )
        assert second.status == STATUS_CONFIRMED
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_concurrent_double_booking_attempt_only_one_wins() -> None:
    """Real concurrency against real disposable Postgres: two threads
    race to book the *identical* slot on the same calendar, synchronized
    to start together via threading.Barrier -- the database EXCLUDE
    constraint (not application logic) must let exactly one through."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(5, 9)
        barrier = threading.Barrier(2)
        results: dict[str, tuple[str, object]] = {}

        def _attempt(label: str, email: str) -> None:
            barrier.wait()
            try:
                appt = book_appointment(
                    tenant_id=client.tenant_id,
                    calendar_id=calendar.id,
                    contact_email=email,
                    contact_first_name=label,
                    contact_last_name="Racer",
                    starts_at=starts_at,
                    ends_at=ends_at,
                    actor_user_id=owner.id,
                )
                results[label] = ("ok", appt)
            except AppointmentSlotUnavailableError as exc:
                results[label] = ("failed", exc)

        thread_a = threading.Thread(target=_attempt, args=("a", "racer-a@example.com"))
        thread_b = threading.Thread(target=_attempt, args=("b", "racer-b@example.com"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=30)
        thread_b.join(timeout=30)

        outcomes = sorted([results["a"][0], results["b"][0]])
        assert outcomes == ["failed", "ok"], results

        with tenant_session_scope(client.tenant_id) as session:
            from sqlalchemy import select

            confirmed = (
                session.execute(
                    select(Appointment).where(
                        Appointment.tenant_id == client.tenant_id,
                        Appointment.calendar_id == calendar.id,
                        Appointment.status == STATUS_CONFIRMED,
                    )
                )
                .scalars()
                .all()
            )
            assert len(confirmed) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_cross_tenant_calendar_reference_rejected_by_database_constraint_directly() -> None:
    """The composite FK on appointments.calendar_id -- proven by
    bypassing the service layer entirely."""
    owner_a = make_user()
    owner_b = make_user()
    agency_a, client_a = _agency_and_client(owner_a.id)
    agency_b, client_b = _agency_and_client(owner_b.id)
    try:
        calendar_b = create_calendar(
            owner_b.id, client_b.tenant_id, name="B Only", owner_user_id=owner_b.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(6, 9)
        with pytest.raises(IntegrityError):
            with tenant_session_scope(client_a.tenant_id) as session:
                row = Appointment(
                    tenant_id=client_a.tenant_id,
                    calendar_id=calendar_b.id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    status=STATUS_CONFIRMED,
                )
                session.add(row)
                session.flush()
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


def test_deleting_contact_unlinks_appointment_but_keeps_booking_history() -> None:
    """ON DELETE SET NULL (contact_id), column-scoped -- the fix for the
    defect class the deferred Phase 4 CRM bug demonstrated."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(owner.id, client.tenant_id, first_name="Soon", last_name="Gone")
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(7, 9)
        appt = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email=contact.email or "unlink@example.com",
            contact_first_name="Soon",
            contact_last_name="Gone",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )
        assert appt.contact_id is not None

        delete_contact(owner.id, client.tenant_id, appt.contact_id)

        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(Appointment, appt.id)
            assert row is not None
            assert row.contact_id is None
            assert row.status == STATUS_CONFIRMED
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Cancel / reschedule, state transitions ----------------------------------


def test_reschedule_and_cancel_state_transitions() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(8, 9)
        appt = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="reschedule@example.com",
            contact_first_name="Re",
            contact_last_name="Schedule",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )
        new_start, new_end = _slot(8, 14)
        rescheduled = staff_reschedule_appointment(
            owner.id, client.tenant_id, appt.id, new_starts_at=new_start, new_ends_at=new_end
        )
        assert rescheduled.starts_at == new_start

        cancelled = staff_cancel_appointment(owner.id, client.tenant_id, appt.id)
        assert cancelled.status == STATUS_CANCELLED

        # Cancel-then-cancel rejected.
        with pytest.raises(AppointmentValidationError):
            staff_cancel_appointment(owner.id, client.tenant_id, appt.id)
        # Reschedule-a-cancelled-appointment rejected.
        with pytest.raises(AppointmentValidationError):
            staff_reschedule_appointment(
                owner.id, client.tenant_id, appt.id, new_starts_at=new_start, new_ends_at=new_end
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_reschedule_into_an_occupied_slot_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        occupied_start, occupied_end = _slot(9, 9)
        book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="occupant@example.com",
            contact_first_name="Occ",
            contact_last_name="Upant",
            starts_at=occupied_start,
            ends_at=occupied_end,
            actor_user_id=owner.id,
        )
        movable_start, movable_end = _slot(9, 14)
        movable = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="movable@example.com",
            contact_first_name="Mov",
            contact_last_name="Able",
            starts_at=movable_start,
            ends_at=movable_end,
            actor_user_id=owner.id,
        )
        with pytest.raises(AppointmentSlotUnavailableError):
            staff_reschedule_appointment(
                owner.id,
                client.tenant_id,
                movable.id,
                new_starts_at=occupied_start,
                new_ends_at=occupied_end,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_concurrent_cancel_and_reschedule_on_same_appointment_is_serialized() -> None:
    """Real concurrency: one thread cancels, another reschedules, the
    *same* appointment, synchronized via threading.Barrier. The row lock
    (with_for_update=True) must serialize these -- the final state is
    coherent (either cancelled, or rescheduled-and-still-confirmed), never
    torn, and never both succeeding into a contradictory state."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        starts_at, ends_at = _slot(10, 9)
        appt = book_appointment(
            tenant_id=client.tenant_id,
            calendar_id=calendar.id,
            contact_email="race@example.com",
            contact_first_name="Race",
            contact_last_name="Condition",
            starts_at=starts_at,
            ends_at=ends_at,
            actor_user_id=owner.id,
        )
        new_start, new_end = _slot(10, 15)

        barrier = threading.Barrier(2)
        results: dict[str, tuple[str, object]] = {}

        def _cancel() -> None:
            barrier.wait()
            try:
                cancelled = staff_cancel_appointment(owner.id, client.tenant_id, appt.id)
                results["cancel"] = ("ok", cancelled)
            except AppointmentValidationError as exc:
                results["cancel"] = ("failed", exc)

        def _reschedule() -> None:
            barrier.wait()
            try:
                results["reschedule"] = (
                    "ok",
                    staff_reschedule_appointment(
                        owner.id,
                        client.tenant_id,
                        appt.id,
                        new_starts_at=new_start,
                        new_ends_at=new_end,
                    ),
                )
            except (AppointmentValidationError, AppointmentSlotUnavailableError) as exc:
                results["reschedule"] = ("failed", exc)

        thread_cancel = threading.Thread(target=_cancel)
        thread_reschedule = threading.Thread(target=_reschedule)
        thread_cancel.start()
        thread_reschedule.start()
        thread_cancel.join(timeout=30)
        thread_reschedule.join(timeout=30)

        # Corrected assertion (the original "exactly one succeeds" claim
        # was wrong -- caught by this test itself failing deterministically,
        # not assumed): `staff_cancel_appointment()`'s only precondition is
        # "not already cancelled", which a concurrent *reschedule* never
        # triggers (reschedule never sets status to "cancelled") -- so
        # cancel always succeeds here, regardless of which operation's row
        # lock is acquired first. What genuinely depends on lock-acquisition
        # order is *reschedule*: if it wins the lock first, it succeeds (the
        # row is still "confirmed") and cancel then cancels the *rescheduled*
        # appointment; if cancel wins first, reschedule's own "must be
        # confirmed" precondition correctly rejects it. Both orderings are
        # safe and serialized (proven by `with_for_update=True` on both
        # sides) -- neither is a torn/lost-update state, they are simply two
        # different, both-legitimate final outcomes of a genuine race. The
        # real invariant this test proves is that the final row state is
        # *always* fully coherent with whichever ordering actually occurred,
        # never a mix of the two (e.g. cancelled status with a half-applied
        # reschedule, or vice versa).
        assert results["cancel"][0] == "ok", results
        assert results["reschedule"][0] in ("ok", "failed"), results

        with tenant_session_scope(client.tenant_id) as session:
            row = session.get(Appointment, appt.id)
            assert row is not None
            # Cancel always wins the race in the end (nothing ever blocks
            # it here) -- the appointment is always cancelled by the time
            # both threads have finished, regardless of ordering.
            assert row.status == STATUS_CANCELLED
            if results["reschedule"][0] == "ok":
                # Reschedule's row lock was acquired first: its new time
                # values are the ones cancel then found and cancelled.
                assert row.starts_at == new_start
                assert row.ends_at == new_end
            else:
                # Cancel's row lock was acquired first: reschedule's own
                # "must be confirmed" precondition correctly rejected it
                # against the already-cancelled row, so the appointment's
                # time values are untouched, exactly as originally booked.
                assert row.starts_at == starts_at
                assert row.ends_at == ends_at
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


# --- Public booking/manage ----------------------------------------------------


def test_public_booking_and_manage_flow() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        link_token = get_or_create_booking_link(owner.id, client.tenant_id, calendar.id)
        resolved_link = resolve_booking_link(link_token)
        assert resolved_link is not None
        assert resolved_link.calendar_id == calendar.id

        starts_at, ends_at = _slot(11, 9)
        appt = public_book_appointment(
            link_token,
            contact_email="public@example.com",
            contact_first_name="Pub",
            contact_last_name="Lic",
            starts_at=starts_at,
            ends_at=ends_at,
        )
        assert appt.status == STATUS_CONFIRMED

        assert resolve_booking_link("not-a-real-token") is None
        assert resolve_booking_link("") is None

        with pytest.raises(AppointmentTokenInvalidError):
            public_book_appointment(
                "not-a-real-token",
                contact_email="x@example.com",
                contact_first_name="X",
                contact_last_name="Y",
                starts_at=starts_at,
                ends_at=ends_at,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_public_cancel_and_reschedule_via_manage_token() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        link_token = get_or_create_booking_link(owner.id, client.tenant_id, calendar.id)
        starts_at, ends_at = _slot(12, 9)
        appt = public_book_appointment(
            link_token,
            contact_email="manage@example.com",
            contact_first_name="Man",
            contact_last_name="Age",
            starts_at=starts_at,
            ends_at=ends_at,
        )
        # Find the real manage_token via direct DB lookup (it is not
        # returned by public_book_appointment() -- delivered out-of-band,
        # e.g. by a confirmation email, outside this phase's scope).
        with session_scope() as session:
            mapping = (
                session.execute(
                    select(AppointmentManageToken).where(
                        AppointmentManageToken.appointment_id == appt.id
                    )
                )
                .scalars()
                .one()
            )
            manage_token = mapping.manage_token

        resolved = resolve_manage_token(manage_token)
        assert resolved is not None
        assert resolved.id == appt.id

        new_start, new_end = _slot(12, 15)
        rescheduled = public_reschedule_appointment(
            manage_token, new_starts_at=new_start, new_ends_at=new_end
        )
        assert rescheduled.starts_at == new_start

        cancelled = public_cancel_appointment(manage_token)
        assert cancelled.status == STATUS_CANCELLED

        assert resolve_manage_token("unknown-token") is None
        with pytest.raises(AppointmentTokenInvalidError):
            public_cancel_appointment("unknown-token")
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_manage_token_and_booking_link_never_cross_tenant_boundaries() -> None:
    """IDOR proof: tenant A's real, syntactically-valid manage_token and
    booking-link token each resolve only to tenant A's own data --
    tenant B's booking link is a structurally different token (no shared
    prefix/derivation an attacker could pivot from), and there is no API
    parameter (public routes take only the token, never a tenant_id) a
    caller could use to redirect either token to tenant B."""
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
        link_token_a = get_or_create_booking_link(owner_a.id, client_a.tenant_id, calendar_a.id)
        link_token_b = get_or_create_booking_link(owner_b.id, client_b.tenant_id, calendar_b.id)
        assert link_token_a != link_token_b

        starts_at, ends_at = _slot(13, 9)
        appt_a = public_book_appointment(
            link_token_a,
            contact_email="isolated@example.com",
            contact_first_name="Iso",
            contact_last_name="Lated",
            starts_at=starts_at,
            ends_at=ends_at,
        )

        resolved_link_a = resolve_booking_link(link_token_a)
        assert resolved_link_a is not None
        assert resolved_link_a.tenant_id == client_a.tenant_id
        assert resolved_link_a.tenant_id != client_b.tenant_id

        with session_scope() as session:
            mapping = (
                session.execute(
                    select(AppointmentManageToken).where(
                        AppointmentManageToken.appointment_id == appt_a.id
                    )
                )
                .scalars()
                .one()
            )
            manage_token_a = mapping.manage_token

        resolved_appt = resolve_manage_token(manage_token_a)
        assert resolved_appt is not None
        assert resolved_appt.tenant_id == client_a.tenant_id
        assert resolved_appt.tenant_id != client_b.tenant_id

        # A structurally different, guessed token never resolves.
        assert resolve_manage_token(manage_token_a[:-4] + "0000") is None
    finally:
        cleanup_tenant_tree(
            client_a.tenant_id, agency_a.tenant_id, client_b.tenant_id, agency_b.tenant_id
        )
        cleanup_users(owner_a.id, owner_b.id)


# --- HTTP layer: rate limiting, non-enumeration, pagination ------------------


def test_public_book_route_rate_limited() -> None:
    from infra.ratelimit.config import get_ratelimit_config

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    import os

    old_value = os.environ.get("RATE_LIMIT_REQUESTS_PER_WINDOW")
    os.environ["RATE_LIMIT_REQUESTS_PER_WINDOW"] = "2"
    get_ratelimit_config.cache_clear()
    try:
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        link_token = get_or_create_booking_link(owner.id, client.tenant_id, calendar.id)
        api = TestClient(create_app())
        statuses = []
        for i in range(4):
            starts_at, ends_at = _slot(14, 9 + i)
            resp = api.post(
                f"/v1/appointments/book/{link_token}",
                json={
                    "contact_email": f"rl-{i}@example.com",
                    "contact_first_name": "RL",
                    "contact_last_name": f"{i}",
                    "starts_at": starts_at.isoformat(),
                    "ends_at": ends_at.isoformat(),
                },
            )
            statuses.append(resp.status_code)
        assert 429 in statuses, statuses
    finally:
        if old_value is None:
            os.environ.pop("RATE_LIMIT_REQUESTS_PER_WINDOW", None)
        else:
            os.environ["RATE_LIMIT_REQUESTS_PER_WINDOW"] = old_value
        get_ratelimit_config.cache_clear()
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_public_book_route_unknown_token_over_http_is_non_enumerating_404() -> None:
    api = TestClient(create_app())
    starts_at, ends_at = _slot(15, 9)
    response = api.post(
        "/v1/appointments/book/totally-unknown-token",
        json={
            "contact_email": "x@example.com",
            "contact_first_name": "X",
            "contact_last_name": "Y",
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
        },
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "resource not found."}


def test_double_booking_over_http_returns_409() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        headers = _auth_headers(owner.id)
        api = TestClient(create_app())
        calendar_resp = api.post(
            f"/v1/appointments/tenants/{client.tenant_id}/calendars",
            json={"name": "HTTP Cal", "owner_user_id": str(owner.id), "timezone": "UTC"},
            headers=headers,
        )
        assert calendar_resp.status_code == 201
        calendar_id = calendar_resp.json()["id"]

        starts_at, ends_at = _slot(16, 9)
        body = {
            "calendar_id": calendar_id,
            "contact_email": "http@example.com",
            "contact_first_name": "H",
            "contact_last_name": "TTP",
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
        }
        first = api.post(
            f"/v1/appointments/tenants/{client.tenant_id}/appointments", json=body, headers=headers
        )
        assert first.status_code == 201
        second = api.post(
            f"/v1/appointments/tenants/{client.tenant_id}/appointments", json=body, headers=headers
        )
        assert second.status_code == 409
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_available_slots_route_rejects_oversized_date_range() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        headers = _auth_headers(owner.id)
        api = TestClient(create_app())
        calendar = create_calendar(
            owner.id, client.tenant_id, name="Cal", owner_user_id=owner.id, timezone="UTC"
        )
        resp = api.get(
            f"/v1/appointments/tenants/{client.tenant_id}/calendars/{calendar.id}/available-slots",
            params={
                "date_from": "2026-01-01",
                "date_to": "2026-12-31",
                "slot_duration_minutes": 30,
            },
            headers=headers,
        )
        assert resp.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_unauthenticated_staff_route_rejected() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        api = TestClient(create_app())
        resp = api.get(f"/v1/appointments/tenants/{client.tenant_id}/calendars")
        assert resp.status_code == 401
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
