"""Closed workflow step vocabulary and definition validation
(docs/ROADMAP.md Phase 10.3).

**Closed, explicit vocabulary -- never `eval`/`exec`/dynamic imports/
arbitrary callables.** A step is a plain, validated dict with a `type`
drawn from `STEP_TYPES` (exactly four: `action`, `condition`, `delay`,
`wait_for_event` -- this phase's own required minimal vocabulary, no
more). `action` steps reuse `product.automation.actions`'s own closed,
5-member `ACTIONS` set unchanged -- this module adds no new action type
and no way to reference one that `validate_action_type()` would reject.
`condition` steps reuse `product.automation.conditions.validate_conditions()`/
`evaluate_conditions()` unchanged -- **the second-expression-language
this phase's own instructions explicitly forbid is never built here**;
a condition is exactly the same bounded `[{"field", "op", "value"}, ...]`
shape 10.2 already validates and evaluates, nothing more expressive.

**Deterministic branching, explicit destinations only.** `next_step_key`
(action/delay/wait_for_event) and `next_step_key_true`/
`next_step_key_false` (condition) name another step's own `step_key` or
are `null` (run ends after this step). There is no "goto a computed
step," no step-key expression, no indirection -- a workflow's own graph
is a fixed, fully-enumerable structure at publish time, walked the same
way on every execution and on every replay.

**No loops, by validation, not by convention** (this phase's own
explicit "if loops are not necessary for this phase, prohibit them").
`validate_workflow_definition()` builds the full directed graph implied
by every step's own destination fields and rejects it if any cycle
exists -- a published version's own step graph is always a finite DAG,
so a run is structurally guaranteed to reach a terminal step (or run out
of the bounded step-count budget below) rather than loop forever.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from product.automation.actions import validate_action_config, validate_action_type
from product.automation.conditions import validate_conditions
from product.automation.dispatcher import TRIGGER_EVENT_TYPES
from product.automation.errors import AutomationValidationError

STEP_TYPE_ACTION = "action"
STEP_TYPE_CONDITION = "condition"
STEP_TYPE_DELAY = "delay"
STEP_TYPE_WAIT_FOR_EVENT = "wait_for_event"
STEP_TYPES = frozenset(
    {STEP_TYPE_ACTION, STEP_TYPE_CONDITION, STEP_TYPE_DELAY, STEP_TYPE_WAIT_FOR_EVENT}
)

MAX_STEPS = 20
MAX_STEP_KEY_LENGTH = 64
MIN_DELAY_SECONDS = 1
MAX_DELAY_SECONDS = 30 * 24 * 3600  # 30 days -- a bounded, explicit ceiling
MIN_WAIT_TIMEOUT_SECONDS = 1
MAX_WAIT_TIMEOUT_SECONDS = 30 * 24 * 3600

# The closed set of event types a `wait_for_event` step may name -- reuses
# the identical trigger catalog product/automation/dispatcher.py already
# wires up (docs/ROADMAP.md Phase 10.2's own trigger library), never a
# separately invented event-type vocabulary. Derived from dispatcher.py's
# own tuple (not duplicated by hand) so the two stay structurally in sync.
WAITABLE_EVENT_TYPES = frozenset(TRIGGER_EVENT_TYPES)

# A step_key doubles as part of a business idempotency key
# (product/automation/durable/business_activities.py's own
# `_SAFE_KEY_PATTERN`-compatible `f"{run_id}.{step_key}"` construction) --
# restricted to the same safe character set from the start, not merely
# length-bounded, so no future caller needs to re-derive or escape it.
_STEP_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _require_step_key(value: object, *, field_name: str, allow_none: bool) -> str | None:
    if value is None:
        if allow_none:
            return None
        raise AutomationValidationError(f"{field_name} is required.")
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_STEP_KEY_LENGTH
        or not _STEP_KEY_PATTERN.match(value)
    ):
        raise AutomationValidationError(
            f"{field_name} must be a non-empty string of at most {MAX_STEP_KEY_LENGTH} "
            "characters, containing only letters, digits, '_' and '-'."
        )
    return value


def _validate_step_shape(step: Mapping[str, object], *, index: int) -> str:
    if not isinstance(step, Mapping):
        raise AutomationValidationError(f"step at index {index} must be an object.")
    step_key = _require_step_key(step.get("step_key"), field_name="step_key", allow_none=False)
    assert step_key is not None  # allow_none=False above guarantees this

    step_type = step.get("type")
    if step_type not in STEP_TYPES:
        raise AutomationValidationError(
            f"step {step_key!r}.type must be one of {sorted(STEP_TYPES)}, got {step_type!r}."
        )

    if step_type == STEP_TYPE_ACTION:
        action_type = step.get("action_type")
        if not isinstance(action_type, str):
            raise AutomationValidationError(f"step {step_key!r}.action_type is required.")
        validate_action_type(action_type)
        action_config = step.get("action_config") or {}
        if not isinstance(action_config, Mapping):
            raise AutomationValidationError(f"step {step_key!r}.action_config must be an object.")
        validate_action_config(action_type, action_config)
        _require_step_key(step.get("next_step_key"), field_name="next_step_key", allow_none=True)

    elif step_type == STEP_TYPE_CONDITION:
        conditions = step.get("conditions")
        if not isinstance(conditions, list):
            raise AutomationValidationError(f"step {step_key!r}.conditions must be a list.")
        validate_conditions(conditions)
        _require_step_key(
            step.get("next_step_key_true"), field_name="next_step_key_true", allow_none=True
        )
        _require_step_key(
            step.get("next_step_key_false"), field_name="next_step_key_false", allow_none=True
        )

    elif step_type == STEP_TYPE_DELAY:
        delay_seconds = step.get("delay_seconds")
        if (
            not isinstance(delay_seconds, int)
            or isinstance(delay_seconds, bool)
            or not (MIN_DELAY_SECONDS <= delay_seconds <= MAX_DELAY_SECONDS)
        ):
            raise AutomationValidationError(
                f"step {step_key!r}.delay_seconds must be an integer between "
                f"{MIN_DELAY_SECONDS} and {MAX_DELAY_SECONDS}."
            )
        _require_step_key(step.get("next_step_key"), field_name="next_step_key", allow_none=True)

    else:  # STEP_TYPE_WAIT_FOR_EVENT
        event_type = step.get("event_type")
        if event_type not in WAITABLE_EVENT_TYPES:
            raise AutomationValidationError(
                f"step {step_key!r}.event_type must be one of {sorted(WAITABLE_EVENT_TYPES)}, "
                f"got {event_type!r}."
            )
        timeout_seconds = step.get("timeout_seconds")
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or not (MIN_WAIT_TIMEOUT_SECONDS <= timeout_seconds <= MAX_WAIT_TIMEOUT_SECONDS)
        ):
            raise AutomationValidationError(
                f"step {step_key!r}.timeout_seconds must be an integer between "
                f"{MIN_WAIT_TIMEOUT_SECONDS} and {MAX_WAIT_TIMEOUT_SECONDS}."
            )
        _require_step_key(step.get("next_step_key"), field_name="next_step_key", allow_none=True)
        _require_step_key(
            step.get("timeout_step_key"), field_name="timeout_step_key", allow_none=True
        )

    return step_key


def _destinations(step: Mapping[str, object]) -> list[str]:
    step_type = step["type"]
    if step_type == STEP_TYPE_CONDITION:
        keys = (step.get("next_step_key_true"), step.get("next_step_key_false"))
    elif step_type == STEP_TYPE_WAIT_FOR_EVENT:
        keys = (step.get("next_step_key"), step.get("timeout_step_key"))
    else:
        keys = (step.get("next_step_key"),)
    return [str(k) for k in keys if k is not None]


def validate_workflow_definition(start_step_key: str, steps: list) -> None:
    """Validates a full step graph before it may ever be saved as a draft
    or published: referenced steps exist, no invalid/impossible
    destinations, no malformed conditions, no unsupported actions,
    bounded graph size, and -- the one this module's own docstring
    highlights -- no cycle (this phase's own "prohibit loops" decision).
    Raises `AutomationValidationError` with a specific, actionable
    message on the first problem found.
    """
    if not steps:
        raise AutomationValidationError("a workflow version must have at least one step.")
    if len(steps) > MAX_STEPS:
        raise AutomationValidationError(f"a workflow version may have at most {MAX_STEPS} steps.")

    by_key: dict[str, Mapping[str, object]] = {}
    for index, step in enumerate(steps):
        step_key = _validate_step_shape(step, index=index)
        if step_key in by_key:
            raise AutomationValidationError(f"duplicate step_key: {step_key!r}.")
        by_key[step_key] = step

    if start_step_key not in by_key:
        raise AutomationValidationError(
            f"start_step_key {start_step_key!r} does not reference an existing step."
        )

    for step_key, step in by_key.items():
        for destination in _destinations(step):
            if destination not in by_key:
                raise AutomationValidationError(
                    f"step {step_key!r} references an unknown destination step_key {destination!r}."
                )

    _reject_cycles(start_step_key, by_key)


def _reject_cycles(start_step_key: str, by_key: Mapping[str, Mapping[str, object]]) -> None:
    """DFS-based cycle detection over the destination graph -- WHITE/GRAY/
    BLACK coloring, the standard directed-cycle-detection algorithm.
    Walks every step (not just those reachable from `start_step_key`), so
    an unreachable-but-cyclic sub-graph is rejected too, not silently
    allowed because nothing starts there today."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(by_key, WHITE)

    def visit(step_key: str) -> None:
        color[step_key] = GRAY
        for destination in _destinations(by_key[step_key]):
            if color[destination] == GRAY:
                raise AutomationValidationError(
                    f"workflow definition contains a cycle involving step {destination!r} "
                    "-- loops are not supported in this phase."
                )
            if color[destination] == WHITE:
                visit(destination)
        color[step_key] = BLACK

    for step_key in by_key:
        if color[step_key] == WHITE:
            visit(step_key)


__all__ = [
    "MAX_DELAY_SECONDS",
    "MAX_STEPS",
    "MAX_WAIT_TIMEOUT_SECONDS",
    "MIN_DELAY_SECONDS",
    "MIN_WAIT_TIMEOUT_SECONDS",
    "STEP_TYPE_ACTION",
    "STEP_TYPE_CONDITION",
    "STEP_TYPE_DELAY",
    "STEP_TYPE_WAIT_FOR_EVENT",
    "STEP_TYPES",
    "WAITABLE_EVENT_TYPES",
    "validate_workflow_definition",
]
