"""Permissions for the production durable-workflow domain (docs/ROADMAP.md
Phase 10.3). A separate resource from 10.2's `automation.workflow`
(`product/automation/permissions.py::WORKFLOW_RESOURCE`) -- a genuinely
different domain object (multi-step definitions/runs vs. single-step) --
but reuses the *same* `require()`/`grant_to_role()` machinery unchanged,
never a second RBAC implementation (this phase's own explicit "do not
implement a second RBAC system").

**`DURABLE_WORKFLOW_RESOURCE` gates definition CRUD and run
submission/cancellation only, never step *execution*** -- identical
discipline to `product/automation/permissions.py`'s own module docstring:
execution authorization for each step's own business action is delegated
entirely to the underlying CRM/email/webhook function the action invokes,
using the run's own `actor_user_id`, at the moment that step actually
executes -- never this resource, and never a decision cached from
submission time (`product/automation/durable/production_workflow.py`'s
own module docstring)."""

from __future__ import annotations

from product.automation.permissions import require

DURABLE_WORKFLOW_RESOURCE = "automation.durable_workflow"

__all__ = ["DURABLE_WORKFLOW_RESOURCE", "require"]
