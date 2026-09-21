"""`product/billing/subscriptions.py::_resale_plan_id_from_key()` -- pure,
no-database. Not marked `integration` -- runs in the default `pytest`
invocation.
"""

from __future__ import annotations

import uuid

from product.billing.subscriptions import _resale_plan_id_from_key


def test_resale_plan_id_from_key_parses_resale_prefixed_key() -> None:
    resale_plan_id = uuid.uuid4()
    assert _resale_plan_id_from_key(f"resale:{resale_plan_id}") == resale_plan_id


def test_resale_plan_id_from_key_returns_none_for_platform_key() -> None:
    assert _resale_plan_id_from_key("starter-monthly") is None


def test_resale_plan_id_from_key_returns_none_for_none() -> None:
    assert _resale_plan_id_from_key(None) is None


def test_resale_plan_id_from_key_returns_none_for_malformed_suffix() -> None:
    assert _resale_plan_id_from_key("resale:not-a-uuid") is None
