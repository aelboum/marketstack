"""`FakeSmsProvider`/`FakeWhatsAppProvider` satisfy their own `SmsProvider`/
`WhatsAppProvider` Protocols (docs/ROADMAP.md Phase 5.3/5.4) -- the
substitution-test gap a Phase 17.1 adapter-consistency audit found: every
sibling interface-only Category D module (`product/ai/provider.py`,
`product/telephony/provider.py`, `product/appointments/calendar_sync.py`,
`product/reputation/providers.py`) already carries this exact assertion;
these two did not. Functional send-path behavior is already covered by
`tests/conversations/test_sms_whatsapp_integration.py`. No database, no
network -- a plain unit test, part of the default `pytest` run.
"""

from __future__ import annotations

from product.conversations.sms import FakeSmsProvider, SmsProvider
from product.conversations.whatsapp import FakeWhatsAppProvider, WhatsAppProvider


def test_fake_sms_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeSmsProvider(), SmsProvider)


def test_fake_whatsapp_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeWhatsAppProvider(), WhatsAppProvider)
