"""The composition root that connects Automation's neutral action
registry (`product.foundation.workflow_actions`,
`product.automation.actions.get_action_registry()`) to every
domain-specific production action adapter that exists today
(docs/ROADMAP.md Phase 10.4A).

**Why this lives here, outside both `product.automation` and
`product.ai`.** The import-linter contracts forbid
`product.automation -> product.ai` *and* `product.ai -> product.automation`
in both directions (`product/foundation/workflow_actions.py`'s own module
docstring). Neither package can therefore perform this wiring itself --
it needs a third module, allowed to import both, whose only job is this
one explicit call. `product/api/main.py` already plays exactly this role
for every other module's event-handler/purge-participant registration;
this module is the same kind of composition root, factored out on its
own because it is *also* needed by the separate Temporal worker process
(`product/production_worker_entrypoint.py`) --
`product/automation/durable/production_worker.py` itself cannot import
`product.ai` either, being part of `product.automation`.

**Explicit, not an import side effect.** Importing this module registers
nothing -- only calling `wire_production_automation_actions()` does.
Every process that needs a complete production action vocabulary calls it
once during its own startup, the same "explicit composition root, no
import-order dependence" discipline
`product/automation/actions.py::get_action_registry()`'s own docstring
already establishes.

**Idempotent.** Safe to call more than once in the same process (e.g. a
test that constructs the FastAPI app repeatedly, or a caller unsure
whether an earlier code path already composed the registry) -- mirrors
`product/ai/purge.py::register()`'s/`product/telephony/purge.py
::register()`'s own established idempotent-registration convention.
"""

from __future__ import annotations

from product.ai.automation_action import build_qualify_lead_workflow_action
from product.automation.actions import ACTION_AI_QUALIFY_LEAD, get_action_registry


def wire_production_automation_actions() -> None:
    """Register every domain-specific production action adapter into
    Automation's neutral registry, then assert the registry is complete
    (`WorkflowActionRegistry.require_complete()`) -- the one point where a
    declared-but-unwired action fails loudly, at startup, rather than at
    the first workflow run that reaches it. Pure in-memory: no database,
    no network, safe to call from a process with no `DATABASE_URL`
    configured (matches `product/api/main.py::create_app()`'s own
    existing "must stay callable with no database configured"
    constraint)."""
    registry = get_action_registry()
    if not registry.is_registered(ACTION_AI_QUALIFY_LEAD):
        registry.register(build_qualify_lead_workflow_action())
    registry.require_complete()


__all__ = ["wire_production_automation_actions"]
