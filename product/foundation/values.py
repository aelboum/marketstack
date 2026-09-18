"""Shared value objects (docs/ROADMAP.md Phase 2.1).

Not speculative -- each type here is what a named later phase's own
design already needs a concrete answer for:

- `Money`: Accounting's chart-of-accounts balances and invoice line
  amounts (docs/ACCOUNTING-SCOPE.md, Phase 15) and CRM/billing's own
  monetary fields need one consistent, correctly-rounded currency type
  before any of those phases starts, so no later phase invents its own.
- `normalize_phone_number`/`PhoneNumber`: CRM contacts (Phase 4) and
  Telephony (Phase 8) both need one consistent normalized phone format
  to compare/dedupe/dial against.

Both are pure value objects -- no database, no SaaS-OS dependency, no
product/<module> dependency (this file is `product/foundation/`, which
per docs/ARCHITECTURE.md section 2.2 must never import any other
product/<module> -- nothing here does).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")


class CurrencyMismatchError(ValueError):
    """Raised when an arithmetic operation is attempted between two
    `Money` values of different currencies. Never silently coerced --
    a EUR amount plus a USD amount is not a EUR amount."""

    def __init__(self, left: str, right: str) -> None:
        super().__init__(f"cannot combine {left} with {right}")
        self.left = left
        self.right = right


class InvalidCurrencyCodeError(ValueError):
    """Raised when a currency code is not a 3-letter uppercase ISO 4217-
    shaped code. This does not validate against the real ISO 4217 list
    (no such list is vendored here) -- only the shape, deliberately
    narrow, matching this phase's scope."""


class InvalidMoneyAmountError(ValueError):
    """Raised when a decimal/string amount cannot be parsed, or carries
    more precision than the currency's minor unit can represent without
    rounding being made an explicit, caller-visible decision."""


@dataclass(frozen=True, slots=True)
class Money:
    """An immutable monetary amount: integer minor units (cents) plus a
    currency code -- never a raw `float`, which cannot represent most
    decimal currency amounts exactly and silently accumulates rounding
    error across arithmetic. `minor_units` is the only field: 1999 + EUR
    means EUR 19.99.

    Rounding: round-half-up (`ROUND_HALF_UP`, "round 0.5 away from
    zero") is used everywhere a decimal amount is converted to integer
    minor units, e.g. `Money.from_decimal("19.995", "EUR")` ->
    EUR 20.00 (2000 minor units). This is the conventional choice for
    money (vs. Python's own default banker's rounding, which would
    round 19.995 down to 19.99 -- surprising for a displayed price/
    invoice line). Chosen once, here, so every later phase's monetary
    arithmetic rounds the same way.

    Only two decimal places (100 minor units per major unit) is assumed
    -- correct for EUR/USD/GBP and the overwhelming majority of
    currencies. A currency with a different minor-unit exponent (e.g.
    JPY's zero, BHD's three) is out of scope for this phase; revisit if
    a later phase genuinely needs one.
    """

    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if not _CURRENCY_CODE_RE.match(self.currency):
            raise InvalidCurrencyCodeError(
                f"currency must be a 3-letter uppercase code, got: {self.currency!r}"
            )
        if not isinstance(self.minor_units, int):
            raise InvalidMoneyAmountError(
                f"minor_units must be an int, got: {type(self.minor_units).__name__}"
            )

    @classmethod
    def from_decimal(cls, amount: str | Decimal, currency: str) -> Money:
        """Parse a major-unit decimal amount (e.g. "19.99", or
        `Decimal("19.99")`) into `Money`. A string input is required to
        be a syntactically valid decimal -- never a `float` (a `float`
        argument is rejected by `Decimal()` unless explicitly wrapped,
        which is deliberate: a caller passing `19.99` as a Python float
        literal already lost precision before this function ever runs).
        """
        try:
            decimal_amount = Decimal(amount) if isinstance(amount, str) else amount
        except InvalidOperation as exc:
            raise InvalidMoneyAmountError(f"not a valid decimal amount: {amount!r}") from exc
        minor = (decimal_amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return cls(minor_units=int(minor), currency=currency.upper())

    @property
    def decimal(self) -> Decimal:
        """The amount as a major-unit `Decimal`, e.g. `Money(1999,
        "EUR").decimal == Decimal("19.99")` -- for display/serialization,
        never for further arithmetic (stay in `Money`/minor-units for
        that, so rounding is only ever applied once, at construction)."""
        return Decimal(self.minor_units) / 100

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency)

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.minor_units - other.minor_units, self.currency)

    def __str__(self) -> str:
        return f"{self.decimal:.2f} {self.currency}"


_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class InvalidPhoneNumberError(ValueError):
    """Raised when a phone number cannot be normalized to this module's
    deliberately narrow E.164 shape."""


@dataclass(frozen=True, slots=True)
class PhoneNumber:
    """A normalized phone number in E.164 form (`+<countrycode><number>`,
    8-15 digits total after the `+`, no leading zero in the first digit
    -- the E.164 shape constraints, not a carrier/region-specific
    numbering-plan validator).

    **Deliberately narrow, not telephony-grade**: this does NOT validate
    that a number is actually assigned, actually dialable, or correctly
    shaped for its specific country's own numbering plan (e.g. it
    cannot tell a valid US number from an invalid one beyond the E.164
    digit-count envelope both share). It exists only so every module
    that stores a phone number (CRM contacts, Phase 4; Telephony, Phase
    8) normalizes to one consistent, comparable string shape. A real
    numbering-plan-aware library (e.g. Google's libphonenumber via the
    `phonenumbers` package) is a future decision for Phase 8 if/when
    Telephony's own dialing requirements need it -- not added here
    speculatively (no new dependency is authorized by this phase).
    """

    e164: str

    def __post_init__(self) -> None:
        if not _E164_RE.match(self.e164):
            raise InvalidPhoneNumberError(f"not a valid E.164-shaped phone number: {self.e164!r}")

    def __str__(self) -> str:
        return self.e164


def normalize_phone_number(raw: str) -> PhoneNumber:
    """Best-effort normalization of a human-entered phone number into
    `PhoneNumber` (E.164). Strips common formatting punctuation (spaces,
    hyphens, parentheses, dots); a leading `00` (the common international-
    dial-out prefix outside the `+`) is treated as `+`. Raises
    `InvalidPhoneNumberError` if the result does not fit the E.164 shape
    -- never guesses a country code for a number with no `+`/`00` prefix
    (deliberately conservative: a bare national-format number is
    ambiguous without knowing the tenant's own country, which this
    module does not have)."""
    stripped = re.sub(r"[\s\-().]", "", raw)
    if stripped.startswith("00"):
        stripped = "+" + stripped[2:]
    if not stripped.startswith("+"):
        raise InvalidPhoneNumberError(
            f"phone number must start with '+' or '00' (international format), got: {raw!r}"
        )
    return PhoneNumber(stripped)
