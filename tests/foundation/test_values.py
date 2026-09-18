"""Unit tests for product/foundation/values.py. No database needed."""

from __future__ import annotations

from decimal import Decimal

import pytest
from product.foundation.values import (
    CurrencyMismatchError,
    InvalidCurrencyCodeError,
    InvalidMoneyAmountError,
    InvalidPhoneNumberError,
    Money,
    normalize_phone_number,
)


class TestMoney:
    def test_from_decimal_round_trip(self) -> None:
        m = Money.from_decimal("19.99", "eur")
        assert m.minor_units == 1999
        assert m.currency == "EUR"
        assert m.decimal == Decimal("19.99")

    def test_round_half_up_rounding(self) -> None:
        # 19.995 rounds to 20.00 (round-half-up), not 19.99 (banker's
        # rounding would give the latter) -- the module docstring's own
        # documented, deliberate choice.
        assert Money.from_decimal("19.995", "EUR").minor_units == 2000
        assert Money.from_decimal("19.994", "EUR").minor_units == 1999

    def test_addition_same_currency(self) -> None:
        total = Money.from_decimal("10.00", "EUR") + Money.from_decimal("5.50", "EUR")
        assert total == Money(1550, "EUR")

    def test_subtraction_same_currency(self) -> None:
        remainder = Money.from_decimal("10.00", "EUR") - Money.from_decimal("3.25", "EUR")
        assert remainder == Money(675, "EUR")

    def test_addition_currency_mismatch_raises(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            _ = Money.from_decimal("10.00", "EUR") + Money.from_decimal("10.00", "USD")

    def test_subtraction_currency_mismatch_raises(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            _ = Money.from_decimal("10.00", "EUR") - Money.from_decimal("10.00", "USD")

    def test_invalid_currency_code_rejected(self) -> None:
        with pytest.raises(InvalidCurrencyCodeError):
            Money(100, "euros")
        with pytest.raises(InvalidCurrencyCodeError):
            Money(100, "eur")  # must be uppercase

    def test_invalid_decimal_amount_rejected(self) -> None:
        with pytest.raises(InvalidMoneyAmountError):
            Money.from_decimal("not-a-number", "EUR")

    def test_str_formatting(self) -> None:
        assert str(Money.from_decimal("19.99", "EUR")) == "19.99 EUR"

    def test_frozen_and_immutable(self) -> None:
        m = Money.from_decimal("1.00", "EUR")
        with pytest.raises(AttributeError):
            m.minor_units = 200  # type: ignore[misc]


class TestPhoneNumberNormalization:
    def test_already_e164(self) -> None:
        assert normalize_phone_number("+31612345678").e164 == "+31612345678"

    def test_strips_formatting_punctuation(self) -> None:
        assert normalize_phone_number("+31 6 1234 5678").e164 == "+31612345678"
        assert normalize_phone_number("+1 (555) 123-4567").e164 == "+15551234567"

    def test_00_prefix_treated_as_plus(self) -> None:
        assert normalize_phone_number("0031612345678").e164 == "+31612345678"

    def test_bare_national_number_rejected(self) -> None:
        # No '+' or '00' prefix -- ambiguous without a known tenant
        # country, deliberately not guessed.
        with pytest.raises(InvalidPhoneNumberError):
            normalize_phone_number("0612345678")

    def test_too_short_rejected(self) -> None:
        with pytest.raises(InvalidPhoneNumberError):
            normalize_phone_number("+123")

    def test_leading_zero_after_plus_rejected(self) -> None:
        with pytest.raises(InvalidPhoneNumberError):
            normalize_phone_number("+0612345678")
