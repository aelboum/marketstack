"""WhatsApp provider interface only -- docs/ROADMAP.md Phase 5.4,
explicitly **PARTIAL**, not complete. Identical reasoning and identical
shape to `product/conversations/sms.py` -- read that module's own
docstring first; everything there about the still-open vendor decision
(`docs/RISKS-AND-OPEN-QUESTIONS.md` item 6), the deliberate absence of an
inbound webhook route (WhatsApp's own signature scheme, via Meta's Cloud
API or a BSP, is equally vendor-specific and equally unbuildable without
a real, chosen provider), and the "no default provider" design applies
here unchanged.

One WhatsApp-specific note the roadmap itself calls out (5.4's own
Security consideration): "WhatsApp Business API template-message
approval constraints are a provider-specific detail this adapter must
respect, not something product code works around." No such constraint is
modeled here -- there is no real adapter yet for it to apply to; this is
recorded so a future real `WhatsAppProvider` implementation does not
silently ignore it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from product.conversations.messages import MessageView, create_message
from product.conversations.models import DIRECTION_OUTBOUND


class WhatsAppProviderError(RuntimeError):
    """Mirrors `product.conversations.sms.SmsProviderError`'s identical
    normalized-error discipline."""


@dataclass(frozen=True)
class WhatsAppMessage:
    to: str
    body: str


@dataclass(frozen=True)
class WhatsAppSendResult:
    accepted: bool
    provider_message_id: str | None = None


@runtime_checkable
class WhatsAppProvider(Protocol):
    def send(self, message: WhatsAppMessage) -> WhatsAppSendResult: ...


@dataclass
class FakeWhatsAppProvider:
    """An in-memory `WhatsAppProvider` -- mirrors
    `product.conversations.sms.FakeSmsProvider` exactly."""

    fail: bool = False
    sent: list[WhatsAppMessage] = field(default_factory=list)

    def send(self, message: WhatsAppMessage) -> WhatsAppSendResult:
        if self.fail:
            raise WhatsAppProviderError("FakeWhatsAppProvider configured to fail")
        self.sent.append(message)
        return WhatsAppSendResult(
            accepted=True, provider_message_id=f"fake-whatsapp-{len(self.sent)}"
        )


def send_whatsapp_message(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    *,
    to_phone: str,
    body: str,
    provider: WhatsAppProvider,
) -> MessageView:
    """No default `provider` -- see module docstring."""
    message = WhatsAppMessage(to=to_phone, body=body)
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
