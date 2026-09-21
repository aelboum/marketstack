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
    UnknownWorkflowActionError,
    WorkflowAction,
    WorkflowActionRegistry,
    WorkflowActionSpec,
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
