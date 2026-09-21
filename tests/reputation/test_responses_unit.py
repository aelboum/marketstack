"""`product/reputation/responses.py::_ensure_posted_externally()`: pure,
no-database tests of the provider-routing decision -- see that function's
own docstring for why this branch is proven by direct unit test rather
than an integration test (no non-`'manual'` `Review` row can exist yet).
Not marked `integration` -- runs in the default `pytest` invocation.
"""

from __future__ import annotations

import pytest
from product.reputation.errors import ReputationProviderNotConfiguredError
from product.reputation.models import PROVIDER_MANUAL
from product.reputation.providers import FakeReviewProvider
from product.reputation.responses import _ensure_posted_externally


def test_manual_review_needs_no_external_post() -> None:
    # No provider_client at all -- must not raise, must not need one.
    _ensure_posted_externally(PROVIDER_MANUAL, None, "Thanks!", None)


def test_non_manual_review_posts_via_injected_provider_client() -> None:
    client = FakeReviewProvider()
    _ensure_posted_externally("google_business_profile", "ext-1", "Thanks!", client)
    assert client.posted == [("ext-1", "Thanks!")]


def test_non_manual_review_with_no_configured_provider_raises() -> None:
    """`resolve_provider()` returns `None` for every provider by design
    (`product/reputation/providers.py`) -- with no `provider_client`
    injected, this must fail loudly, never silently no-op."""
    with pytest.raises(ReputationProviderNotConfiguredError) as exc_info:
        _ensure_posted_externally("google_business_profile", "ext-1", "Thanks!", None)
    assert exc_info.value.provider == "google_business_profile"
