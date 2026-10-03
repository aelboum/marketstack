"""`product/billing/parties.py`'s public-API boundary -- pure, no-database.
Not marked `integration` -- runs in the default `pytest` invocation.

Proves the independent audit's remediation holds at the *module* level:
`_ensure_platform_merchant_account()`, `_ensure_agency_merchant_account()`,
and `_get_or_create_platform_billing_account()` are internal provisioning
primitives (module docstring, "Trust boundary") and must never be
advertised as part of this module's public API. This does not assert
that Python prevents importing an underscore-prefixed name -- it never
does, and a test claiming otherwise would prove nothing about security.
What actually matters, and what this checks, is that `__all__` -- the one
place this codebase already uses to declare a module's intended public
surface (every other `product/*/__init__.py` and `product/*/*.py` module
in this repository follows the same convention) -- does not list them.
"""

from __future__ import annotations

import product.billing.parties as parties


def test_internal_provisioning_primitives_are_not_in_the_public_api() -> None:
    assert "_ensure_platform_merchant_account" not in parties.__all__
    assert "_ensure_agency_merchant_account" not in parties.__all__
    assert "_get_or_create_platform_billing_account" not in parties.__all__
    # Still present and callable -- this is a public-API-surface decision,
    # never an attempt to actually hide or remove the functions.
    assert callable(parties._ensure_platform_merchant_account)
    assert callable(parties._ensure_agency_merchant_account)
    assert callable(parties._get_or_create_platform_billing_account)


def test_public_surface_still_exposes_the_caller_accepting_and_read_only_functions() -> None:
    """The remediation must not have removed or hidden any legitimate
    public API -- only the three trusted-internal primitives."""
    assert "get_or_create_billing_account" in parties.__all__
    assert "get_platform_merchant_account" in parties.__all__
    assert "get_agency_merchant_account" in parties.__all__
    assert "list_tenant_billing_accounts" in parties.__all__
    assert "MerchantAccountView" in parties.__all__
    assert "BillingAccountView" in parties.__all__
