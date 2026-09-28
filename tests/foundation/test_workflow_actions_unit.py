"""`WorkflowActionRegistry`/`WorkflowActionSpec` (docs/ROADMAP.md Phase
10.3A, `product/foundation/workflow_actions.py`). No database, no
network -- a plain unit test, part of the default `pytest` run.

The determinism properties proven here are the whole point of the phase:
the publishable vocabulary is declared, not accumulated; registration
cannot introduce a name outside it; and a duplicate registration is an
error rather than a silent last-one-wins overwrite (which is exactly how
import order would otherwise leak into behaviour).
"""

from __future__ import annotations

import uuid

import pytest
from product.foundation.workflow_actions import (
    ActionConfig,
    ActionPayload,
    ActionResult,
    DuplicateWorkflowActionError,
    StepOutputReference,
    UnknownWorkflowActionError,
    WorkflowAction,
    WorkflowActionConfigError,
    WorkflowActionRegistry,
    WorkflowActionSpec,
    parse_step_output_reference,
    resolve_step_output_references,
    step_output_context_key,
)

_ALLOWED = frozenset({"alpha", "beta"})


def _spec(name: str, *, calls: list[str] | None = None) -> WorkflowActionSpec:
    def _validate(config: ActionConfig) -> None:
        if config.get("bad"):
            raise ValueError(f"{name}: bad config")

    def _execute(
        actor_user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        config: ActionConfig,
        payload: ActionPayload,
    ) -> ActionResult:
        if calls is not None:
            calls.append(name)
        return {"action": name, "actor": str(actor_user_id), "tenant": str(tenant_id)}

    return WorkflowActionSpec(name=name, validate_config=_validate, execute=_execute)


def test_spec_satisfies_the_protocol() -> None:
    assert isinstance(_spec("alpha"), WorkflowAction)


def test_register_and_get_round_trip() -> None:
    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    spec = _spec("alpha")
    registry.register(spec)
    assert registry.get("alpha") is spec
    assert registry.is_registered("alpha")


def test_get_unknown_name_is_rejected() -> None:
    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    with pytest.raises(UnknownWorkflowActionError):
        registry.get("alpha")  # declared, but no implementation registered
    with pytest.raises(UnknownWorkflowActionError):
        registry.get("never_declared")


def test_registering_a_name_outside_the_declared_vocabulary_is_rejected() -> None:
    """The registry cannot be used to smuggle a new publishable action
    name in at runtime -- the vocabulary is fixed at construction."""
    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    with pytest.raises(UnknownWorkflowActionError):
        registry.register(_spec("delete_everything"))
    assert not registry.is_registered("delete_everything")


def test_duplicate_registration_is_rejected_deterministically() -> None:
    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    first = _spec("alpha")
    registry.register(first)
    with pytest.raises(DuplicateWorkflowActionError):
        registry.register(_spec("alpha"))
    # the original implementation is still the one that resolves --
    # a rejected duplicate never partially overwrites.
    assert registry.get("alpha") is first


def test_registration_order_does_not_affect_observable_content() -> None:
    forward = WorkflowActionRegistry(allowed_names=_ALLOWED)
    forward.register(_spec("alpha"))
    forward.register(_spec("beta"))

    reverse = WorkflowActionRegistry(allowed_names=_ALLOWED)
    reverse.register(_spec("beta"))
    reverse.register(_spec("alpha"))

    assert forward.registered_names() == reverse.registered_names()
    assert forward.allowed_names == reverse.allowed_names
    assert forward.missing_names() == reverse.missing_names() == frozenset()


def test_allowed_names_is_independent_of_what_is_registered() -> None:
    """`allowed_names` (what may be published) never changes as
    implementations are wired up -- this is what keeps publish-time
    validation deterministic."""
    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    assert registry.allowed_names == _ALLOWED
    assert registry.registered_names() == frozenset()
    registry.register(_spec("alpha"))
    assert registry.allowed_names == _ALLOWED
    assert registry.registered_names() == frozenset({"alpha"})


def test_require_complete_flags_a_declared_but_unwired_action() -> None:
    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    registry.register(_spec("alpha"))
    assert registry.missing_names() == frozenset({"beta"})
    with pytest.raises(UnknownWorkflowActionError):
        registry.require_complete()
    registry.register(_spec("beta"))
    registry.require_complete()  # must not raise


def test_execute_receives_the_caller_supplied_identity_every_call() -> None:
    """No ambient/global identity: the acting user and tenant are
    arguments on every invocation, so nothing can be cached or elevated
    by the registry itself."""
    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    registry.register(_spec("alpha"))
    actor, tenant = uuid.uuid4(), uuid.uuid4()
    result = registry.get("alpha").execute(actor, tenant, {}, {})
    assert result == {"action": "alpha", "actor": str(actor), "tenant": str(tenant)}

    other_actor, other_tenant = uuid.uuid4(), uuid.uuid4()
    other = registry.get("alpha").execute(other_actor, other_tenant, {}, {})
    assert other["actor"] == str(other_actor)
    assert other["tenant"] == str(other_tenant)


def test_validate_config_is_delegated_to_the_registered_action() -> None:
    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    registry.register(_spec("alpha"))
    registry.get("alpha").validate_config({})  # must not raise
    with pytest.raises(ValueError):
        registry.get("alpha").validate_config({"bad": True})


def test_a_foreign_domain_can_supply_an_action_without_automation_importing_it() -> None:
    """The dependency inversion itself, proven without touching
    `product.ai` (Phase 10.4A's own work, not this phase's).

    This module -- which `product.automation` does not import and has
    never heard of -- supplies a working action purely by satisfying the
    neutral contract. That is exactly the shape a `product.ai` adapter
    will take: the domain depends on `product.foundation`, Automation
    depends on `product.foundation`, and neither imports the other.
    """

    class _ForeignDomainAction:
        """Stands in for a future domain adapter. Deliberately a plain
        class, not a `WorkflowActionSpec`, to prove the Protocol -- not
        one concrete helper -- is the real contract."""

        name = "beta"

        def validate_config(self, config: ActionConfig, /) -> None:
            if "capability" not in config:
                raise ValueError("capability is required")

        def execute(
            self,
            actor_user_id: uuid.UUID,
            tenant_id: uuid.UUID,
            config: ActionConfig,
            payload: ActionPayload,
            /,
        ) -> ActionResult:
            return {"capability": config["capability"], "tenant": str(tenant_id)}

    action = _ForeignDomainAction()
    assert isinstance(action, WorkflowAction)

    registry = WorkflowActionRegistry(allowed_names=_ALLOWED)
    registry.register(action)

    tenant = uuid.uuid4()
    assert registry.get("beta").execute(uuid.uuid4(), tenant, {"capability": "x"}, {}) == {
        "capability": "x",
        "tenant": str(tenant),
    }
    with pytest.raises(ValueError):
        registry.get("beta").validate_config({})


# --- step-output reference parsing/resolution (docs/ROADMAP.md Phase 26C) --


def test_step_output_context_key_is_dotted_and_step_scoped() -> None:
    assert step_output_context_key("qualify_lead") == "qualify_lead.output"
    assert step_output_context_key("s1") != step_output_context_key("s2")


def test_parse_ordinary_values_are_not_references() -> None:
    assert parse_step_output_reference("a plain string") is None
    assert parse_step_output_reference(123) is None
    assert parse_step_output_reference(None) is None
    assert parse_step_output_reference([1, 2, 3]) is None
    assert parse_step_output_reference({"an": "ordinary dict"}) is None


def test_parse_valid_reference() -> None:
    reference = parse_step_output_reference(
        {"$step_output": {"step": "qualify_lead", "field": "decision"}}
    )
    assert reference == StepOutputReference(step="qualify_lead", field="decision")


@pytest.mark.parametrize(
    "value",
    [
        {"$step_output": {}},
        {"$step_output": {"step": "x"}},
        {"$step_output": {"field": "decision"}},
        {"$step_output": {"step": 123, "field": "decision"}},
        {"$step_output": {"step": "x", "field": 123}},
        {"$step_output": {"step": "", "field": "decision"}},
        {"$step_output": {"step": "x", "field": ""}},
        {"$step_output": {"step": "x", "field": "decision", "extra": True}},
        {"$step_output": "not an object"},
        {"$step_output": {"step": "x", "field": "decision"}, "extra_outer_key": True},
    ],
)
def test_parse_malformed_reference_rejected(value: object) -> None:
    with pytest.raises(WorkflowActionConfigError):
        parse_step_output_reference(value)


def test_resolve_scalar_string_value() -> None:
    context = {"qualify_lead.output": {"decision": "qualified", "contact_id": "c1"}}
    config = {"title": {"$step_output": {"step": "qualify_lead", "field": "decision"}}}
    assert resolve_step_output_references(config, context) == {"title": "qualified"}


@pytest.mark.parametrize("value", [True, False, 42, 3.14, None])
def test_resolve_other_supported_scalar_types(value: object) -> None:
    context = {"s1.output": {"field": value}}
    config = {"x": {"$step_output": {"step": "s1", "field": "field"}}}
    assert resolve_step_output_references(config, context) == {"x": value}


def test_resolve_ordinary_values_pass_through_unchanged() -> None:
    config = {"title": "a literal string", "count": 5}
    assert resolve_step_output_references(config, {}) == config


def test_resolve_missing_step_output_fails() -> None:
    config = {"title": {"$step_output": {"step": "nope", "field": "decision"}}}
    with pytest.raises(WorkflowActionConfigError):
        resolve_step_output_references(config, {})


def test_resolve_missing_field_fails() -> None:
    context = {"qualify_lead.output": {"decision": "qualified"}}
    config = {"title": {"$step_output": {"step": "qualify_lead", "field": "reason"}}}
    with pytest.raises(WorkflowActionConfigError):
        resolve_step_output_references(config, context)


@pytest.mark.parametrize("value", [["a", "list"], {"a": "dict"}, {1, 2, 3}, b"bytes"])
def test_resolve_non_scalar_output_rejected(value: object) -> None:
    context = {"qualify_lead.output": {"decision": value}}
    config = {"title": {"$step_output": {"step": "qualify_lead", "field": "decision"}}}
    with pytest.raises(WorkflowActionConfigError):
        resolve_step_output_references(config, context)


def test_resolve_malformed_reference_still_fails_inside_resolver() -> None:
    config = {"title": {"$step_output": {"step": "x"}}}
    with pytest.raises(WorkflowActionConfigError):
        resolve_step_output_references(config, {})


def test_resolve_is_a_pure_function_stable_across_repeated_calls() -> None:
    """Retry-safety (docs/ROADMAP.md Phase 26C): the same `(config,
    context)` pair must resolve identically every time, with no hidden
    state or caching."""
    context = {"qualify_lead.output": {"decision": "qualified"}}
    config = {"title": {"$step_output": {"step": "qualify_lead", "field": "decision"}}}
    first = resolve_step_output_references(config, context)
    second = resolve_step_output_references(config, context)
    assert first == second == {"title": "qualified"}


def test_reference_embedded_in_a_string_is_not_resolved() -> None:
    """No string interpolation -- a reference is recognized only as a
    field's complete value, never as text inside an ordinary string."""
    config = {"title": "Decision: {$step_output}"}
    assert resolve_step_output_references(config, {}) == config


def test_reference_nested_inside_a_list_is_not_unwrapped() -> None:
    reference = {"$step_output": {"step": "qualify_lead", "field": "decision"}}
    config = {"title": [reference]}
    # Not recognized as a top-level reference -- carried through unchanged,
    # exactly like any other ordinary (here, list-shaped) config value.
    assert resolve_step_output_references(config, {}) == config


def test_reference_nested_inside_another_dict_is_not_unwrapped() -> None:
    reference = {"$step_output": {"step": "qualify_lead", "field": "decision"}}
    config = {"title": {"nested": reference}}
    assert resolve_step_output_references(config, {}) == config
