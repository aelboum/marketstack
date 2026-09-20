# ADR-0007: Automation Execution Substrate (Phase 10.1 Spike)

Status: PROPOSED — requires your review before Phase 10.3 begins, per
`docs/ROADMAP.md` Phase 10.1's own Checkpoint ("review the engine decision
with you before committing — this is a significant new infrastructure
dependency"). This ADR is the spike's output, not yet a decision you have
signed off on.

Date: 2026-09-20

## Context

`docs/ARCHITECTURE.md` §5 flags this decision explicitly, in advance:
multi-step, stateful, or compensating workflows "must not be built on top
of the Redis-backed `infra/jobs` queue by hand-rolling state tracking...
the trigger to introduce a durable workflow engine [is] when that
capability is actually built — not before." Phase 10 is that trigger.
§5 also states: "Simple, single-step automations... run fine on
`infra.jobs` exactly as every other background job in this product does,"
while "multi-step automations with branching, delays..., or
wait-for-external-event semantics need a durable workflow engine (e.g.
Temporal)."

Phase 10.1's own Objective is to evaluate this **against the product's
actual trigger/action catalog**, informed by Phases 4-9 — not decided in
the abstract. That catalog, inspected directly rather than assumed:

- **Zero existing Product code publishes a multi-step, delayed, or
  wait-for-event workflow need.** The only real domain event published
  anywhere in this codebase before this phase is
  `crm.opportunity.stage_changed` (Phase 4.2) — a single, synchronous,
  in-process `publish()` call with zero existing subscribers.
- The two SaaS-OS capability gaps already discovered and disclosed in
  Phases 7/8 (`product/appointments/reminders.py`, `product/telephony
  /calls.py`'s own module docstrings) remain true here: `infra.jobs
  .enqueue_job()` exposes no deferred/scheduled-execution parameter
  (`_defer_until`/`_defer_by` not threaded through), and there is no
  sanctioned tenant-enumeration primitive for a cron-style sweep across
  all tenants.
- **A new, narrower gap, discovered during this phase's own spike**:
  `infra.jobs.enqueue_job()` is `async def`-only — there is no
  sanctioned synchronous entrypoint into it anywhere in `infra.jobs`.
  `product/foundation/events.py::subscribe()`'s own `EventHandler` type
  is `Callable[["Event"], None]` — synchronous-only. Every existing
  Product event publisher (`crm.opportunity.stage_changed`'s own
  `change_stage()`, and the ones this phase adds —
  `crm.contact.created`, `appointments.appointment.booked`,
  `telephony.call.completed`) is itself an ordinary, synchronous service
  function, called from both synchronous and (via FastAPI's own
  sync-route support) asynchronous callers throughout this codebase. A
  synchronous `subscribe()` handler therefore has **no sanctioned path**
  to `infra.jobs.enqueue_job()` without either (a) an unsafe
  `asyncio.run()` bridge inside a handler that might itself be invoked
  from code that is already inside an event loop, or (b) converting
  every existing, already-shipped synchronous publisher (and every one
  of *their* own callers, transitively) to `async def` — a redesign of
  unrelated, already-tested call chains this phase's own instructions
  explicitly forbid ("do not redesign unrelated event producers").

## Decision (proposed, pending your review)

**10.2 (single-step) does not need a durable engine and does not use
`infra.jobs` for execution.** It runs entirely synchronously, in-process,
inside the same `publish()` call that fires the triggering event — see
`product/automation/dispatcher.py`'s own module docstring for the full
mechanics, and the "new gap" above for why this, not
`infra.jobs`-mediated async execution, is this phase's actual choice.
This has one real, positive architectural consequence: because execution
happens at the exact instant of the trigger, there is no window between
trigger and execution in which tenant lifecycle or the configuring user's
own permissions could have changed — every authorization check
(`core.rbac.can()`, called by the underlying CRM function an action
invokes) is inherently checked at true execution time, not a stale,
earlier instant.

**10.3 (multi-step, branching, delayed, wait-for-event) is explicitly
NOT implemented in this pass.** Two independent reasons converge on the
same conclusion:

1. `docs/ARCHITECTURE.md` §5 already forbids hand-rolling this on
   `infra.jobs` — building 10.3 without a real durable engine would
   violate that standing architectural rule, not merely be second-best.
2. Adopting a real durable engine (Temporal or equivalent) is a
   significant, cost-incurring, operationally consequential
   infrastructure decision — a new external service to provision,
   operate, and hold credentials for. This is exactly the class of
   decision this session's own operating instructions require pausing
   for explicit user approval before taking action on, and it is the
   *exact* decision Phase 10.1's own roadmap text names as needing your
   review "before committing."

**Recommendation for that review, stated plainly**: given the actual
catalog above shows no existing product code with a multi-step/delayed
need yet, and given 10.2 alone covers every currently-real trigger/action
pairing, I recommend deferring the durable-engine adoption decision
itself until a concrete Phase 10.3 need is scheduled — rather than
provisioning Temporal now against a catalog that does not yet require it.
This is a recommendation for your review, not something this pass has
acted on.

## Consequences

- `product/automation/` (this phase) implements 10.2 only: single-step
  trigger → condition → action, synchronous execution, `WorkflowRun`
  table as the idempotency/audit ledger (see
  `product/automation/models.py`'s own docstring).
- 10.3 and 10.4's Accounting-dependent actions (`create invoice`,
  `record payment`) remain unimplemented — 10.4's AI-invocation action
  (`Phase 9`, already built) is the only part of 10.4 in scope here, and
  only if it fits cleanly on 10.2's own synchronous, non-`infra.jobs`
  action model without violating Phase 9's own "no autonomous agent
  runtime" boundary.
- Should a genuine Phase 10.3 need arise, this ADR's own recommendation
  (durable engine, evaluated against the *then*-current catalog) is the
  starting point for that follow-up decision — not silently superseded.

## Rejected Alternative

Hand-rolling delay/branching/wait-for-event state tracking on top of
`infra.jobs` (e.g. a workflow-run row with a `next_action_at` column,
polled by a sweep) was considered and rejected — this is precisely the
pattern `docs/ARCHITECTURE.md` §5 names and forbids by name ("never
hand-rolled as ad hoc state tracking on top of it").
