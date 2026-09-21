"""Automation's own action registry (docs/ROADMAP.md Phase 10.3A,
`product/automation/actions.py::get_action_registry()`). No database, no
network -- a plain unit test, part of the default `pytest` run.

Complements `tests/foundation/test_workflow_actions_unit.py` (which
proves the generic contract) by proving the *migration* did not change
anything observable: Phase 10.2's own five actions still resolve, the
closed vocabulary is still exactly those five, and publish-time
validation still consults the static constant rather than the registry's
contents.
"""

from __future__ import annotations

import uuid

import pytest
from product.automation.actions import (
    ACTION_CREATE_TASK,
    ACTION_MOVE_OPPORTUNITY,
    ACTION_SEND_EMAIL,
    ACTION_SEND_WEBHOOK,
    ACTION_UPDATE_CONTACT,
    ACTIONS,
    execute_action,
    get_action_registry,
    validate_action_config,
)
from product.automation.errors import AutomationActionError, AutomationValidationError
from product.foundation.workflow_actions import (
    ActionConfig,
    ActionPayload,
    ActionResult,
    DuplicateWorkflowActionError,
    UnknownWorkflowActionError,
    WorkflowAction,
    WorkflowActionRegistry,
)

_PHASE_10_2_ACTIONS = frozenset(
    {
        ACTION_CREATE_TASK,
        ACTION_UPDATE_CONTACT,
        ACTION_MOVE_OPPORTUNITY,
        ACTION_SEND_EMAIL,
        ACTION_SEND_WEBHOOK,
    }
)


def test_registry_is_a_workflow_action_registry() -> None:
    assert isinstance(get_action_registry(), WorkflowActionRegistry)


def test_every_existing_action_resolves_through_the_registry() -> None:
    registry = get_action_registry()
    for action_type in _PHASE_10_2_ACTIONS:
        action = registry.get(action_type)
        assert isinstance(action, WorkflowAction)
        assert action.name == action_type


def test_registry_is_complete_and_closed_to_exactly_the_declared_vocabulary() -> None:
    """The declared vocabulary, the registered implementations, and
    Phase 10.2's own action list are all the same set -- no action is
    declared without an implementation, and none is registered without
    being declared."""
    registry = get_action_registry()
    assert ACTIONS == _PHASE_10_2_ACTIONS
    assert registry.allowed_names == _PHASE_10_2_ACTIONS
    assert registry.registered_names() == _PHASE_10_2_ACTIONS
    assert registry.missing_names() == frozenset()
    registry.require_complete()  # must not raise


def test_no_ai_or_other_foreign_action_is_registered_today() -> None:
    """Phase 10.3A adds the mechanism, not a sixth action. Phase 10.4A
    is the phase that introduces an AI action -- this asserts it has not
    been smuggled in early."""
    registry = get_action_registry()
    for name in ("invoke_ai", "ai", "create_invoice", "record_payment"):
        assert not registry.is_registered(name)
        assert name not in registry.allowed_names


def test_registering_an_undeclared_action_is_rejected() -> None:
    """The process-wide registry cannot be widened at runtime by a
    caller -- a would-be foreign action whose name is not in the
    declared vocabulary is refused."""

    class _Rogue:
        name = "delete_everything"

        def validate_config(self, config: ActionConfig, /) -> None: ...

        def execute(
            self,
            actor_user_id: uuid.UUID,
            tenant_id: uuid.UUID,
            config: ActionConfig,
            payload: ActionPayload,
            /,
        ) -> ActionResult:
            return {}

    with pytest.raises(UnknownWorkflowActionError):
        get_action_registry().register(_Rogue())


def test_re_registering_an_existing_action_is_rejected() -> None:
    """Guards the real failure mode a composition root could hit: wiring
    the same action twice must fail loudly, never silently replace a
    built-in implementation with another one."""

    class _Shadow:
        name = ACTION_CREATE_TASK

        def validate_config(self, config: ActionConfig, /) -> None: ...

        def execute(
            self,
            actor_user_id: uuid.UUID,
            tenant_id: uuid.UUID,
            config: ActionConfig,
            payload: ActionPayload,
            /,
        ) -> ActionResult:
            return {"hijacked": True}

    with pytest.raises(DuplicateWorkflowActionError):
        get_action_registry().register(_Shadow())
    # the built-in is untouched
    assert get_action_registry().get(ACTION_CREATE_TASK).name == ACTION_CREATE_TASK


def test_execute_action_rejects_an_unknown_action_type_as_a_validation_error() -> None:
    """`execute_action()`'s pre-10.3A contract preserved exactly: an
    unresolvable action_type surfaces as `AutomationValidationError`,
    which the durable engine classifies as permanent/non-retryable."""
    with pytest.raises(AutomationValidationError):
        execute_action("delete_everything", uuid.uuid4(), uuid.uuid4(), {}, {})


def test_validate_action_config_still_enforces_existing_rules() -> None:
    """Spot-check that routing validation through the registry preserved
    each action's own rules (the full per-action matrix remains in
    tests/automation/test_actions_unit.py, unchanged by this phase)."""
    with pytest.raises(AutomationValidationError):
        validate_action_config(ACTION_CREATE_TASK, {})
    validate_action_config(ACTION_CREATE_TASK, {"title": "Follow up"})

    validate_action_config(ACTION_UPDATE_CONTACT, {})  # all fields optional

    with pytest.raises(AutomationValidationError):
        validate_action_config(ACTION_SEND_WEBHOOK, {"url": "http://example.com/hook"})
    # SSRF refusal keeps raising AutomationActionError, not a validation
    # error -- the exact pre-10.3A behaviour asserted by
    # tests/automation/test_actions_unit.py::test_send_webhook_rejects_loopback_address
    with pytest.raises(AutomationActionError):
        validate_action_config(ACTION_SEND_WEBHOOK, {"url": "https://127.0.0.1/hook"})


def test_registry_holds_no_identity_or_authorization_state() -> None:
    """The registry maps names to implementations and nothing else --
    no cached actor, tenant, or authorization decision lives on it."""
    registry = get_action_registry()
    state = set(getattr(type(registry), "__slots__", ()))
    assert state == {"_actions", "_allowed_names"}
    assert not hasattr(registry, "__dict__")
