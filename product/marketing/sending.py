"""Campaign send orchestration (docs/ROADMAP.md Phase 6.1's own core
acceptance criterion: "a segmented campaign sends correctly to its
matching audience and respects suppression").

**Enrollment (`start_campaign_send`) vs. actual send (the job handler)
are two separate steps**, on purpose: enrollment resolves the segment and
creates one `campaign_recipients` row per matching contact -- marking an
already-suppressed contact `"suppressed"` immediately, so a paused-and-
resumed send can never accidentally attempt them (the hard gate applies
at enrollment time, not only at send time). The job handler then
processes every still-`"pending"` row, re-checking suppression again for
each one (a contact can unsubscribe *between* enrollment and their turn
in the batch) -- the gate is enforced at both moments, not just one.

**No CRM PII duplicated onto the recipient row**: `campaign_recipients`
stores only `contact_id`, never a copy of the contact's email/phone.
Every actual send re-reads the contact's current address via
`product.crm.contacts.get_contact()` (CRM's own published, already-
authorizing function --
`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`),
which needs a real `actor_user_id` to authorize against; the enrolling
actor's id is threaded through the job payload for exactly this reason
(`payload.data["actor_user_id"]`, mirroring `product/crm/imports.py`'s
own identical pattern) -- there is no "system actor" concept invented
here, the job runs, and is authorized, as the user who started the send.

**Idempotency**: `infra.jobs` is at-least-once (no exactly-once claim
exists anywhere in `saas-os` -- confirmed by this codebase's own existing
convention, e.g. `product/crm/imports.py`'s own identical framing). If
this job were retried after a partial run, `campaign_recipients.status`
already being `"sent"`/`"failed"`/`"suppressed"` (not `"pending"`) for
some rows is what prevents a double-send on retry -- the job handler
only ever processes rows still `"pending"`, never re-iterates the full
segment. No `core.idempotency` key is used here; the recipient table's
own status column already serves that purpose, exactly the way
`crm.import_jobs`' own counters did for the CRM import job.

**Mid-send cancellation**: the job handler re-reads the campaign's own
`status` before processing *each* recipient, not just once at job start.
`product/marketing/campaigns.py::cancel_campaign()` (called from a
separate request while this job is running) sets `status="cancelled"`;
the next iteration of this loop observes that and stops, leaving
already-`"sent"`/`"failed"` recipients untouched and the rest `"pending"`
-- the literal mechanism behind `docs/ROADMAP.md` Phase 6.1's Rollback
text ("a bad campaign can be paused mid-send").

**Provider injection for tests, not for production**: `_run_campaign_send_job`
takes optional `email_provider`/`sms_provider` keyword arguments (both
default `None`) purely so tests can inject `FakeEmailProvider`/
`FakeSmsProvider` by calling this function directly (mirroring
`product/crm/imports.py::_run_import_job`'s own directly-callable-in-tests
shape, and `product/conversations/email_sending.py::send_email_message()`'s
own `provider=None` parameter). The real, registered `infra.jobs` handler
(`CAMPAIGN_SEND_JOB_FUNCTIONS`) is called by the worker with only a
`payload` argument -- these two keyword arguments are never supplied at
real invocation time, so production always uses the real default
`core.email` provider for the `"email"` channel, and -- because no real
SMS provider is configured anywhere in this product yet (`docs/ROADMAP.md`
Phase 6.2, deliberately PARTIAL, see `product/marketing/sms.py`) -- every
`"sms"`-channel recipient fails with a clear, per-recipient
`"sms_provider_not_configured"` reason in production today, exactly
mirroring how a misconfigured `EMAIL_DEFAULT_SENDER` fails the email
channel rather than silently succeeding.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from core.audit_log import ActorType, AuditOutcome, record
from core.email import EmailMessage, get_email_config, send_email
from core.email.errors import EmailConfigurationError, EmailProviderError, InvalidEmailAddressError
from core.email.provider import EmailProvider
from infra.db import select, tenant_session_scope
from infra.jobs import TenantJobPayload, enqueue_job, register_job

from product.crm.contacts import get_contact
from product.crm.errors import CrmAccessDeniedError, CrmReferenceNotFoundError
from product.marketing.errors import MarketingReferenceNotFoundError, MarketingValidationError
from product.marketing.models import (
    CHANNEL_EMAIL,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_PENDING,
    RECIPIENT_STATUS_SENT,
    RECIPIENT_STATUS_SUPPRESSED,
    STATUS_CANCELLED,
    STATUS_DRAFT,
    STATUS_SENDING,
    STATUS_SENT,
    MarketingCampaign,
    MarketingCampaignRecipient,
    MarketingRecipientTrackingToken,
)
from product.marketing.permissions import CAMPAIGN_RESOURCE, require
from product.marketing.segmentation import parse_segment_query, resolve_segment
from product.marketing.sms import SmsProvider, SmsProviderError, send_campaign_sms
from product.marketing.suppressions import is_suppressed


@dataclass(frozen=True, slots=True)
class CampaignSendStarted:
    campaign_id: uuid.UUID
    recipient_count: int
    suppressed_count: int
    job_id: str


async def start_campaign_send(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    queue_name: str | None = None,
) -> CampaignSendStarted:
    """Authorize, resolve the segment, enroll every matching contact as a
    `campaign_recipients` row, transition the campaign to `"sending"`,
    and enqueue the real background job. The one entrypoint a route
    calls."""
    require(actor_user_id, tenant_id, resource=CAMPAIGN_RESOURCE, action="update")

    with tenant_session_scope(tenant_id) as session:
        campaign = session.get(MarketingCampaign, campaign_id)
        if campaign is None or campaign.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("campaign", campaign_id)
        if campaign.status != STATUS_DRAFT:
            raise MarketingValidationError(
                f"campaign {campaign_id} can only be sent from 'draft' status "
                f"(currently {campaign.status!r})."
            )
        segment_query = parse_segment_query(campaign.segment_query)
        channel = campaign.channel

    contacts = resolve_segment(actor_user_id, tenant_id, segment_query)

    suppressed_count = 0
    with tenant_session_scope(tenant_id) as session:
        recipients: list[MarketingCampaignRecipient] = []
        for contact in contacts:
            suppressed = is_suppressed(tenant_id, contact.id, channel)
            if suppressed:
                suppressed_count += 1
            recipient = MarketingCampaignRecipient(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                contact_id=contact.id,
                status=RECIPIENT_STATUS_SUPPRESSED if suppressed else RECIPIENT_STATUS_PENDING,
            )
            session.add(recipient)
            recipients.append(recipient)
        session.flush()

        # Phase 6.5: one globally-unique tracking token per recipient,
        # backing the public open/click endpoints. Written via this same
        # tenant_session_scope() session -- functionally identical to a
        # plain session_scope() write here, since
        # marketing.recipient_tracking_tokens carries no RLS policy for
        # any session variable to matter to (see migration
        # 0023_marketing_tracking's own docstring).
        for recipient in recipients:
            session.add(
                MarketingRecipientTrackingToken(
                    tracking_token=secrets.token_urlsafe(32),
                    tenant_id=tenant_id,
                    recipient_id=recipient.id,
                )
            )
        session.flush()

        campaign = session.get(MarketingCampaign, campaign_id)
        assert campaign is not None
        campaign.status = STATUS_SENDING
        session.flush()

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.campaign.send_started",
        resource_type="marketing.campaign",
        resource_id=str(campaign_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={
            "channel": channel,
            "recipient_count": len(contacts),
            "suppressed_count": suppressed_count,
        },
    )

    payload = TenantJobPayload(
        tenant_id=str(tenant_id),
        data={"campaign_id": str(campaign_id), "actor_user_id": str(actor_user_id)},
    )
    job_id = await enqueue_job(_run_campaign_send_job.__name__, payload, queue_name=queue_name)
    return CampaignSendStarted(
        campaign_id=campaign_id,
        recipient_count=len(contacts),
        suppressed_count=suppressed_count,
        job_id=job_id,
    )


def _mark_recipient(
    tenant_id: uuid.UUID, recipient_id: uuid.UUID, status: str, error: str | None
) -> None:
    """Only ever called with `"failed"`/`"suppressed"` -- the `"sent"`
    outcome is recorded inline, separately, by `_process_one_recipient()`
    itself once the real send has actually succeeded (never speculatively
    here), so this helper never touches `sent_at`."""
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingCampaignRecipient, recipient_id)
        if row is None or row.tenant_id != tenant_id:
            return
        row.status = status
        row.error = error
        session.flush()


def _process_one_recipient(
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    channel: str,
    subject: str | None,
    body: str,
    recipient_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    email_provider: EmailProvider | None,
    sms_provider: SmsProvider | None,
) -> None:
    """Processes exactly one recipient: re-checks suppression at send
    time (a contact may have unsubscribed since enrollment), re-reads the
    contact's current address via CRM's own published `get_contact()`,
    attempts the real send, and records the per-recipient outcome. Never
    raises -- one bad recipient must not abort the batch, mirroring
    `product/crm/imports.py::_process_row()`'s own "never a partial
    silent failure" discipline."""
    from datetime import UTC, datetime

    if contact_id is None:
        # The contact was deleted after enrollment (ON DELETE SET NULL
        # (contact_id) -- see product/marketing/models.py) -- nothing
        # left to send to.
        _mark_recipient(tenant_id, recipient_id, RECIPIENT_STATUS_FAILED, "contact_deleted")
        return

    if is_suppressed(tenant_id, contact_id, channel):
        _mark_recipient(tenant_id, recipient_id, RECIPIENT_STATUS_SUPPRESSED, None)
        return

    try:
        contact = get_contact(actor_user_id, tenant_id, contact_id)
    except (CrmAccessDeniedError, CrmReferenceNotFoundError):
        _mark_recipient(tenant_id, recipient_id, RECIPIENT_STATUS_FAILED, "contact_not_readable")
        return

    try:
        if channel == CHANNEL_EMAIL:
            if not contact.email:
                _mark_recipient(
                    tenant_id, recipient_id, RECIPIENT_STATUS_FAILED, "no_email_on_file"
                )
                return
            _send_email_to_contact(contact.email, subject or "", body, email_provider)
        else:
            if not contact.phone:
                _mark_recipient(
                    tenant_id, recipient_id, RECIPIENT_STATUS_FAILED, "no_phone_on_file"
                )
                return
            _send_sms_to_contact(contact.phone, body, sms_provider)
    except (EmailConfigurationError, EmailProviderError, InvalidEmailAddressError) as exc:
        _mark_recipient(tenant_id, recipient_id, RECIPIENT_STATUS_FAILED, type(exc).__name__)
        return
    except SmsProviderError as exc:
        _mark_recipient(tenant_id, recipient_id, RECIPIENT_STATUS_FAILED, type(exc).__name__)
        return

    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingCampaignRecipient, recipient_id)
        if row is None or row.tenant_id != tenant_id:
            return
        row.status = RECIPIENT_STATUS_SENT
        row.sent_at = datetime.now(UTC)
        row.error = None
        session.flush()


def _send_email_to_contact(
    to_email: str, subject: str, body: str, provider: EmailProvider | None
) -> None:
    config = get_email_config()
    if not config.default_sender:
        raise EmailConfigurationError("EMAIL_DEFAULT_SENDER is not set.")
    message = EmailMessage(
        sender=config.default_sender, to=(to_email,), subject=subject, text_body=body
    )
    send_email(message, provider=provider)


def _send_sms_to_contact(to_phone: str, body: str, provider: SmsProvider | None) -> None:
    if provider is None:
        # No real SMS provider is configured anywhere in this product yet
        # (docs/ROADMAP.md Phase 6.2, deliberately PARTIAL) -- fail
        # closed, per-recipient, with a clear reason, rather than
        # silently pretending to send. See module docstring.
        raise SmsProviderError("no SMS provider is configured for this product yet.")
    send_campaign_sms(to_phone=to_phone, body=body, provider=provider)


async def _run_campaign_send_job(
    payload: TenantJobPayload | None,
    *,
    email_provider: EmailProvider | None = None,
    sms_provider: SmsProvider | None = None,
) -> None:
    """The registered arq job handler. See module docstring for the
    cancellation/idempotency/provider-injection design -- all three are
    load-bearing, not incidental."""
    if payload is None:
        raise ValueError("_run_campaign_send_job requires a TenantJobPayload, got None.")
    tenant_id = uuid.UUID(payload.tenant_id)
    campaign_id = uuid.UUID(str(payload.data["campaign_id"]))
    actor_user_id = uuid.UUID(str(payload.data["actor_user_id"]))

    with tenant_session_scope(tenant_id) as session:
        campaign = session.get(MarketingCampaign, campaign_id)
        if campaign is None or campaign.tenant_id != tenant_id:
            return
        channel = campaign.channel
        subject = campaign.subject
        body = campaign.body

    while True:
        with tenant_session_scope(tenant_id) as session:
            campaign = session.get(MarketingCampaign, campaign_id)
            if campaign is None or campaign.tenant_id != tenant_id:
                return
            if campaign.status == STATUS_CANCELLED:
                # Mid-send cancellation observed -- stop processing
                # further recipients. Already-sent/failed rows stay as
                # they are; the rest remain "pending" (module docstring).
                return

            next_recipient = (
                session.execute(
                    select(MarketingCampaignRecipient)
                    .where(
                        MarketingCampaignRecipient.tenant_id == tenant_id,
                        MarketingCampaignRecipient.campaign_id == campaign_id,
                        MarketingCampaignRecipient.status == RECIPIENT_STATUS_PENDING,
                    )
                    .order_by(MarketingCampaignRecipient.created_at.asc())
                    .limit(1)
                )
                .scalars()
                .one_or_none()
            )
            if next_recipient is None:
                # No more pending recipients -- the send is complete.
                campaign.status = STATUS_SENT
                session.flush()
                break
            recipient_id = next_recipient.id
            contact_id = next_recipient.contact_id

        _process_one_recipient(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            channel=channel,
            subject=subject,
            body=body,
            recipient_id=recipient_id,
            contact_id=contact_id,
            email_provider=email_provider,
            sms_provider=sms_provider,
        )

    with tenant_session_scope(tenant_id) as session:
        sent_count = (
            session.execute(
                select(MarketingCampaignRecipient).where(
                    MarketingCampaignRecipient.tenant_id == tenant_id,
                    MarketingCampaignRecipient.campaign_id == campaign_id,
                    MarketingCampaignRecipient.status == RECIPIENT_STATUS_SENT,
                )
            )
            .scalars()
            .all()
        )
        sent_count_num = len(sent_count)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.campaign.send_completed",
        resource_type="marketing.campaign",
        resource_id=str(campaign_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"channel": channel, "sent_count": sent_count_num},
    )


CAMPAIGN_SEND_JOB_FUNCTIONS = [register_job(_run_campaign_send_job)]
