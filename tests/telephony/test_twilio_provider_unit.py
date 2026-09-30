"""`product/telephony/adapters/twilio_provider.py`. No network -- every
Twilio REST call is served by an in-process `httpx.MockTransport`; nothing
here ever contacts the real Twilio API. Part of the default `pytest` run.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import httpx
import pytest
from product.telephony.adapters.twilio_config import get_twilio_config
from product.telephony.adapters.twilio_provider import TwilioTelephonyProvider
from product.telephony.errors import TelephonyProviderError, TelephonyProviderNotConfiguredError
from product.telephony.provider import ConsultationLeg, TelephonyProvider

_ACCOUNT_SID = "ACtest0000000000000000000000000000"
_AUTH_TOKEN = "test-auth-token-not-real"
_CALLBACK_BASE = "https://marketstack.example.test"


def _reference_signature(url: str, body: bytes) -> str:
    """An independent re-implementation of Twilio's own documented
    algorithm (docs.twilio.com/usage/security), built directly from the
    spec rather than by importing anything from the module under test --
    proves `_twilio_signature()` is actually correct, not merely
    self-consistent."""
    from urllib.parse import parse_qsl

    pairs = sorted(parse_qsl(body.decode("utf-8"), keep_blank_values=True), key=lambda kv: kv[0])
    data = url + "".join(k + v for k, v in pairs)
    digest = hmac.new(_AUTH_TOKEN.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _reference_signature_for_path(path: str, body: bytes) -> str:
    """The reference signature for a given request `path` -- combines it
    with `_CALLBACK_BASE` exactly the way `TwilioTelephonyProvider
    .verify_webhook_signature()` itself does internally (Phase 27.0
    HIGH-2 remediation: the provider owns this combination, never the
    caller)."""
    return _reference_signature(f"{_CALLBACK_BASE}{path}", body)


@pytest.fixture(autouse=True)
def _configured_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", _ACCOUNT_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", _AUTH_TOKEN)
    monkeypatch.setenv("TWILIO_VOICE_CALLBACK_BASE_URL", _CALLBACK_BASE)
    from infra.secrets import get_secrets_provider

    get_secrets_provider.cache_clear()
    get_twilio_config.cache_clear()
    yield
    get_secrets_provider.cache_clear()
    get_twilio_config.cache_clear()


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _provider(handler) -> TwilioTelephonyProvider:
    return TwilioTelephonyProvider(_transport=_mock_transport(handler))


def test_provider_name_is_twilio() -> None:
    assert _provider(lambda r: httpx.Response(200, json={})).name == "twilio"


def test_missing_credentials_raise_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    from infra.secrets import get_secrets_provider

    get_secrets_provider.cache_clear()
    with pytest.raises(TelephonyProviderNotConfiguredError):
        TwilioTelephonyProvider()


def test_missing_callback_url_raises_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWILIO_VOICE_CALLBACK_BASE_URL", raising=False)
    get_twilio_config.cache_clear()
    with pytest.raises(TelephonyProviderNotConfiguredError):
        TwilioTelephonyProvider()


def test_implements_telephony_provider_protocol() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={}))
    assert isinstance(provider, TelephonyProvider)


# --- signature verification (path-based -- HIGH-2 remediation) --------


def test_verify_webhook_signature_accepts_correctly_signed_request() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={}))
    path = "/v1/telephony/adapters/twilio/inbound-call"
    body = b"CallSid=CA123&From=%2B14155550123&To=%2B31612345678&CallStatus=ringing"
    signature = _reference_signature_for_path(path, body)
    assert provider.verify_webhook_signature(
        headers={"X-Twilio-Signature": signature}, body=body, path=path
    )


def test_verify_webhook_signature_is_header_case_insensitive() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={}))
    path = "/v1/telephony/adapters/twilio/inbound-call"
    body = b"CallSid=CA123"
    signature = _reference_signature_for_path(path, body)
    assert provider.verify_webhook_signature(
        headers={"x-twilio-signature": signature}, body=body, path=path
    )


def test_verify_webhook_signature_preserves_query_string() -> None:
    """HIGH-2 Part B.7 Test 2 -- the exact query string must be part of
    the signed URL, matching Twilio's own signing specification."""
    provider = _provider(lambda r: httpx.Response(200, json={}))
    path = "/v1/telephony/adapters/twilio/transfer-events/t-1/CA1/a-1?foo=bar"
    body = b"CallSid=CA-consult"
    signature = _reference_signature_for_path(path, body)
    assert provider.verify_webhook_signature(
        headers={"X-Twilio-Signature": signature}, body=body, path=path
    )
    # The identical signature must NOT validate against a different query
    # string (proves the query string is actually part of what is signed,
    # not silently dropped before verification).
    other_path = "/v1/telephony/adapters/twilio/transfer-events/t-1/CA1/a-1?foo=baz"
    assert not provider.verify_webhook_signature(
        headers={"X-Twilio-Signature": signature}, body=body, path=other_path
    )


def test_verify_webhook_signature_rejects_forged_signature() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={}))
    path = "/v1/telephony/adapters/twilio/inbound-call"
    body = b"CallSid=CA123"
    assert not provider.verify_webhook_signature(
        headers={"X-Twilio-Signature": "forged"}, body=body, path=path
    )


def test_verify_webhook_signature_rejects_missing_header() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={}))
    path = "/v1/telephony/adapters/twilio/inbound-call"
    assert not provider.verify_webhook_signature(headers={}, body=b"CallSid=CA123", path=path)


def test_verify_webhook_signature_rejects_missing_path() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={}))
    body = b"CallSid=CA123"
    signature = _reference_signature_for_path("", body)
    assert not provider.verify_webhook_signature(
        headers={"X-Twilio-Signature": signature}, body=body, path=""
    )


def test_verify_webhook_signature_rejects_tampered_body() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={}))
    path = "/v1/telephony/adapters/twilio/inbound-call"
    signature = _reference_signature_for_path(path, b"CallSid=CA123")
    assert not provider.verify_webhook_signature(
        headers={"X-Twilio-Signature": signature}, body=b"CallSid=CA999", path=path
    )


def test_verify_webhook_signature_rejects_wrong_auth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    path = "/v1/telephony/adapters/twilio/inbound-call"
    body = b"CallSid=CA123"
    signature = _reference_signature_for_path(path, body)  # signed with the ORIGINAL token

    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "a-different-token")
    from infra.secrets import get_secrets_provider

    get_secrets_provider.cache_clear()
    wrong_token_provider = _provider(lambda r: httpx.Response(200, json={}))
    assert not wrong_token_provider.verify_webhook_signature(
        headers={"X-Twilio-Signature": signature}, body=body, path=path
    )


def test_verify_webhook_signature_rejects_wrong_external_url() -> None:
    """HIGH-2 Part B.7 Test 4 -- a signature computed for a different host
    must fail even though the path matches, proving the base URL is
    actually part of what gets verified, not ignored."""
    provider = _provider(lambda r: httpx.Response(200, json={}))
    path = "/v1/telephony/adapters/twilio/inbound-call"
    body = b"CallSid=CA123"
    wrong_host_signature = _reference_signature(f"https://attacker.example{path}", body)
    assert not provider.verify_webhook_signature(
        headers={"X-Twilio-Signature": wrong_host_signature}, body=body, path=path
    )


# --- REST operations -----------------------------------------------------


def test_provision_number_searches_then_purchases() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "AvailablePhoneNumbers" in str(request.url):
            return httpx.Response(
                200, json={"available_phone_numbers": [{"phone_number": "+31612345678"}]}
            )
        return httpx.Response(201, json={"sid": "PN123", "phone_number": "+31612345678"})

    provider = _provider(handler)
    result = provider.provision_number(country_code="NL")
    assert result.phone_number == "+31612345678"
    assert result.provider_number_id == "PN123"
    assert len(calls) == 2


def test_provision_number_raises_on_no_availability() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={"available_phone_numbers": []}))
    with pytest.raises(TelephonyProviderError):
        provider.provision_number(country_code="NL")


def test_place_call_returns_placed_call() -> None:
    provider = _provider(lambda r: httpx.Response(201, json={"sid": "CA999"}))
    result = provider.place_call(from_number="+31612345678", to_number="+14155550123")
    assert result.provider_call_id == "CA999"


def test_place_call_normalizes_http_error() -> None:
    provider = _provider(lambda r: httpx.Response(500, json={"message": "boom"}))
    with pytest.raises(TelephonyProviderError):
        provider.place_call(from_number="+31612345678", to_number="+14155550123")


def test_create_consultation_leg_uses_original_caller_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"to": "+31612345678"})
        body = request.content.decode("utf-8")
        assert "From=%2B31612345678" in body
        assert "To=%2B14155550123" in body
        return httpx.Response(201, json={"sid": "CA-consult-1"})

    provider = _provider(handler)
    leg = provider.create_consultation_leg(
        original_provider_call_id="CA123",
        human_destination="+14155550123",
        tenant_id="11111111-1111-1111-1111-111111111111",
        attempt_id="22222222-2222-2222-2222-222222222222",
    )
    assert isinstance(leg, ConsultationLeg)
    assert leg.provider_leg_id == "CA-consult-1"


def test_create_consultation_leg_status_callback_embeds_attempt_id() -> None:
    """HIGH-1 remediation: the attempt id must be part of the signature-bound
    StatusCallback URL so a late callback belonging to a superseded attempt
    can be recognized as stale."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"to": "+31612345678"})
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(201, json={"sid": "CA-consult-1"})

    provider = _provider(handler)
    provider.create_consultation_leg(
        original_provider_call_id="CA123",
        human_destination="+14155550123",
        tenant_id="11111111-1111-1111-1111-111111111111",
        attempt_id="22222222-2222-2222-2222-222222222222",
    )
    assert "22222222-2222-2222-2222-222222222222" in seen["body"]
    assert "11111111-1111-1111-1111-111111111111" in seen["body"]


def test_bridge_call_redirects_original_call() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"sid": "CA123"})

    provider = _provider(handler)
    leg = ConsultationLeg(provider_leg_id="CA-consult-1")
    provider.bridge_call(original_provider_call_id="CA123", consultation_leg=leg)
    assert "Calls/CA123" in seen["url"]
    assert "transfer-CA123" in seen["body"]


def test_bridge_call_normalizes_http_error() -> None:
    provider = _provider(lambda r: httpx.Response(500, json={"message": "boom"}))
    with pytest.raises(TelephonyProviderError):
        provider.bridge_call(
            original_provider_call_id="CA123",
            consultation_leg=ConsultationLeg(provider_leg_id="CA-consult-1"),
        )
