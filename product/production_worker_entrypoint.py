"""Production Temporal worker process entrypoint, composed
(docs/ROADMAP.md Phase 10.4A). Run via
`python -m product.production_worker_entrypoint` instead of
`python -m product.automation.durable.production_worker` directly -- same
worker, same task queue
(`product/automation/durable/production_workflow.py::PRODUCTION_TASK_QUEUE`),
same activities
(`product/automation/durable/business_activities.py::ACTIVITIES`),
unchanged -- with the one composition step
(`product/action_registry_composition.py::wire_production_automation_actions()`)
applied first, so a durable run reaching an `ai.crm.qualify_lead` step in
*this* worker process resolves it exactly as the API process's own 10.2
synchronous path does.

**Why not inside `product/automation/durable/production_worker.py`
itself.** That module is part of `product.automation`, which the
import-linter contracts forbid from importing `product.ai`
(`product/action_registry_composition.py`'s own module docstring).
`production_worker.py` itself is untouched by this phase -- its own
`main()`/`run_worker()` functions, activities, and task queue are exactly
what Phase 10.3 built; this wrapper only changes *what runs before* it
starts polling.

Not yet wired into `docker-compose.yml` -- `production_worker.py` itself
was not either (only the Phase 10.3 infrastructure spike's own
`worker.py`, serving `ProbeWorkflow` on a different task queue, has a
compose service today). Deploying this wrapper as the production worker's
own compose command/entrypoint is an operational follow-up, not part of
this phase's own scope.
"""

from __future__ import annotations

from product.action_registry_composition import wire_production_automation_actions
from product.automation.durable.production_worker import main as _run_production_worker


def main() -> None:
    wire_production_automation_actions()
    _run_production_worker()


if __name__ == "__main__":
    main()


__all__ = ["main"]
