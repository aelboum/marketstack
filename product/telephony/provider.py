"""Telephony provider interface only -- docs/ROADMAP.md Phase 8.1,
explicitly **PARTIAL**, not complete. Read `product/telephony/__init__.py`'s
own module docstring first for the full reasoning (mirrors
`product/conversations/sms.py`'s identical "no vendor selected" situation,
`docs/RISKS-AND-OPEN-QUESTIONS.md` item 6).

**What IS built here**: the `TelephonyProvider` Protocol (mirrors
`core/email/provider.py::EmailProvider`'s exact shape) and
`FakeTelephonyProvider`, a real, deterministic, in-memory implementation
of it -- not a mock, a genuine second implementation any test can run
against with no network access, no credentials.

`verify_webhook_signature()` is a real, working HMAC-SHA256 check here --
`FakeTelephonyProvider` is constructed with an explicit `webhook_secret`
(never a default, never hardcoded -- a real caller/test supplies its own
value, exactly like `infra.secrets`-sourced credentials would for a real
adapter) and actually verifies a signature computed the same way. This is
deliberately **not** any real vendor's scheme (Twilio's, Vonage's, or
anyone else's HMAC construction differs from this one and from each
other) -- it is *a* real, working scheme, proving the verification/
replay-protection/idempotency pipeline in `product/telephony/calls.py
::receive_inbound_call_event()` is genuine, not a stub that "verifies
nothing real" (the exact failure mode `product/conversations/sms.py`'s own
docstring warns against for a route wired to nothing real). A real
`TwilioTelephonyProvider` (or similar) implementing this same Protocol
with Twilio's own signature scheme is what a future phase adds; nothing
here needs to change for that to happen.

**What is NOT built here, deliberately**: no real adapter (no vendor
selected), no `infra.secrets` credential lookup for any specific vendor,
no environment variable naming a vendor, no HTTP route (see
`product/telephony/__init__.py`'s own module docstring for why).
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from product.telephony.errors import TelephonyProviderError

_SIGNATURE_HEADER = "X-Fake-Telephony-Signature"


@dataclass(frozen=True)
class ProvisionedNumber:
    phone_number: str
    provider_number_id: str


@dataclass(frozen=True)
class PlacedCall:
    provider_call_id: str


@runtime_checkable
class TelephonyProvider(Protocol):
    @property
    def name(self) -> str: ...

    def provision_number(self, *, country_code: str) -> ProvisionedNumber: ...

    def place_call(self, *, from_number: str, to_number: str) -> PlacedCall: ...

    def verify_webhook_signature(self, *, headers: Mapping[str, str], body: bytes) -> bool: ...


@dataclass
class FakeTelephonyProvider:
    """An in-memory `TelephonyProvider` -- mirrors
    `product.conversations.sms.FakeSmsProvider`'s identical role.
    `webhook_secret` has no default -- a caller (today, only a test) must
    supply one explicitly, exactly like `product/foundation/storage.py
    ::FakeObjectStorage` requires no hidden default credential either."""

    webhook_secret: str
    fail: bool = False
    _provisioned: list[ProvisionedNumber] = field(default_factory=list)
    _placed_calls: list[PlacedCall] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake"

    def provision_number(self, *, country_code: str) -> ProvisionedNumber:
        if self.fail:
            raise TelephonyProviderError("FakeTelephonyProvider configured to fail")
        sequence = len(self._provisioned) + 1
        result = ProvisionedNumber(
            phone_number=f"+1555{sequence:07d}",
            provider_number_id=f"fake-number-{sequence}",
        )
        self._provisioned.append(result)
        return result

    def place_call(self, *, from_number: str, to_number: str) -> PlacedCall:
        if self.fail:
            raise TelephonyProviderError("FakeTelephonyProvider configured to fail")
        result = PlacedCall(provider_call_id=f"fake-call-{len(self._placed_calls) + 1}")
        self._placed_calls.append(result)
        return result

    def compute_signature(self, body: bytes) -> str:
        """The counterpart a test uses to sign a fake inbound webhook body
        the same way `verify_webhook_signature()` checks it."""
        return hmac.new(self.webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, *, headers: Mapping[str, str], body: bytes) -> bool:
        provided = headers.get(_SIGNATURE_HEADER)
        if not provided:
            return False
        expected = self.compute_signature(body)
        return hmac.compare_digest(provided, expected)


__all__ = [
    "TelephonyProvider",
    "FakeTelephonyProvider",
    "ProvisionedNumber",
    "PlacedCall",
]
