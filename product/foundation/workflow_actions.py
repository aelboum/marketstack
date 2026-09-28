"""The generic, domain-neutral workflow-action contract and registry
(docs/ROADMAP.md Phase 10.3A).

**Why this lives in `product/foundation/` and not in
`product/automation/`.** Phase 10.4A needs Automation to be able to
execute an action whose implementation belongs to another product
domain (`product.ai` first). The import-linter contracts in this
repository's own `pyproject.toml` forbid that edge in *both*
directions -- `product.ai` is in Automation's own `forbidden_modules`,
and `product.automation` is in AI's -- so neither package can import
the other, and no "narrow exception" edge is available either:
`product.ai` itself imports `product.conversations` and
`product.telephony`, which are also forbidden to Automation, so a
direct edge would create forbidden *indirect* chains as well (this
repository sets no `allow_indirect_imports` anywhere, by design).

The resolution is the one `docs/ARCHITECTURE.md` section 2.2 already
prescribes for exactly this shape -- "the capability is generic enough
to belong in `product/foundation`... promote it, don't duplicate it":
a dependency inversion, where both sides depend on a neutral contract
neither of them owns.

    product.automation  ---->  product.foundation.workflow_actions
                                          ^
                                          |
    product.<domain> adapter  ------------+

`product/foundation/` is the one always-allowed dependency *target*,
and itself imports no other product module -- so this file must stay
domain-neutral. It knows nothing about CRM, AI, Conversations,
Telephony, or Accounting; it defines only what Automation genuinely
needs in order to identify an action, validate its configuration,
execute it, and classify the resulting error. Mirrors
`product/foundation/storage.py`'s own `Protocol`-plus-neutral-errors
shape rather than inventing a new one.

**The closed vocabulary is declared, never accumulated.** A registry is
constructed with an explicit, finite `allowed_names` set and will
refuse to register anything outside it. That inversion is deliberate
and is what keeps publish-time validation deterministic: the set of
*publishable* action names is a static constant owned by Automation
(`product.automation.actions.ACTIONS`), never "whatever happens to have
been registered by the time the first workflow is published." Importing
some unrelated module can therefore never change which workflows
validate. `require_complete()` closes the other half of that guarantee
at bootstrap: a declared name with no registered implementation is a
loud startup failure, not a surprise at execution time.

**This module holds no authorization, no tenant truth, and no state
beyond the registration table itself.** An action's `execute` receives
the acting identity and tenant from its caller on every single call and
is expected to re-authorize through its own domain's existing
authorization boundary -- exactly as `product/automation/actions.py`'s
own actions already do. Nothing here caches, elevates, or stands in for
an authorization decision, and there is no global mutable "current
actor" anywhere in this contract.

**Step-output chaining (docs/ROADMAP.md Phase 26C).** The durable engine
already makes every prior action step's own bounded result available to
later steps, via a flat context merge
(`product/automation/durable/production_workflow.py::_run_action_step()`)
plus, since this phase, one additional namespaced entry per step
(`step_output_context_key()` below) -- this module owns only the
generic, domain-neutral *reference* concept built on top of that: a
closed marker shape a workflow author may place as a complete
`action_config` field value (`parse_step_output_reference()`), and a
pure function resolving every such marker against a run's own context
(`resolve_step_output_references()`). Deliberately narrow: no
expression language, no templating, no string interpolation, no
recursive traversal into nested dicts/lists -- a config field's value is
either an ordinary literal or exactly one complete reference, never a
mix. This module still knows nothing about steps' *ordering* (whether
one step is guaranteed to run before another) -- that is a workflow-graph
property only `product/automation/durable/dsl.py` can determine, and
remains that module's own responsibility; this one only recognizes and
resolves a reference already known to be valid.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

ActionConfig = Mapping[str, object]
ActionPayload = Mapping[str, object]
ActionResult = dict[str, object]


class WorkflowActionConfigError(ValueError):
    """Raised by an action's own `validate_config`/`execute` for a
    malformed or unusable action configuration. A **permanent** outcome:
    retrying an invalid definition can never make it valid. Domain
    adapters outside `product.automation` raise this (they cannot import
    `product.automation.errors`); Automation's own built-in actions keep
    raising their existing `AutomationValidationError` unchanged, and
    both are classified identically by the durable engine."""


class WorkflowActionDeniedError(PermissionError):
    """Raised when the acting identity is not authorized to perform the
    action at execution time. A **permanent** outcome -- never retried,
    because a denial is an answer, not a transient failure.

    Raising this never *performs* an authorization check: the real check
    belongs to the domain's own existing authorization boundary, and this
    type only carries that boundary's decision back to Automation in a
    domain-neutral form."""


class WorkflowActionExecutionError(RuntimeError):
    """Raised when an action's execution fails for a reason that is not a
    configuration or authorization problem (a provider/transport failure,
    say). Treated as potentially **transient** by the durable engine's
    bounded retry policy, matching how `AutomationActionError` is already
    treated today."""


class UnknownWorkflowActionError(LookupError):
    """Raised by `WorkflowActionRegistry.get()` for a name with no
    registered implementation."""


class DuplicateWorkflowActionError(ValueError):
    """Raised by `WorkflowActionRegistry.register()` when a name is
    registered twice. Deliberately an error rather than a silent
    overwrite: last-registration-wins would make behaviour depend on
    import order, which is precisely what this design exists to prevent."""


@runtime_checkable
class WorkflowAction(Protocol):
    """One executable workflow action. Domain-neutral by construction --
    every parameter below is either a primitive, a UUID, or a plain
    mapping; no domain type ever crosses this boundary."""

    @property
    def name(self) -> str:
        """The action's stable vocabulary name (`"create_task"`, ...) --
        the same string a workflow definition stores."""
        ...

    def validate_config(self, config: ActionConfig, /) -> None:
        """Structural validation, run at workflow create/update/publish
        time. Raises `WorkflowActionConfigError` (or a caller-domain
        equivalent) for a malformed configuration; returns `None` when the
        configuration is usable. Must be pure: no I/O, no authorization,
        no tenant lookup -- it runs against a definition, not a run.

        Position-only (`/`) throughout this Protocol: an implementation is
        free to name its own parameters whatever reads best in its own
        domain, and a plain function can satisfy the contract directly --
        which is what lets `WorkflowActionSpec` wrap the existing
        `_validate_*`/`_execute_*` functions with no rewrite."""
        ...

    def execute(
        self,
        actor_user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        config: ActionConfig,
        payload: ActionPayload,
        /,
    ) -> ActionResult:
        """Perform the action as `actor_user_id` within `tenant_id`, and
        return a bounded, JSON-serializable result.

        The identity and tenant are passed on **every** call and are the
        only authority the implementation may act on -- it must
        re-authorize through its own domain's existing authorization
        boundary at this moment, never trust a decision made when the
        workflow was defined or started."""
        ...


@dataclass(frozen=True, slots=True)
class WorkflowActionSpec:
    """The concrete, function-backed `WorkflowAction` implementation used
    by every action in this codebase today. A frozen dataclass rather than
    a class hierarchy: an action is a name plus two functions, and
    `product/automation/actions.py`'s own existing actions are already
    written exactly that way (a `_validate_*` branch and an `_execute_*`
    function), so adopting the registry needed no rewrite of any of
    them."""

    name: str
    validate_config: Callable[[ActionConfig], None]
    execute: Callable[[uuid.UUID, uuid.UUID, ActionConfig, ActionPayload], ActionResult]


class WorkflowActionRegistry:
    """Deterministic registration and lookup of workflow-action
    implementations, constrained to a declared, closed vocabulary.

    Determinism comes from three properties, each independently tested:
    `allowed_names` is fixed at construction and never grows; registering
    an unknown name raises; registering the same name twice raises rather
    than overwriting. Consequently the registry's observable content
    depends only on *which* registrations were performed, never on the
    order they happened in or on which modules an interpreter happened to
    import first."""

    __slots__ = ("_actions", "_allowed_names")

    def __init__(self, *, allowed_names: frozenset[str]) -> None:
        self._allowed_names = allowed_names
        self._actions: dict[str, WorkflowAction] = {}

    @property
    def allowed_names(self) -> frozenset[str]:
        """The declared closed vocabulary. Publish-time validation uses
        this (or Automation's own equivalent constant), never
        `registered_names()` -- so a workflow's validity never depends on
        what has been wired up in the current process."""
        return self._allowed_names

    def register(self, action: WorkflowAction) -> None:
        name = action.name
        if name not in self._allowed_names:
            raise UnknownWorkflowActionError(
                f"{name!r} is not in this registry's declared action vocabulary "
                f"{sorted(self._allowed_names)} -- an action name must be declared "
                f"before an implementation can be registered for it."
            )
        if name in self._actions:
            raise DuplicateWorkflowActionError(
                f"a workflow action named {name!r} is already registered."
            )
        self._actions[name] = action

    def get(self, name: str) -> WorkflowAction:
        action = self._actions.get(name)
        if action is None:
            raise UnknownWorkflowActionError(f"no workflow action is registered for {name!r}.")
        return action

    def is_registered(self, name: str) -> bool:
        return name in self._actions

    def registered_names(self) -> frozenset[str]:
        """What actually has an implementation right now. Distinct from
        `allowed_names` on purpose -- see that property's own docstring."""
        return frozenset(self._actions)

    def missing_names(self) -> frozenset[str]:
        return self._allowed_names - frozenset(self._actions)

    def require_complete(self) -> None:
        """Assert every declared name has an implementation. Called once
        at bootstrap so a declared-but-unwired action fails loudly at
        startup rather than at the first workflow run that reaches it."""
        missing = self.missing_names()
        if missing:
            raise UnknownWorkflowActionError(
                f"declared workflow actions have no registered implementation: {sorted(missing)}."
            )


#: The one reserved marker key recognized by `parse_step_output_reference()`.
#: No existing action_config field in this repository is ever dict-shaped
#: (every one of `product/automation/actions.py`'s own actions reads flat
#: strings only), so this key cannot collide with any legitimate existing
#: configuration value.
_STEP_OUTPUT_REFERENCE_KEY = "$step_output"

#: The small, closed set of value types a referenced output field may
#: resolve to -- never a list, dict, set, bytes, or other structured/
#: arbitrary object (docs/ROADMAP.md Phase 26C's own explicit bound,
#: matching `product/automation/durable/models.py::Run.context`'s own
#: "ids and small scalars only" discipline).
_SCALAR_TYPES: tuple[type, ...] = (bool, int, float, str, type(None))


@dataclass(frozen=True, slots=True)
class StepOutputReference:
    """A parsed, shape-validated `{"$step_output": {"step": ...,
    "field": ...}}` reference -- see `parse_step_output_reference()`.
    Names a step_key and a field name only; nothing about what produced
    them."""

    step: str
    field: str


def parse_step_output_reference(value: object) -> StepOutputReference | None:
    """Recognize a complete-value step-output reference.

    Returns `None` for any ordinary, non-reference value -- a plain
    string, a list, or a mapping that does not carry the reserved
    `"$step_output"` key -- so no existing or future ordinary
    `action_config` value is ever affected, and a reference nested inside
    a list or another mapping is never unwrapped (this function inspects
    exactly the value it is given, never recurses).

    Once the reserved key is present, the shape is strict:
    `"$step_output"` must be the value's *only* key, its own value must be
    a mapping with *exactly* `"step"` and `"field"` keys, and both must be
    non-empty strings. Any deviation raises `WorkflowActionConfigError`
    rather than silently falling through as an ordinary (and then
    presumably invalid) value -- an attempted reference is never
    reinterpreted as literal configuration."""
    if not isinstance(value, Mapping):
        return None
    if _STEP_OUTPUT_REFERENCE_KEY not in value:
        return None
    if set(value.keys()) != {_STEP_OUTPUT_REFERENCE_KEY}:
        raise WorkflowActionConfigError(
            f"a {_STEP_OUTPUT_REFERENCE_KEY!r} reference must be the field's only value."
        )
    inner = value[_STEP_OUTPUT_REFERENCE_KEY]
    if not isinstance(inner, Mapping) or set(inner.keys()) != {"step", "field"}:
        raise WorkflowActionConfigError(
            f"{_STEP_OUTPUT_REFERENCE_KEY!r} must be an object with exactly 'step' and "
            "'field' keys."
        )
    step = inner.get("step")
    field_name = inner.get("field")
    if not isinstance(step, str) or not step:
        raise WorkflowActionConfigError(
            f"{_STEP_OUTPUT_REFERENCE_KEY!r}.step must be a non-empty string."
        )
    if not isinstance(field_name, str) or not field_name:
        raise WorkflowActionConfigError(
            f"{_STEP_OUTPUT_REFERENCE_KEY!r}.field must be a non-empty string."
        )
    return StepOutputReference(step=step, field=field_name)


def step_output_context_key(step_key: str) -> str:
    """The reserved, collision-resistant context key a step's own action
    output is namespaced under: `f"{step_key}.output"` -- the identical
    dotted convention `product/automation/durable/production_workflow.py
    ::_run_wait_step()` already established for its own
    `f"{step_key}.event"` entry. A `step_key` can never itself contain
    `"."` (`product/automation/durable/dsl.py::_STEP_KEY_PATTERN`), so this
    key can never collide with another step's own namespaced entry or
    with any pre-existing flat context key."""
    return f"{step_key}.output"


def resolve_step_output_references(
    config: ActionConfig, context: Mapping[str, object]
) -> ActionConfig:
    """Pure, domain-neutral substitution: return a new mapping with every
    top-level `$step_output` reference in `config` replaced by the bounded
    scalar value it names in `context`, and every ordinary value carried
    through unchanged. A pure function of exactly these two arguments --
    no I/O, no clock, no randomness -- so the same `(config, context)`
    pair always resolves identically, which is what lets a Temporal
    activity retry re-resolve the same reference safely with no caching
    (docs/ROADMAP.md Phase 26C).

    Raises `WorkflowActionConfigError` -- already one of the durable
    engine's existing permanent/non-retryable error types
    (`product/automation/durable/business_activities.py`) -- when a
    reference is malformed, names a step with no recorded output in
    `context`, names a field absent from that step's own output, or names
    a field whose value is not one of the small bounded scalar types this
    phase allows to cross into workflow context (`None`/`bool`/`int`/
    `float`/`str`) -- never a list, dict, or other structured value, and
    never silently stringified."""
    resolved: dict[str, object] = {}
    for key, value in config.items():
        reference = parse_step_output_reference(value)
        if reference is None:
            resolved[key] = value
            continue
        step_output = context.get(step_output_context_key(reference.step))
        if not isinstance(step_output, Mapping):
            raise WorkflowActionConfigError(
                f"{_STEP_OUTPUT_REFERENCE_KEY!r} references step {reference.step!r}, which "
                "has no recorded output in this run's context."
            )
        if reference.field not in step_output:
            raise WorkflowActionConfigError(
                f"{_STEP_OUTPUT_REFERENCE_KEY!r} references field {reference.field!r} on "
                f"step {reference.step!r}, which its output does not contain."
            )
        field_value = step_output[reference.field]
        if not isinstance(field_value, _SCALAR_TYPES):
            raise WorkflowActionConfigError(
                f"{_STEP_OUTPUT_REFERENCE_KEY!r} references field {reference.field!r} on "
                f"step {reference.step!r}, whose value is not a scalar suitable for "
                "workflow context."
            )
        resolved[key] = field_value
    return resolved


__all__ = [
    "ActionConfig",
    "ActionPayload",
    "ActionResult",
    "DuplicateWorkflowActionError",
    "StepOutputReference",
    "UnknownWorkflowActionError",
    "WorkflowAction",
    "WorkflowActionConfigError",
    "WorkflowActionDeniedError",
    "WorkflowActionExecutionError",
    "WorkflowActionRegistry",
    "WorkflowActionSpec",
    "parse_step_output_reference",
    "resolve_step_output_references",
    "step_output_context_key",
]
