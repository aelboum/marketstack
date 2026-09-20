"""The one trivial workflow this infrastructure spike defines (package
docstring: `product/automation/durable/__init__.py`).

**Determinism boundary, enforced here by construction, not merely by
convention.** This workflow's `run()` method contains exactly three
operations: call an activity, `await asyncio.sleep(...)` (Temporal's
Python SDK transparently replaces `asyncio.sleep` inside workflow code
with its own durable timer -- this is the one sanctioned way to "wait"
inside workflow code, never `time.sleep`), and call the activity again.
No SQL query, no network request, no filesystem operation, no random
number generation, no uncontrolled wall-clock read (`workflow.now()` is
the sanctioned, replay-safe clock accessor if one were needed -- unused
here), no `core.rbac` call, no `core.audit_log` write. Every one of those
belongs in `activities.py`, called through `workflow.execute_activity`,
never inlined here -- see `activities.py`'s own module docstring for the
one activity this phase defines, and the package docstring's own
"Determinism boundary" section for the full rule this restates.

**The sleep is test scaffolding for this spike's own restart proof, not
a product feature.** `_INTER_ACTIVITY_SLEEP_SECONDS` exists to create a
real, observable window in which a worker process can be stopped and a
new one started while this workflow is suspended between its two
activities -- proving the durable timer (and the workflow's own
in-flight state generally) survives a worker restart. This is
infrastructure validation, not "wait 3 days" business functionality
(explicitly out of scope for this phase, per docs/ROADMAP.md 10.3's own
still-deferred Objective) -- no roadmap trigger/action, no
`product.automation` domain object, ever constructs or schedules this
workflow for a business purpose.

**Bounded, deterministic result** -- `ProbeWorkflowResult` carries only
the two activities' own bounded `ProbeActivityOutput` values, nothing
unbounded, nothing sourced from outside this workflow's own explicit
input.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    # Importing this pure-dataclass/activity module from inside the
    # sandboxed workflow environment is safe (it performs no I/O and
    # defines no unsandboxed global state) -- see `activities.py`'s own
    # module docstring. `imports_passed_through()` tells the SDK's
    # sandbox not to re-execute this import under sandbox restrictions a
    # second time, matching the SDK's own documented pattern for a
    # workflow file that needs a plain, deterministic sibling module.
    from product.automation.durable.activities import (
        ProbeActivityInput,
        ProbeActivityOutput,
        probe_activity,
    )

_ACTIVITY_TIMEOUT = timedelta(seconds=10)
_INTER_ACTIVITY_SLEEP_SECONDS = 8


@dataclass(frozen=True, slots=True)
class ProbeWorkflowInput:
    tenant_id: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class ProbeWorkflowResult:
    first: ProbeActivityOutput
    second: ProbeActivityOutput


@workflow.defn
class ProbeWorkflow:
    """Infrastructure-validation-only. Accepts a `tenant_id` and a
    `resource_id`, invokes `probe_activity` twice (with a durable sleep
    in between, for this spike's own restart proof -- module docstring),
    and returns a bounded, deterministic result. Never sends email, never
    sends a webhook, never mutates CRM, never creates an appointment,
    never touches telephony, never invokes AI, never accesses an
    arbitrary URL or database, never executes arbitrary code, never
    accepts an arbitrary Python callable."""

    @workflow.run
    async def run(self, input: ProbeWorkflowInput) -> ProbeWorkflowResult:
        first = await workflow.execute_activity(
            probe_activity,
            ProbeActivityInput(tenant_id=input.tenant_id, resource_id=input.resource_id),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
        )
        await asyncio.sleep(_INTER_ACTIVITY_SLEEP_SECONDS)
        second = await workflow.execute_activity(
            probe_activity,
            ProbeActivityInput(tenant_id=input.tenant_id, resource_id=input.resource_id),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
        )
        return ProbeWorkflowResult(first=first, second=second)
