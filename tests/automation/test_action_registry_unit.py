"""Automation's own action registry (docs/ROADMAP.md Phase 10.3A,
`product/automation/actions.py::get_action_registry()`; Phase 10.4A
integrates the first foreign action into it). No database, no network --
a plain unit test, part of the default `pytest` run. Pure in-memory
composition (`wire_production_automation_actions()`) needs no database
either -- proven directly here, not merely inferred.

Complements `tests/foundation/test_workflow_actions_unit.py` (which
proves the generic contract) and `tests/ai/test_automation_action_unit.py`
(which proves the AI-owned adapter in isolation) by proving the
*integration*: Phase 10.2's own five actions still resolve unchanged,
`ACTION_AI_QUALIFY_LEAD` is now declared and, once the explicit
composition root has run, registered as a sixth, and publish-time
validation still consults the static `ACTIONS` constant rather than the
registry's own contents.

**Module-scoped composition, called once, explicitly -- not an import
side effect.** `_ensure_production_actions_composed()` below is an
`autouse` fixture that calls the real composition-root function
(`product/action_registry_composition.py::wire_production_automation_actions()`)
before any test in this file runs. This is the same call
`product/api/main.py::create_app()` makes at real startup; running it
here proves the *steady state* every one of this file's other tests
should see, and proves it is idempotent (every test in this file, and
`test_app_smoke.py`, which also calls `create_app()`, would otherwise
each attempt registration again)."""

from __future__ import annotations

import uuid

import pytest
from product.action_registry_composition import wire_production_automation_actions
from product.automation.actions import (
    ACTION_AI_QUALIFY_LEAD,
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
_PRODUCTION_ACTIONS = _PHASE_10_2_ACTIONS | {ACTION_AI_QUALIFY_LEAD}


@pytest.fixture(autouse=True, scope="module")
def _ensure_production_actions_composed() -> None:
    wire_production_automation_actions()


def test_registry_is_a_workflow_action_registry() -> None:
    assert isinstance(get_action_registry(), WorkflowActionRegistry)


def test_every_existing_action_resolves_through_the_registry() -> None:
    registry = get_action_registry()
    for action_type in _PHASE_10_2_ACTIONS:
        action = registry.get(action_type)
        assert isinstance(action, WorkflowAction)
        assert action.name == action_type


def test_ai_action_resolves_through_the_registry_after_composition() -> None:
    registry = get_action_registry()
    action = registry.get(ACTION_AI_QUALIFY_LEAD)
    assert isinstance(action, WorkflowAction)
    assert action.name == ACTION_AI_QUALIFY_LEAD


def test_registry_is_complete_and_closed_to_exactly_the_declared_vocabulary() -> None:
    """The declared vocabulary, the registered implementations, and the
    production action list (Phase 10.2's own five, plus Phase 10.4A's AI
    action) are all the same set -- no action is declared without an
    implementation, and none is registered without being declared."""
    registry = get_action_registry()
    assert ACTIONS == _PRODUCTION_ACTIONS
    assert registry.allowed_names == _PRODUCTION_ACTIONS
    assert registry.registered_names() == _PRODUCTION_ACTIONS
    assert registry.missing_names() == frozenset()
    registry.require_complete()  # must not raise


def test_composition_is_deterministic_regardless_of_call_count() -> None:
    """`wire_production_automation_actions()` is idempotent -- calling it
    again (as `create_app()` would on a second invocation, or as this
    file's own fixture already has) changes nothing observable."""
    before = get_action_registry().registered_names()
    wire_production_automation_actions()
    wire_production_automation_actions()
    after = get_action_registry().registered_names()
    assert before == after == _PRODUCTION_ACTIONS


def test_no_other_foreign_action_is_registered() -> None:
    """Exactly one foreign action exists today -- `ACTION_AI_QUALIFY_LEAD`.
    No accounting action, and no *other* AI capability, was smuggled in
    alongside it."""
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


def test_re_registering_the_ai_action_is_also_rejected() -> None:
    """The duplicate-registration guard applies identically to the
    foreign, composed-in action, not only the five built-in ones."""

    class _ShadowAI:
        name = ACTION_AI_QUALIFY_LEAD

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
        get_action_registry().register(_ShadowAI())
    assert get_action_registry().get(ACTION_AI_QUALIFY_LEAD).name == ACTION_AI_QUALIFY_LEAD


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


def test_automation_source_never_imports_product_ai() -> None:
    """Static, source-level confirmation of the dependency-inversion
    boundary -- independent of import-linter, which this test does not
    invoke. Reads the actual `.py` files under `product/automation/`
    (excluding this test file itself, which is not one of them) and
    asserts none contains an import of `product.ai`."""
    import pathlib
    import re

    automation_root = pathlib.Path(__file__).resolve().parents[2] / "product" / "automation"
    pattern = re.compile(r"^\s*(from|import)\s+product\.ai\b", re.MULTILINE)
    offenders = [
        str(path)
        for path in automation_root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_ai_source_never_imports_product_automation() -> None:
    """The mirror-image static check -- `product/ai/` never imports
    `product.automation` either, including this phase's own new adapter
    (`product/ai/automation_action.py`)."""
    import pathlib
    import re

    ai_root = pathlib.Path(__file__).resolve().parents[2] / "product" / "ai"
    pattern = re.compile(r"^\s*(from|import)\s+product\.automation\b", re.MULTILINE)
    offenders = [
        str(path)
        for path in ai_root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
