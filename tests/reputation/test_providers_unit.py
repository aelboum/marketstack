"""`product/reputation/providers.py`: pure, no-database tests. Not marked
`integration` -- runs in the default `pytest` invocation.
"""

from __future__ import annotations

from product.reputation.providers import FakeReviewProvider, resolve_provider


def test_resolve_provider_returns_none_for_every_provider_by_design() -> None:
    """`docs/ROADMAP.md` Phase 12.2 is deliberately deferred -- no real
    adapter is ever configured in this phase, for any provider name."""
    assert resolve_provider("manual") is None
    assert resolve_provider("google_business_profile") is None
    assert resolve_provider("facebook") is None
    assert resolve_provider("") is None


def test_fake_review_provider_records_posted_responses() -> None:
    provider = FakeReviewProvider(name="fake")
    result = provider.post_response(external_review_id="ext-1", body="Thanks!")
    assert result.accepted is True
    assert result.provider_response_id == "ext-1"
    assert provider.posted == [("ext-1", "Thanks!")]


def test_fake_review_provider_can_simulate_failure() -> None:
    provider = FakeReviewProvider(fail=True)
    result = provider.post_response(external_review_id="ext-1", body="Thanks!")
    assert result.accepted is False
    assert provider.posted == []
