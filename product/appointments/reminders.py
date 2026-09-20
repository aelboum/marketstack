"""Appointment reminders (docs/ROADMAP.md Phase 7.3).

**No native scheduled/deferred job support exists to build a real cron-style
sweep on** -- verified directly, not assumed:

* `infra.jobs.enqueue_job(function_name, payload=None, *, pool=None,
  queue_name=None) -> str` does not expose arq's own `_defer_until`/
  `_defer_by` kwargs (confirmed present on the underlying
  `arq.connections.ArqRedis.enqueue_job` by direct introspection, but not
  threaded through `infra.jobs`'s own narrower signature) -- there is no
  sanctioned way to schedule a job for a future time.
* `core.tenancy` exposes no tenant-enumeration function -- only
  `find_tenants_by_name(name)` (a name search). Combined with RLS (an
  untenanted `session_scope()` read against any tenant-owned table
  returns zero rows for every tenant, not "all tenants"), there is no
  sanctioned way for product runtime code to enumerate tenants and sweep
  across all of them; the restricted application DB role cannot bypass
  RLS, and using the privileged migration role from runtime code would be
  a materially larger, unauthorized exception.

Both are genuine SaaS-OS capability gaps, not implemented around here.

**Resulting, honest design**: `send_due_reminders()` is a real, correct,
**per-tenant, on-demand** sweep -- not a global cron loop pretending to be
one. `product/appointments/routes.py`'s
`POST /v1/appointments/tenants/{tenant_id}/reminders/sweep` is this
function's only caller in this codebase. The periodic, cross-tenant
*triggering* of that endpoint (e.g. an external scheduler calling it once
per tenant on a fixed interval, authenticated via a
`core.identity.create_service_account()` credential -- an already-existing
Category A capability, no new mechanism) is explicitly an
operational/deployment concern outside this product's own code, not
something this module fakes.

**Idempotency and cancellation suppression both fall out of one filter**:
the sweep only ever selects rows where `status = 'confirmed' AND
reminder_sent_at IS NULL AND starts_at` is inside the reminder window.
Once a reminder is sent, `reminder_sent_at` is set and the row is excluded
from every later sweep (idempotent -- no dedicated "already sent" branch
needed). A cancelled appointment fails `status = 'confirmed'` immediately
and is silently skipped by the same filter -- no separate
cancellation-suppression code path exists, or is needed.

**`reminder_sent_at` is written only after the outbound email actually
succeeds** -- mirrors `product/conversations/email_sending.py`'s own
"no message row for a failed send" discipline. A send failure for one
appointment leaves that row's `reminder_sent_at` NULL (retried on the
next sweep) and does not abort the rest of the batch -- one bad recipient
must never block every other tenant appointment's reminder in the same
sweep.

**The sweep actor needs both `appointments.appointment:read` (checked
here) and `crm.contact:read` (checked inside `product.crm.contacts
.get_contact()`, called per-row) in `tenant_id`** -- a real, disclosed
consequence of reusing CRM's own published, authorized read function
(`docs/ADR/0005-...`) rather than reading `crm.contacts` directly, which
this module is not permitted to do at all.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from core.audit_log import ActorType, AuditOutcome, record
from core.email import EmailMessage, get_email_config, send_email
from core.email.errors import EmailConfigurationError, EmailProviderError, InvalidEmailAddressError
from core.email.provider import EmailProvider
from infra.db import select, tenant_session_scope

from product.appointments.models import STATUS_CONFIRMED, Appointment
from product.appointments.permissions import APPOINTMENT_RESOURCE, require
from product.crm.contacts import get_contact
from product.crm.errors import CrmReferenceNotFoundError

# Not configurable per-tenant this phase -- a disclosed simplification.
# 24 hours gives a booked contact a full day's notice without this sweep
# needing sub-hour scheduling precision it structurally cannot have (see
# module docstring: this is an on-demand, not a cron, sweep).
REMINDER_LEAD_TIME = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class RemindersSweepResult:
    reminded_count: int
    appointment_ids: list[uuid.UUID] = field(default_factory=list)


def send_due_reminders(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    now: datetime | None = None,
    provider: EmailProvider | None = None,
) -> RemindersSweepResult:
    """Send a reminder email for every confirmed appointment in
    `tenant_id` starting within `REMINDER_LEAD_TIME` that has not already
    had one sent. See module docstring for the idempotency/cancellation/
    partial-failure discipline. `now` defaults to the real current UTC
    instant; the parameter exists only so tests can pin the sweep window
    deterministically (mirrors `core.identity.accept_invitation()`'s own
    `now` parameter). `provider` mirrors `product/conversations
    /email_sending.py::send_email_message()`'s identical parameter --
    `None` means `core.email`'s own real default (SMTP); tests pass
    `core.email.provider.FakeEmailProvider()` instead, exactly as that
    module's own tests do."""
    require(actor_user_id, tenant_id, resource=APPOINTMENT_RESOURCE, action="read")
    current = now if now is not None else datetime.now(UTC)
    window_end = current + REMINDER_LEAD_TIME

    config = get_email_config()
    if not config.default_sender:
        raise EmailConfigurationError("EMAIL_DEFAULT_SENDER is not set.")

    with tenant_session_scope(tenant_id) as session:
        due_rows = (
            session.execute(
                select(Appointment).where(
                    Appointment.tenant_id == tenant_id,
                    Appointment.status == STATUS_CONFIRMED,
                    Appointment.reminder_sent_at.is_(None),
                    Appointment.starts_at > current,
                    Appointment.starts_at <= window_end,
                )
            )
            .scalars()
            .all()
        )
        for row in due_rows:
            session.expunge(row)

    reminded_ids: list[uuid.UUID] = []
    for appointment in due_rows:
        if appointment.contact_id is None:
            # SET NULL (contact_id) already ran, or the appointment was
            # never linked to a contact -- nothing to send, skip.
            continue
        try:
            contact = get_contact(actor_user_id, tenant_id, appointment.contact_id)
        except CrmReferenceNotFoundError:
            continue
        if not contact.email:
            continue

        message = EmailMessage(
            sender=config.default_sender,
            to=(contact.email,),
            subject="Appointment reminder",
            text_body=(
                f"This is a reminder that you have an appointment scheduled for "
                f"{appointment.starts_at.isoformat()}."
            ),
        )
        try:
            send_email(message, provider=provider)
        except (EmailConfigurationError, EmailProviderError, InvalidEmailAddressError):
            # Leave reminder_sent_at NULL -- retried on the next sweep.
            # Never aborts the rest of this batch (module docstring).
            continue

        with tenant_session_scope(tenant_id) as session:
            row = session.get(Appointment, appointment.id)
            if row is not None and row.tenant_id == tenant_id and row.reminder_sent_at is None:
                row.reminder_sent_at = current
        reminded_ids.append(appointment.id)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="appointments.reminders.sweep",
        resource_type="appointments.appointment",
        resource_id=str(tenant_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"reminded_count": len(reminded_ids), "tenant_id": str(tenant_id)},
    )
    return RemindersSweepResult(reminded_count=len(reminded_ids), appointment_ids=reminded_ids)


__all__ = ["REMINDER_LEAD_TIME", "RemindersSweepResult", "send_due_reminders"]
