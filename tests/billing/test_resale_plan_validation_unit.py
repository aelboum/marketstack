"""`product/billing/resale_plans.py`'s pure, no-database validators
(docs/ROADMAP.md Phase 13.2). Not marked `integration` -- runs in the
default `pytest` invocation.
"""

from __future__ import annotations

import pytest
from product.billing.errors import BillingValidationError
from product.billing.models import MAX_KEY_LENGTH, MAX_NAME_LENGTH
from product.billing.resale_plans import (
    _validate_billing_interval,
    _validate_description,
    _validate_key,
    _validate_name,
    _validate_price_amount,
    _validate_price_currency,
)


def test_validate_key_rejects_empty() -> None:
    with pytest.raises(BillingValidationError):
        _validate_key("   ")


def test_validate_key_rejects_too_long() -> None:
    with pytest.raises(BillingValidationError):
        _validate_key("x" * (MAX_KEY_LENGTH + 1))


def test_validate_key_accepts_valid() -> None:
    assert _validate_key("starter") == "starter"


def test_validate_name_rejects_empty() -> None:
    with pytest.raises(BillingValidationError):
        _validate_name("")


def test_validate_name_rejects_too_long() -> None:
    with pytest.raises(BillingValidationError):
        _validate_name("x" * (MAX_NAME_LENGTH + 1))


def test_validate_description_allows_none() -> None:
    assert _validate_description(None) is None


def test_validate_description_rejects_too_long() -> None:
    with pytest.raises(BillingValidationError):
        _validate_description("x" * 1001)


@pytest.mark.parametrize("price_amount", [-1, -100])
def test_validate_price_amount_rejects_negative(price_amount: int) -> None:
    with pytest.raises(BillingValidationError):
        _validate_price_amount(price_amount)


def test_validate_price_amount_rejects_bool() -> None:
    """`isinstance(True, int)` is `True` in Python -- must be explicitly
    excluded, mirroring `product/reputation/reviews.py::_validate_rating()`'s
    own identical guard."""
    with pytest.raises(BillingValidationError):
        _validate_price_amount(True)  # type: ignore[arg-type]


def test_validate_price_amount_accepts_zero_and_positive() -> None:
    assert _validate_price_amount(0) == 0
    assert _validate_price_amount(1999) == 1999


@pytest.mark.parametrize("currency", ["US", "USDD", "12$", ""])
def test_validate_price_currency_rejects_invalid(currency: str) -> None:
    with pytest.raises(BillingValidationError):
        _validate_price_currency(currency)


def test_validate_price_currency_normalizes_case() -> None:
    assert _validate_price_currency("usd") == "USD"


def test_validate_billing_interval_rejects_unsupported() -> None:
    with pytest.raises(BillingValidationError):
        _validate_billing_interval("week")


@pytest.mark.parametrize("interval", ["month", "year"])
def test_validate_billing_interval_accepts_supported(interval: str) -> None:
    assert _validate_billing_interval(interval) == interval
