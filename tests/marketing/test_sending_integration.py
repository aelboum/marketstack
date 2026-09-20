"""Segmentation, suppression enforcement, and the campaign-send job
(docs/ROADMAP.md Phase 6.1's own core acceptance criterion: "a segmented
campaign sends correctly to its matching audience and respects
suppression"). Real disposable Postgres. Marked `integration`, excluded
from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.audit_log import list as list_audit_log
from core.email.provider import FakeEmailProvider
from infra.jobs import TenantJobPayload
from product.agency.provisioning import provision_agency, provision_client
from product.crm.contacts import create_contact
from product.crm.custom_fields import define_field, set_field_value
from product.crm.tags import attach_tag, create_tag
from product.marketing.campaigns import cancel_campaign, create_campaign, get_campaign
from product.marketing.errors import MarketingAccessDeniedError
from product.marketing.recipients import list_campaign_recipients
from product.marketing.segmentation import SegmentQuery, resolve_segment
from product.marketing.sending import _run_campaign_send_job, start_campaign_send
from product.marketing.sms import FakeSmsProvider
from product.marketing.suppressions import create_suppression

from tests.marketing._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


async def _run_job_inline(
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    email_provider=None,
    sms_provider=None,
) -> None:
    """Runs `_run_campaign_send_job()` directly, in-process -- mirrors
    `tests/crm/test_import_export_integration.py::_run_job_inline`'s
    exact role: proves the row-processing logic itself, decoupled from
    the durability-across-a-process-boundary question a real worker
    would answer (not this test file's job -- a genuinely separate
    subprocess-worker proof, mirroring `tests/crm/test_import_export_
    integration.py::test_import_job_runs_in_a_real_separate_worker_process`,
    is intentionally not duplicated here since the underlying `infra.jobs`
    durability mechanism is already proven there and in
    `tests/foundation/test_events_durable_integration.py` -- this phase's
    own acceptance criterion is about segmentation/suppression/
    cancellation correctness, which these in-process calls prove more
    directly)."""
    payload = TenantJobPayload(
        tenant_id=str(tenant_id),
        data={"campaign_id": str(campaign_id), "actor_user_id": str(actor_id)},
    )
    await _run_campaign_send_job(payload, email_provider=email_provider, sms_provider=sms_provider)


async def test_segmentation_by_tag_sends_only_to_matching_contacts() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        vip = create_contact(
            owner.id, client.tenant_id, first_name="Vip", last_name="One", email="vip@ex.com"
        )
        regular = create_contact(
            owner.id, client.tenant_id, first_name="Reg", last_name="Two", email="reg@ex.com"
        )
        tag = create_tag(owner.id, client.tenant_id, name="vip")
        attach_tag(
            owner.id, client.tenant_id, entity_type="contact", entity_id=vip.id, tag_id=tag.id
        )

        campaign = create_campaign(
            owner.id,
            client.tenant_id,
            name="VIP Blast",
            channel="email",
            subject="Hi VIP",
            body="secret-vip-body-marker",
            segment_tag="vip",
        )
        started = await start_campaign_send(owner.id, client.tenant_id, campaign.id)
        assert started.recipient_count == 1

        provider = FakeEmailProvider()
        await _run_job_inline(client.tenant_id, campaign.id, owner.id, email_provider=provider)

        assert len(provider.sent) == 1
        assert provider.sent[0].to == ("vip@ex.com",)

        final = get_campaign(owner.id, client.tenant_id, campaign.id)
        assert final.status == "sent"
        recipients = list_campaign_recipients(owner.id, client.tenant_id, campaign.id)
        assert {r.status for r in recipients} == {"sent"}
        assert regular.id not in {r.contact_id for r in recipients}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_segmentation_by_custom_field() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        matching = create_contact(
            owner.id, client.tenant_id, first_name="Match", last_name="Field", email="m@ex.com"
        )
        other = create_contact(
            owner.id, client.tenant_id, first_name="Other", last_name="Field", email="o@ex.com"
        )
        field = define_field(
            owner.id, client.tenant_id, entity_type="contact", name="plan", field_type="text"
        )
        set_field_value(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            entity_id=matching.id,
            field_definition_id=field.id,
            value="enterprise",
        )
        set_field_value(
            owner.id,
            client.tenant_id,
            entity_type="contact",
            entity_id=other.id,
            field_definition_id=field.id,
            value="starter",
        )

        segment = SegmentQuery(custom_field=(f"{field.id}:enterprise",))
        resolved = resolve_segment(owner.id, client.tenant_id, segment)
        assert {c.id for c in resolved} == {matching.id}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_suppressed_contact_enrolled_as_suppressed_and_never_sent() -> None:
    """The hard gate at enrollment time -- a suppressed contact never
    even reaches 'pending', and core.email.send_email is never called
    for them."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        good = create_contact(
            owner.id, client.tenant_id, first_name="Good", last_name="One", email="good@ex.com"
        )
        suppressed = create_contact(
            owner.id, client.tenant_id, first_name="Bad", last_name="Two", email="bad@ex.com"
        )
        create_suppression(
            owner.id,
            client.tenant_id,
            contact_id=suppressed.id,
            channel="email",
            reason="unsubscribed",
        )

        campaign = create_campaign(
            owner.id, client.tenant_id, name="All Contacts", channel="email", subject="s", body="b"
        )
        started = await start_campaign_send(owner.id, client.tenant_id, campaign.id)
        assert started.recipient_count == 2
        assert started.suppressed_count == 1

        recipients = list_campaign_recipients(owner.id, client.tenant_id, campaign.id)
        by_contact = {r.contact_id: r.status for r in recipients}
        assert by_contact[suppressed.id] == "suppressed"
        assert by_contact[good.id] == "pending"

        provider = FakeEmailProvider()
        await _run_job_inline(client.tenant_id, campaign.id, owner.id, email_provider=provider)

        # The suppressed contact's email address never reached the
        # provider at all -- proves the gate, doesn't just assume it.
        sent_to = {addr for msg in provider.sent for addr in msg.to}
        assert "bad@ex.com" not in sent_to
        assert "good@ex.com" in sent_to
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_contact_suppressed_between_enrollment_and_send_is_still_skipped() -> None:
    """The hard gate also applies at send time, not only enrollment time
    -- a contact who unsubscribes after enrollment but before their turn
    in the batch must still be skipped."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id, client.tenant_id, first_name="Late", last_name="Unsub", email="late@ex.com"
        )
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Late Unsub", channel="email", subject="s", body="b"
        )
        started = await start_campaign_send(owner.id, client.tenant_id, campaign.id)
        assert started.suppressed_count == 0  # not suppressed yet at enrollment time

        # Unsubscribes AFTER enrollment, before the job actually runs.
        create_suppression(
            owner.id,
            client.tenant_id,
            contact_id=contact.id,
            channel="email",
            reason="unsubscribed",
        )

        provider = FakeEmailProvider()
        await _run_job_inline(client.tenant_id, campaign.id, owner.id, email_provider=provider)

        assert provider.sent == []
        recipients = list_campaign_recipients(owner.id, client.tenant_id, campaign.id)
        assert recipients[0].status == "suppressed"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_mid_send_cancellation_stops_further_sends() -> None:
    """docs/ROADMAP.md Phase 6.1's own Rollback text: "a bad campaign can
    be paused mid-send." A real interleaved cancellation -- the second
    recipient's own send triggers cancel_campaign() as a side effect,
    proving the job handler's next loop iteration actually observes and
    respects it, not merely that the code compiles."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        for i in range(4):
            create_contact(
                owner.id,
                client.tenant_id,
                first_name=f"C{i}",
                last_name="Bulk",
                email=f"c{i}@ex.com",
            )
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Cancel Mid", channel="email", subject="s", body="b"
        )
        started = await start_campaign_send(owner.id, client.tenant_id, campaign.id)
        assert started.recipient_count == 4

        provider = FakeEmailProvider()
        real_send = provider.send

        def _send_then_cancel_after_two(message):
            result = real_send(message)
            if len(provider.sent) == 2:
                cancel_campaign(owner.id, client.tenant_id, campaign.id)
            return result

        provider.send = _send_then_cancel_after_two  # type: ignore[method-assign]

        await _run_job_inline(client.tenant_id, campaign.id, owner.id, email_provider=provider)

        assert len(provider.sent) == 2, "cancellation should stop the loop after the 2nd recipient"
        final = get_campaign(owner.id, client.tenant_id, campaign.id)
        assert final.status == "cancelled"
        recipients = list_campaign_recipients(owner.id, client.tenant_id, campaign.id)
        statuses = [r.status for r in recipients]
        assert statuses.count("sent") == 2
        assert statuses.count("pending") == 2
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_job_retry_never_double_sends_already_processed_recipients() -> None:
    """Idempotency: campaign_recipients.status (not 'pending' once
    processed) is what prevents a double-send on a retried job -- proven
    by running the same job handler twice for the same campaign."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(
            owner.id, client.tenant_id, first_name="Once", last_name="Only", email="once@ex.com"
        )
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Retry Test", channel="email", subject="s", body="b"
        )
        await start_campaign_send(owner.id, client.tenant_id, campaign.id)

        first_provider = FakeEmailProvider()
        await _run_job_inline(
            client.tenant_id, campaign.id, owner.id, email_provider=first_provider
        )
        assert len(first_provider.sent) == 1

        second_provider = FakeEmailProvider()
        await _run_job_inline(
            client.tenant_id, campaign.id, owner.id, email_provider=second_provider
        )
        assert second_provider.sent == [], (
            "a retried job must never re-send an already-sent recipient"
        )

        recipients = list_campaign_recipients(owner.id, client.tenant_id, campaign.id)
        assert [r.status for r in recipients] == ["sent"]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_sms_channel_campaign_sends_via_fake_provider() -> None:
    """6.2, deliberately PARTIAL: proves the channel-agnostic
    campaign/recipient model and send-job shape work for a second channel
    via FakeSmsProvider -- not that a real SMS send exists."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(
            owner.id, client.tenant_id, first_name="Sms", last_name="Contact", phone="+15551234567"
        )
        campaign = create_campaign(
            owner.id, client.tenant_id, name="SMS Blast", channel="sms", body="Text body"
        )
        await start_campaign_send(owner.id, client.tenant_id, campaign.id)

        sms_provider = FakeSmsProvider()
        await _run_job_inline(client.tenant_id, campaign.id, owner.id, sms_provider=sms_provider)

        assert len(sms_provider.sent) == 1
        assert sms_provider.sent[0].to == "+15551234567"
        final = get_campaign(owner.id, client.tenant_id, campaign.id)
        assert final.status == "sent"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_sms_campaign_with_no_provider_fails_closed_in_production_shape() -> None:
    """With no sms_provider injected (the real production default), every
    SMS recipient fails with a clear reason -- never a silent
    pseudo-success. Documents 6.2's PARTIAL status as observable
    behavior, not just a docstring claim."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(
            owner.id,
            client.tenant_id,
            first_name="NoProvider",
            last_name="Contact",
            phone="+15559999999",
        )
        campaign = create_campaign(
            owner.id, client.tenant_id, name="No Provider", channel="sms", body="x"
        )
        await start_campaign_send(owner.id, client.tenant_id, campaign.id)

        await _run_job_inline(client.tenant_id, campaign.id, owner.id)  # no sms_provider supplied

        recipients = list_campaign_recipients(owner.id, client.tenant_id, campaign.id)
        assert recipients[0].status == "failed"
        assert recipients[0].error == "SmsProviderError"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_audit_metadata_never_contains_campaign_body_or_pii() -> None:
    """Personal-data requirement: campaign body/contact PII must never
    land in audit metadata. Proven by reading the real, persisted
    core.audit_log row back."""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    pii_marker = "super-secret-campaign-body-marker-xyz"
    try:
        create_contact(
            owner.id,
            client.tenant_id,
            first_name="Audit",
            last_name="Test",
            email="audit-pii@ex.com",
        )
        campaign = create_campaign(
            owner.id,
            client.tenant_id,
            name="Audit Test",
            channel="email",
            subject="s",
            body=pii_marker,
        )
        await start_campaign_send(owner.id, client.tenant_id, campaign.id)
        await _run_job_inline(
            client.tenant_id, campaign.id, owner.id, email_provider=FakeEmailProvider()
        )

        entries = list_audit_log(
            client.tenant_id, resource_type="marketing.campaign", resource_id=str(campaign.id)
        )
        assert len(entries) >= 1
        for entry in entries:
            serialized = str(entry.metadata)
            assert pii_marker not in serialized
            assert "audit-pii@ex.com" not in serialized
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_deleted_contact_recipient_is_set_null_not_cascaded() -> None:
    """Column-scoped ON DELETE SET NULL (contact_id) -- the fix for the
    defect class the deferred Phase 4 CRM bug demonstrated. Deleting a
    contact must unlink their recipient row, not crash the delete or
    cascade-delete send history."""
    from product.crm.contacts import delete_contact

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = create_contact(
            owner.id,
            client.tenant_id,
            first_name="ToDelete",
            last_name="Contact",
            email="del@ex.com",
        )
        campaign = create_campaign(
            owner.id,
            client.tenant_id,
            name="Delete Contact Test",
            channel="email",
            subject="s",
            body="b",
        )
        await start_campaign_send(owner.id, client.tenant_id, campaign.id)
        recipients = list_campaign_recipients(owner.id, client.tenant_id, campaign.id)
        assert recipients[0].contact_id == contact.id

        delete_contact(owner.id, client.tenant_id, contact.id)  # must not raise

        recipients_after = list_campaign_recipients(owner.id, client.tenant_id, campaign.id)
        assert len(recipients_after) == 1, "the recipient row must survive, only unlinked"
        assert recipients_after[0].contact_id is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_unrelated_actor_cannot_start_campaign_send() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        campaign = create_campaign(
            owner.id, client.tenant_id, name="Protected", channel="email", subject="s", body="b"
        )
        with pytest.raises(MarketingAccessDeniedError):
            await start_campaign_send(stranger.id, client.tenant_id, campaign.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)
