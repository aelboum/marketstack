"""Workflow-definition validation (docs/ROADMAP.md Phase 10.3's own
required "WORKFLOW DEFINITION" test group). Pure unit tests, no
database, no Temporal -- runs in the default `pytest` invocation.
"""

from __future__ import annotations

import pytest
from product.automation.durable.dsl import validate_workflow_definition
from product.automation.errors import AutomationConditionError, AutomationValidationError


def _action_step(step_key: str, next_step_key: str | None = None) -> dict:
    return {
        "step_key": step_key,
        "type": "action",
        "action_type": "create_task",
        "action_config": {"title": "Follow up"},
        "next_step_key": next_step_key,
    }


def _condition_step(step_key: str, *, true_key: str | None, false_key: str | None) -> dict:
    return {
        "step_key": step_key,
        "type": "condition",
        "conditions": [{"field": "stage", "op": "eq", "value": "won"}],
        "next_step_key_true": true_key,
        "next_step_key_false": false_key,
    }


def test_valid_single_step_workflow_publishes() -> None:
    validate_workflow_definition("s1", [_action_step("s1")])


def test_valid_multi_step_workflow_with_branch_publishes() -> None:
    steps = [
        _condition_step("s1", true_key="s2", false_key="s3"),
        _action_step("s2"),
        _action_step("s3"),
    ]
    validate_workflow_definition("s1", steps)


def test_missing_start_step_key_rejected() -> None:
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("does-not-exist", [_action_step("s1")])


def test_invalid_step_reference_rejected() -> None:
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s1", [_action_step("s1", next_step_key="ghost")])


def test_invalid_branch_destination_rejected() -> None:
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition(
            "s1", [_condition_step("s1", true_key="ghost", false_key=None)]
        )


def test_unsupported_action_type_rejected() -> None:
    step = _action_step("s1")
    step["action_type"] = "delete_the_database"
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s1", [step])


def test_malformed_condition_rejected() -> None:
    step = _condition_step("s1", true_key=None, false_key=None)
    step["conditions"] = [{"field": "stage", "op": "not_a_real_operator", "value": "won"}]
    # product.automation.conditions.validate_conditions() raises its own
    # AutomationConditionError (distinct from AutomationValidationError --
    # product/automation/errors.py's own docstring: "callers can tell
    # 'bad workflow definition' apart from 'bad API request shape'"),
    # reused here unchanged, never wrapped or re-typed.
    with pytest.raises(AutomationConditionError):
        validate_workflow_definition("s1", [step])


def test_duplicate_step_key_rejected() -> None:
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s1", [_action_step("s1"), _action_step("s1")])


def test_empty_step_list_rejected() -> None:
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s1", [])


def test_too_many_steps_rejected() -> None:
    step_count = 25
    steps = [
        _action_step(f"s{i}", next_step_key=f"s{i + 1}" if i < step_count - 1 else None)
        for i in range(step_count)
    ]
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s0", steps)


def test_direct_self_loop_rejected() -> None:
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s1", [_action_step("s1", next_step_key="s1")])


def test_indirect_cycle_rejected() -> None:
    steps = [_action_step("s1", next_step_key="s2"), _action_step("s2", next_step_key="s1")]
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s1", steps)


def test_delay_step_bounds_enforced() -> None:
    step = {"step_key": "s1", "type": "delay", "delay_seconds": 0, "next_step_key": None}
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s1", [step])


def test_wait_for_event_step_requires_known_event_type() -> None:
    step = {
        "step_key": "s1",
        "type": "wait_for_event",
        "event_type": "made.up.event",
        "timeout_seconds": 3600,
        "next_step_key": None,
        "timeout_step_key": None,
    }
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("s1", [step])


def test_step_key_charset_is_restricted() -> None:
    with pytest.raises(AutomationValidationError):
        validate_workflow_definition("bad key!", [_action_step("bad key!")])
