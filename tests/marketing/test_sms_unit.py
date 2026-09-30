"""`FakeSmsProvider` satisfies its own `SmsProvider` Protocol
(docs/ROADMAP.md Phase 6.2) -- the substitution-test gap a Phase 17.1
adapter-consistency audit found: `product/marketing/sms.py`'s functional
send-path behavior is already covered by
`tests/marketing/test_sending_integration.py`, but no dedicated unit test
existed for this module at all. No database, no network -- a plain unit
test, part of the default `pytest` run.
"""

from __future__ import annotations

from product.marketing.sms import FakeSmsProvider, SmsProvider


def test_fake_sms_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeSmsProvider(), SmsProvider)
