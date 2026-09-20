"""Bounded condition evaluation (docs/ROADMAP.md Phase 10.2). No
database -- a plain unit test, part of the default `pytest` run.
"""

from __future__ import annotations

import pytest
from product.automation.conditions import (
    MAX_CONDITIONS,
    evaluate_conditions,
    validate_conditions,
)
from product.automation.errors import AutomationConditionError


def test_empty_conditions_always_match() -> None:
    assert evaluate_conditions([], {"anything": 1}) is True


def test_eq_condition_matches() -> None:
    conditions = [{"field": "to_stage_id", "op": "eq", "value": "abc"}]
    assert evaluate_conditions(conditions, {"to_stage_id": "abc"}) is True
    assert evaluate_conditions(conditions, {"to_stage_id": "xyz"}) is False


def test_missing_field_evaluates_false_never_raises() -> None:
    conditions = [{"field": "missing", "op": "eq", "value": "x"}]
    assert evaluate_conditions(conditions, {}) is False


def test_type_mismatch_evaluates_false_never_raises() -> None:
    conditions = [{"field": "amount", "op": "gt", "value": 100}]
    assert evaluate_conditions(conditions, {"amount": "not-a-number"}) is False


def test_gt_gte_lt_lte_numeric() -> None:
    assert evaluate_conditions([{"field": "n", "op": "gt", "value": 5}], {"n": 6}) is True
    assert evaluate_conditions([{"field": "n", "op": "gt", "value": 5}], {"n": 5}) is False
    assert evaluate_conditions([{"field": "n", "op": "gte", "value": 5}], {"n": 5}) is True
    assert evaluate_conditions([{"field": "n", "op": "lt", "value": 5}], {"n": 4}) is True
    assert evaluate_conditions([{"field": "n", "op": "lte", "value": 5}], {"n": 5}) is True


def test_contains_operator() -> None:
    conditions = [{"field": "body", "op": "contains", "value": "urgent"}]
    assert evaluate_conditions(conditions, {"body": "this is urgent"}) is True
    assert evaluate_conditions(conditions, {"body": "not"}) is False


def test_multiple_conditions_are_and() -> None:
    conditions = [
        {"field": "a", "op": "eq", "value": 1},
        {"field": "b", "op": "eq", "value": 2},
    ]
    assert evaluate_conditions(conditions, {"a": 1, "b": 2}) is True
    assert evaluate_conditions(conditions, {"a": 1, "b": 3}) is False


def test_validate_conditions_rejects_unknown_operator() -> None:
    with pytest.raises(AutomationConditionError):
        validate_conditions([{"field": "a", "op": "regex", "value": "x"}])


def test_validate_conditions_rejects_non_string_field() -> None:
    with pytest.raises(AutomationConditionError):
        validate_conditions([{"field": 123, "op": "eq", "value": "x"}])


def test_validate_conditions_rejects_missing_value() -> None:
    with pytest.raises(AutomationConditionError):
        validate_conditions([{"field": "a", "op": "eq"}])


def test_validate_conditions_rejects_non_object() -> None:
    with pytest.raises(AutomationConditionError):
        validate_conditions(["not-a-dict"])


def test_validate_conditions_rejects_too_many() -> None:
    conditions = [{"field": f"f{i}", "op": "eq", "value": i} for i in range(MAX_CONDITIONS + 1)]
    with pytest.raises(AutomationConditionError):
        validate_conditions(conditions)


def test_validate_conditions_accepts_max_count() -> None:
    conditions = [{"field": f"f{i}", "op": "eq", "value": i} for i in range(MAX_CONDITIONS)]
    validate_conditions(conditions)  # must not raise
