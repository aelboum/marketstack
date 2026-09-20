"""Bounded condition evaluation against a trigger event's own payload
(docs/ROADMAP.md Phase 10.2's own "condition evaluation" scope).

**No `eval()`, no `exec()`, no expression language, no arbitrary
code path** -- a condition is one of a fixed, closed set of comparison
operators applied to one named field of the event payload against one
literal value. This is a deliberately small interpreter, not a general
one: the entire vocabulary is `_OPERATORS` below, nothing else is ever
reachable regardless of what a caller supplies in a workflow definition
(this phase's own explicit "do not permit arbitrary Python/code execution
from an automation definition" requirement).

**A malformed/missing field never raises** -- a condition referencing a
field the payload does not have (or a type mismatch the operator cannot
compare) evaluates to `False` (condition not met), never an exception
that would abort evaluation of the remaining conditions or crash the
dispatcher. Only a condition whose own *shape* is invalid (unknown
operator, non-string field name) raises `AutomationConditionError` at
validation time (workflow create/update), never at evaluation time --
evaluation-time failures are always a silent `False`, by design.
"""

from __future__ import annotations

from collections.abc import Mapping

from product.automation.errors import AutomationConditionError

MAX_CONDITIONS = 10

_OPERATORS = frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "contains"})


def validate_conditions(conditions: list) -> None:
    """Raises `AutomationConditionError` for a structurally invalid
    condition list -- called at workflow create/update time, never at
    evaluation time (module docstring)."""
    if len(conditions) > MAX_CONDITIONS:
        raise AutomationConditionError(
            f"a workflow may declare at most {MAX_CONDITIONS} conditions."
        )
    for condition in conditions:
        if not isinstance(condition, Mapping):
            raise AutomationConditionError("each condition must be an object.")
        field = condition.get("field")
        op = condition.get("op")
        if not isinstance(field, str) or not field:
            raise AutomationConditionError("condition.field must be a non-empty string.")
        if op not in _OPERATORS:
            raise AutomationConditionError(
                f"condition.op must be one of {sorted(_OPERATORS)}, got {op!r}."
            )
        if "value" not in condition:
            raise AutomationConditionError("condition.value is required.")


def _compare(op: str, actual: object, expected: object) -> bool:
    try:
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "contains":
            return isinstance(actual, str) and isinstance(expected, str) and expected in actual
        # gt/gte/lt/lte -- only ever attempted on mutually comparable
        # types; any TypeError (e.g. str vs int) is caught below and
        # treated as "condition not met," never propagated.
        if op == "gt":
            return actual > expected  # type: ignore[operator]
        if op == "gte":
            return actual >= expected  # type: ignore[operator]
        if op == "lt":
            return actual < expected  # type: ignore[operator]
        if op == "lte":
            return actual <= expected  # type: ignore[operator]
    except TypeError:
        return False
    return False  # pragma: no cover -- unreachable, _OPERATORS is exhaustive above


def evaluate_conditions(conditions: list, payload: Mapping[str, object]) -> bool:
    """`True` only if every condition matches (implicit AND) -- an empty
    condition list always matches (a workflow with no conditions fires on
    every occurrence of its trigger type, the documented default)."""
    for condition in conditions:
        field = condition["field"]
        op = condition["op"]
        expected = condition["value"]
        actual = payload.get(field)
        if not _compare(op, actual, expected):
            return False
    return True


__all__ = ["MAX_CONDITIONS", "evaluate_conditions", "validate_conditions"]
