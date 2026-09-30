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

**Update (Phase 27.0)**: a real adapter now exists --
`product/telephony/adapters/twilio_provider.py::TwilioTelephonyProvider`,
implementing this exact `TelephonyProvider` Protocol with Twilio's own
documented webhook-signature scheme. This file's own `TelephonyProvider`/
`FakeTelephonyProvider` pair is unchanged by that addition -- exactly the
"nothing here needs to change" outcome the paragraph above already
anticipated.
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


@dataclass(frozen=True)
class ConsultationLeg:
    """The minimum stable domain concept for Phase 27.0's attended
    transfer -- an outbound leg placed to a trusted human destination,
    correlated back to the original call for every subsequent transfer
    operation (`bridge_call()`/`remove_leg()`). Deliberately just a
    provider-assigned identifier, nothing else: this module never exposes
    a vendor-specific object (a Twilio `CallInstance`, a `ConferenceSid`)
    outside the concrete adapter that created it -- see
    `product/telephony/adapters/twilio_provider.py`'s own module
    docstring."""

    provider_leg_id: str


@runtime_checkable
class TelephonyProvider(Protocol):
    @property
    def name(self) -> str: ...

    def provision_number(self, *, country_code: str) -> ProvisionedNumber: ...

    def place_call(self, *, from_number: str, to_number: str) -> PlacedCall: ...

    # `path` (Phase 27.0 HIGH-2 remediation, renamed from `url`) is the
    # inbound request's own path+query ONLY, never a full URL. A real
    # adapter whose signature algorithm covers the full external URL
    # (Twilio's does) combines this path with its OWN already-trusted
    # base URL (its own platform configuration -- see
    # `product/telephony/adapters/twilio_provider.py`'s own module
    # docstring) to build the exact URL it verifies against. The route
    # calling this method never supplies a full URL and never reads a
    # forwarded-header-derived scheme/host for this purpose -- the
    # externally-visible origin is always the adapter's own trusted
    # configuration, never anything the request itself carries.
    def verify_webhook_signature(
        self, *, headers: Mapping[str, str], body: bytes, path: str = ""
    ) -> bool: ...

    # --- Phase 27.0 attended-transfer primitives -----------------------
    #
    # The smallest stable set of transfer-specific operations a real
    # adapter's own vendor primitives (Twilio's Dial/Conference/Participant
    # trio, Telnyx's Bridge/Conference/Leave-Conference trio, or a SIP/PBX
    # adapter's own REFER+Replaces) must be able to express -- never a
    # general-purpose call-orchestration engine, and never a Twilio-,
    # Telnyx-, or SIP-specific method name or return type.
    #
    # "Hold" is deliberately not a separate method: for every architecture
    # this phase evaluated, putting the caller on hold is an implementation
    # detail of how a concrete adapter creates the consultation leg (e.g. a
    # Twilio adapter dials the human into a new conference the original
    # caller leg has not yet joined), never a distinct domain-visible
    # operation the AI/CallSession layer needs to request on its own.
    #
    # "Remove AI leg" is deliberately not a separate method either: the AI
    # is not a distinct telephony leg with its own provider identifier in
    # any evaluated architecture -- it is a media-processing attachment
    # (Phase 27.0's own streaming boundary,
    # `product/telephony/adapters/twilio_media_stream.py`) riding on the
    # *original* call's own leg. Redirecting that same leg into the bridge
    # conference (`bridge_call()`) is what ends the AI's handling of it --
    # there is no separate "AI CallSid" a real adapter could remove. The
    # domain still sees a distinct `EVENT_TRANSFER_AI_LEG_REMOVED` audit
    # milestone (`product/telephony/transfer.py`), recorded once
    # `bridge_call()` succeeds, without a corresponding Protocol method.

    # `tenant_id`/`attempt_id` here are never caller-supplied and never a
    # new trust boundary: they exist only so a real adapter can build its
    # own server-generated, signature-bound status-callback URL for this
    # one consultation leg (`product/telephony/adapters/twilio_provider.py`'s
    # own module docstring) -- `tenant_id` is the same tenant a signed
    # inbound request already resolved further upstream, and `attempt_id`
    # is the domain-generated transfer-attempt identity
    # `product/telephony/calls.py::try_start_transfer_attempt()` already
    # claimed before this method is ever called (Phase 27.0 HIGH-1
    # remediation) -- both passed straight through, never invented here.
    def create_consultation_leg(
        self,
        *,
        original_provider_call_id: str,
        human_destination: str,
        tenant_id: str,
        attempt_id: str,
    ) -> ConsultationLeg: ...

    def bridge_call(
        self, *, original_provider_call_id: str, consultation_leg: ConsultationLeg
    ) -> None: ...


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
    _consultation_legs: list[ConsultationLeg] = field(default_factory=list)
    _bridged: list[tuple[str, str]] = field(default_factory=list)

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

    def verify_webhook_signature(
        self, *, headers: Mapping[str, str], body: bytes, path: str = ""
    ) -> bool:
        # `path` is unused -- this scheme never covered it (module
        # docstring); accepted only to satisfy the shared Protocol shape.
        del path
        provided = headers.get(_SIGNATURE_HEADER)
        if not provided:
            return False
        expected = self.compute_signature(body)
        return hmac.compare_digest(provided, expected)

    def create_consultation_leg(
        self,
        *,
        original_provider_call_id: str,
        human_destination: str,
        tenant_id: str,
        attempt_id: str,
    ) -> ConsultationLeg:
        if self.fail:
            raise TelephonyProviderError("FakeTelephonyProvider configured to fail")
        del original_provider_call_id, human_destination, tenant_id, attempt_id
        result = ConsultationLeg(provider_leg_id=f"fake-leg-{len(self._consultation_legs) + 1}")
        self._consultation_legs.append(result)
        return result

    def bridge_call(
        self, *, original_provider_call_id: str, consultation_leg: ConsultationLeg
    ) -> None:
        if self.fail:
            raise TelephonyProviderError("FakeTelephonyProvider configured to fail")
        self._bridged.append((original_provider_call_id, consultation_leg.provider_leg_id))


__all__ = [
    "ConsultationLeg",
    "FakeTelephonyProvider",
    "PlacedCall",
    "ProvisionedNumber",
    "TelephonyProvider",
]
