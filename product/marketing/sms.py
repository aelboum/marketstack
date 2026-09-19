"""SMS provider interface only -- docs/ROADMAP.md Phase 6.2, explicitly
**PARTIAL**, not complete. Read this docstring before assuming SMS
campaign sending works end-to-end; it does not, and should not be made to
without your explicit sign-off.

**Why this is partial, not finished**: 6.2's Objective is "same as 6.1,
over the Phase 5.3 SMS adapter," and its own Security Considerations line
names "SMS-specific opt-out (STOP keyword handling)" as a hard
requirement -- STOP-keyword handling needs a real inbound webhook, which
needs a real vendor, which is the identical, still-open blocker
`product/conversations/sms.py` already carries for Phase 5.3 (see that
module's own docstring: `docs/INTEGRATIONS.md` states vendor selection
"is a Phase-level decision made when that phase actually starts... not
fixed prematurely here," and `docs/RISKS-AND-OPEN-QUESTIONS.md` item 6
lists it as still open, never resolved by the user in any prior phase).

**Deliberate duplication, not an oversight**: this module's `SmsProvider`/
`FakeSmsProvider` are structurally identical to `product/conversations
/sms.py`'s own -- but NOT imported from there. `docs/ADR/0005-marketing-
depends-on-crm.md` permits `product.marketing -> product.crm` only; it
does not authorize `product.marketing -> product.conversations` (nor the
reverse), and this two-line Protocol definition is not a generic enough
capability to justify promoting to `product/foundation/` for two
call sites, mirroring `product/conversations/pagination.py`'s own
"duplication is a smaller, more honest cost than a cross-module
dependency" reasoning for the identical kind of judgment call. Revisit if
a third module needs the identical shape.

**What IS built here**: the `SmsProvider` Protocol, `FakeSmsProvider` (a
real in-memory implementation, not a mock), and `send_campaign_sms()` --
the one-message-at-a-time send primitive `product/marketing/sending.py`'s
own batch job calls once per recipient for an `"sms"`-channel campaign.
Proves the channel-agnostic campaign/recipient data model and send-job
shape work for a second channel (mirrors `docs/ROADMAP.md` Phase 5.1's
identical "at least two channel types" acceptance criterion, applied here
to campaigns) without claiming a live SMS send exists.

**What is NOT built here, deliberately**: no inbound webhook, no STOP-
keyword handling, no real provider adapter, no `infra.secrets` credential
lookup for any specific vendor, no environment variable naming a vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


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
    Records every message it was asked to send."""

    fail: bool = False
    sent: list[SmsMessage] = field(default_factory=list)

    def send(self, message: SmsMessage) -> SmsSendResult:
        if self.fail:
            raise SmsProviderError("FakeSmsProvider configured to fail")
        self.sent.append(message)
        return SmsSendResult(accepted=True, provider_message_id=f"fake-sms-{len(self.sent)}")


def send_campaign_sms(*, to_phone: str, body: str, provider: SmsProvider) -> SmsSendResult:
    """No default `provider` -- see module docstring: there is no real
    default SMS provider configured. Raises on failure (`SmsProviderError`
    or whatever the real provider's own normalized error is) -- the
    caller (`product/marketing/sending.py`'s job handler) is responsible
    for catching this per-recipient and recording `"failed"`, never
    letting one recipient's failure abort the whole batch."""
    return provider.send(SmsMessage(to=to_phone, body=body))
