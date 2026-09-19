"""SMS provider interface only -- docs/ROADMAP.md Phase 5.3, explicitly
**PARTIAL**, not complete. Read this docstring before assuming SMS
sending works end-to-end; it does not, and should not be made to without
your explicit sign-off.

**Why this is partial, not finished**: 5.3's Objective calls for "one
concrete provider" and "inbound webhook handling." `docs/INTEGRATIONS.md`
itself states vendor selection "is a Phase-level decision made when that
phase actually starts... not fixed prematurely here," and
`docs/RISKS-AND-OPEN-QUESTIONS.md` item 6 lists "initial integration
providers for SMS, WhatsApp..." as still open -- never resolved by the
user in any prior phase. Picking a real vendor (Twilio, MessageBird, or
otherwise), provisioning real credentials, and wiring a real inbound
webhook with that vendor's own signature scheme is a real, consequential,
costs-money decision this product may not make unilaterally.

**What IS built here**: the `SmsProvider` Protocol (mirrors
`core/email/provider.py::EmailProvider`'s exact shape -- a
`@runtime_checkable Protocol`, one `send()` method, a normalized result
dataclass) and `FakeSmsProvider`, a real, in-memory second implementation
of that Protocol (mirroring `core.email.provider.FakeEmailProvider`'s own
role -- not a mock bolted onto internals, a genuine implementation any
test can run against with no network access). `send_sms_message()` has
the identical shape to `email_sending.py::send_email_message()`, except
`provider` has **no default** -- there is no real default SMS provider
configured, so a caller (today, only a test using `FakeSmsProvider`) must
supply one explicitly. This proves the channel-agnostic thread/message
model itself works across a second channel type (5.1's real acceptance
criterion: "a thread can be created and populated across at least two
channel types... even before real sending exists") without claiming a
live SMS send exists.

**What is NOT built here, deliberately**: no inbound webhook route (SMS
signature verification is vendor-specific -- Twilio's HMAC scheme differs
from every other provider's; a route that "verifies" nothing real would
be a false sense of completeness, worse than no route at all), no real
provider adapter, no `infra.secrets` credential lookup for any specific
vendor, no environment variable naming a vendor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from product.conversations.messages import MessageView, create_message
from product.conversations.models import DIRECTION_OUTBOUND


class SmsProviderError(RuntimeError):
    """Raised by an `SmsProvider.send()` implementation on failure --
    mirrors `core.email.errors.EmailProviderError`'s own normalized-error
    discipline (never a raw transport/library exception)."""


@dataclass(frozen=True)
class SmsMessage:
    to: str
    body: str


@dataclass(frozen=True)
class SmsSendResult:
    accepted: bool
    provider_message_id: str | None = None


@runtime_checkable
class SmsProvider(Protocol):
    def send(self, message: SmsMessage) -> SmsSendResult: ...


@dataclass
class FakeSmsProvider:
    """An in-memory `SmsProvider` -- no network access, no credentials.
    Records every message it was asked to send, mirroring
    `core.email.provider.FakeEmailProvider`'s identical role."""

    fail: bool = False
    sent: list[SmsMessage] = field(default_factory=list)

    def send(self, message: SmsMessage) -> SmsSendResult:
        if self.fail:
            raise SmsProviderError("FakeSmsProvider configured to fail")
        self.sent.append(message)
        return SmsSendResult(accepted=True, provider_message_id=f"fake-sms-{len(self.sent)}")


def send_sms_message(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    *,
    to_phone: str,
    body: str,
    provider: SmsProvider,
) -> MessageView:
    """No default `provider` -- see module docstring: there is no real
    default SMS provider configured. On failure, no `Message` row is
    created, the identical guarantee `email_sending.py
    ::send_email_message()` makes."""
    message = SmsMessage(to=to_phone, body=body)
    provider.send(message)
    return create_message(
        actor_user_id,
        tenant_id,
        thread_id,
        direction=DIRECTION_OUTBOUND,
        is_internal_note=False,
        body=body,
        author_user_id=actor_user_id,
    )
