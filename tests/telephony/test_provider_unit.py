"""`FakeTelephonyProvider` round-trips through `TelephonyProvider`
correctly (docs/ROADMAP.md Phase 8.1), including a real, working
signature-verification scheme (Phase 8.2's own webhook-security
requirement) -- see product/telephony/provider.py's own module docstring
for why this is *a* real scheme, not a specific vendor's. No database, no
network -- a plain unit test, part of the default `pytest` run.
"""

from __future__ import annotations

import pytest
from product.telephony.errors import TelephonyProviderError
from product.telephony.provider import FakeTelephonyProvider, TelephonyProvider


def test_fake_telephony_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeTelephonyProvider(webhook_secret="s"), TelephonyProvider)


def test_provision_number_returns_deterministic_distinct_numbers() -> None:
    provider = FakeTelephonyProvider(webhook_secret="s")
    first = provider.provision_number(country_code="US")
    second = provider.provision_number(country_code="US")
    assert first.phone_number != second.phone_number


def test_provision_number_raises_when_configured_to_fail() -> None:
    provider = FakeTelephonyProvider(webhook_secret="s", fail=True)
    with pytest.raises(TelephonyProviderError):
        provider.provision_number(country_code="US")


def test_place_call_raises_when_configured_to_fail() -> None:
    provider = FakeTelephonyProvider(webhook_secret="s", fail=True)
    with pytest.raises(TelephonyProviderError):
        provider.place_call(from_number="+15551110000", to_number="+15552220000")


def test_verify_webhook_signature_accepts_correctly_signed_body() -> None:
    provider = FakeTelephonyProvider(webhook_secret="topsecret")
    body = b'{"event": "call.initiated"}'
    signature = provider.compute_signature(body)
    assert provider.verify_webhook_signature(
        headers={"X-Fake-Telephony-Signature": signature}, body=body
    )


def test_verify_webhook_signature_rejects_forged_signature() -> None:
    provider = FakeTelephonyProvider(webhook_secret="topsecret")
    body = b'{"event": "call.initiated"}'
    assert not provider.verify_webhook_signature(
        headers={"X-Fake-Telephony-Signature": "0" * 64}, body=body
    )


def test_verify_webhook_signature_rejects_missing_header() -> None:
    provider = FakeTelephonyProvider(webhook_secret="topsecret")
    assert not provider.verify_webhook_signature(headers={}, body=b"{}")


def test_verify_webhook_signature_rejects_wrong_secret() -> None:
    signer = FakeTelephonyProvider(webhook_secret="secret-a")
    verifier = FakeTelephonyProvider(webhook_secret="secret-b")
    body = b'{"event": "call.completed"}'
    signature = signer.compute_signature(body)
    assert not verifier.verify_webhook_signature(
        headers={"X-Fake-Telephony-Signature": signature}, body=body
    )


def test_verify_webhook_signature_rejects_tampered_body() -> None:
    provider = FakeTelephonyProvider(webhook_secret="topsecret")
    body = b'{"event": "call.completed"}'
    signature = provider.compute_signature(body)
    tampered = b'{"event": "call.failed"}'
    assert not provider.verify_webhook_signature(
        headers={"X-Fake-Telephony-Signature": signature}, body=tampered
    )
