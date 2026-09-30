"""HTTP-level integration tests for
`product/telephony/adapters/twilio_webhooks.py`, through a real FastAPI
`TestClient` and a real, already-migrated PostgreSQL database. Marked
`integration`, excluded from the default `pytest` run.

`_get_provider()` is monkeypatched to return a `FakeTelephonyProvider`
rather than constructing a real `TwilioTelephonyProvider` -- proving the
*route's own* signature-verification/tenant-resolution/idempotency wiring
end-to-end over real HTTP, independent of Twilio's specific signature
algorithm (covered separately, with an independently-derived reference
implementation, in `tests/telephony/test_twilio_provider_unit.py`). This
also proves the route passes headers through in a way that survives a
real ASGI request (Starlette lower-cases header names on receipt) rather
than only working against a hand-built, exact-case Python dict.
"""

from __future__ import annotations

import urllib.parse
import uuid

import pytest
from fastapi.testclient import TestClient
from product.agency.provisioning import provision_agency, provision_client
from product.api.main import create_app
from product.telephony.calls import get_call, list_calls
from product.telephony.destinations import set_human_transfer_destination
from product.telephony.models import STATUS_IN_PROGRESS, STATUS_TRANSFERRING
from product.telephony.numbers import provision_phone_number
from product.telephony.provider import FakeTelephonyProvider

from tests.telephony._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration

_HEADER = "X-Fake-Telephony-Signature"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _form_body(fields: dict[str, str]) -> bytes:
    return urllib.parse.urlencode(fields).encode("utf-8")


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakeTelephonyProvider:
    provider = FakeTelephonyProvider(webhook_secret="s")
    monkeypatch.setattr(
        "product.telephony.adapters.twilio_webhooks._get_provider", lambda: provider
    )
    return provider


def test_inbound_call_webhook_rejects_forged_signature(
    fake_provider: FakeTelephonyProvider,
) -> None:
    # The full app's own global error-handling middleware converts an
    # unmapped domain exception into a 500 response rather than letting it
    # propagate to the test client -- so the observable contract here is
    # "request rejected, no call created," not a raised Python exception.
    api = TestClient(create_app())
    body = _form_body({"CallSid": "CA1", "From": "+15551234567", "To": "+15559999999"})
    response = api.post(
        "/v1/telephony/adapters/twilio/inbound-call",
        content=body,
        headers={_HEADER: "forged", "content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 500


def test_inbound_call_webhook_creates_and_answers_a_call(
    fake_provider: FakeTelephonyProvider,
) -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=fake_provider
        )

        initiated_body = _form_body(
            {
                "CallSid": "CA-http-1",
                "From": "+15551234567",
                "To": number.phone_number,
                "CallStatus": "ringing",
            }
        )
        response = api.post(
            "/v1/telephony/adapters/twilio/inbound-call",
            content=initiated_body,
            headers={
                _HEADER: fake_provider.compute_signature(initiated_body),
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        assert response.status_code == 200

        answered_body = _form_body(
            {
                "CallSid": "CA-http-1",
                "From": "+15551234567",
                "To": number.phone_number,
                "CallStatus": "in-progress",
            }
        )
        api.post(
            "/v1/telephony/adapters/twilio/inbound-call",
            content=answered_body,
            headers={
                _HEADER: fake_provider.compute_signature(answered_body),
                "content-type": "application/x-www-form-urlencoded",
            },
        )

        calls = list_calls(owner.id, client.tenant_id)
        assert len(calls) == 1
        assert calls[0].status == STATUS_IN_PROGRESS
        assert calls[0].provider_call_id == "CA-http-1"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_transfer_events_webhook_bridges_on_human_answer(
    fake_provider: FakeTelephonyProvider,
) -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    api = TestClient(create_app())
    try:
        number = provision_phone_number(
            owner.id, client.tenant_id, country_code="US", provider=fake_provider
        )
        set_human_transfer_destination(owner.id, client.tenant_id, e164_value="+31612345678")

        initiated_body = _form_body(
            {
                "CallSid": "CA-http-2",
                "From": "+15551234567",
                "To": number.phone_number,
                "CallStatus": "ringing",
            }
        )
        api.post(
            "/v1/telephony/adapters/twilio/inbound-call",
            content=initiated_body,
            headers={
                _HEADER: fake_provider.compute_signature(initiated_body),
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        answered_body = _form_body(
            {
                "CallSid": "CA-http-2",
                "From": "+15551234567",
                "To": number.phone_number,
                "CallStatus": "in-progress",
            }
        )
        api.post(
            "/v1/telephony/adapters/twilio/inbound-call",
            content=answered_body,
            headers={
                _HEADER: fake_provider.compute_signature(answered_body),
                "content-type": "application/x-www-form-urlencoded",
            },
        )

        from product.telephony.transfer import initiate_transfer

        result = initiate_transfer(
            tenant_id=client.tenant_id,
            provider_call_id="CA-http-2",
            provider=fake_provider,
            request_id="turn-1",
        )
        call_id = list_calls(owner.id, client.tenant_id)[0].id
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_TRANSFERRING
        assert result.consultation_leg is not None
        assert result.attempt_id is not None

        transfer_url = (
            "/v1/telephony/adapters/twilio/transfer-events/"
            f"{client.tenant_id}/CA-http-2/{result.attempt_id}"
        )
        transfer_body = _form_body(
            {"CallSid": result.consultation_leg.provider_leg_id, "CallStatus": "in-progress"}
        )
        response = api.post(
            transfer_url,
            content=transfer_body,
            headers={
                _HEADER: fake_provider.compute_signature(transfer_body),
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        assert response.status_code == 200
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS

        # HIGH-1 regression: a duplicate delivery of the identical
        # "in-progress" callback must not call bridge_call() a second
        # time (proven indirectly here via FakeTelephonyProvider's own
        # recorded state; the direct provider-call-count assertion lives
        # in tests/telephony/test_transfer_integration.py).
        second_response = api.post(
            transfer_url,
            content=transfer_body,
            headers={
                _HEADER: fake_provider.compute_signature(transfer_body),
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        assert second_response.status_code == 200
        assert get_call(owner.id, client.tenant_id, call_id).status == STATUS_IN_PROGRESS
        assert len(fake_provider._bridged) == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_transfer_events_webhook_rejects_forged_signature(
    fake_provider: FakeTelephonyProvider,
) -> None:
    api = TestClient(create_app())
    body = _form_body({"CallSid": "CA-consult", "CallStatus": "busy"})
    response = api.post(
        f"/v1/telephony/adapters/twilio/transfer-events/{uuid.uuid4()}/CA-original/{uuid.uuid4()}",
        content=body,
        headers={_HEADER: "forged", "content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 500
