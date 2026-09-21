# ADR-0007: Automation Execution Substrate (Phase 10.1 Spike + Phase 10.3 Infrastructure Spike)

Status: **ACCEPTED** — finalized 2026-09-20 by the Phase 10.3
infrastructure spike below, which built and ran a real, minimal
integration proving this ADR's own 10.1 conclusions (Context/Decision/
Consequences below, unedited) and its 10.3 recommendation (a dedicated
durable engine, adopted only once a concrete need was scheduled) both
hold. The architecture-review pass that preceded this spike (a separate,
read-only pass; its own full report is not reproduced here) approved:
Temporal (or equivalent), external to SaaS-OS, Product-owned. This spike
made the concrete selection (Temporal) and validated it empirically --
"Phase 10.3 Infrastructure Spike" section below.

Date: 2026-09-20 (10.1 spike); 2026-09-20 (10.3 infrastructure spike)

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

---

## Phase 10.3 Infrastructure Spike (2026-09-20)

**Scope discipline, stated up front**: this spike proves infrastructure
viability only. It does NOT implement the production multi-step Workflow
Builder, branching workflow graphs, delayed business workflows,
wait-for-event business workflows, workflow-versioning UI, the 10.3
workflow domain, or 10.4. `product/automation/durable/` is 6 small files
(~450 lines total); the existing 10.2 engine
(`product/automation/{dispatcher,actions,workflows,scheduled,models,...}.py`)
is unmodified in behavior — verified both by test
(`tests/automation/durable/test_disabled_and_failure_unit.py
::test_existing_phase_10_2_automation_package_does_not_import_durable`)
and by the full existing `tests/automation/` suite passing unchanged.

### Engine selected: Temporal

Concrete selection, not left at "Temporal or equivalent." SDK
compatibility verified directly against PyPI before adding the
dependency: `temporalio` 1.33.0 declares `requires_python >= 3.10` and
lists Python 3.13 in its own classifiers (matching this repository's
`requires-python = ">=3.13"` exactly), and ships a prebuilt
`cp310-abi3` wheel for win_amd64/linux/macos — no C toolchain needed on
either this Windows dev machine or the `python:3.13-slim` Docker image.
No blocking compatibility issue found. Pinned as an exact version in
`pyproject.toml` (`temporalio==1.33.0`), mirroring `detect-secrets`'s own
exact-pin discipline in the same file, for the same determinism reason.

### Dependency boundary

```
product.automation (domain: Workflow, WorkflowRun, actions, conditions)
    |
    v
product.automation.durable   (new adapter -- client.py, worker.py,
    |                          workflows.py, activities.py, config.py)
    v
temporalio SDK                 (external, Product-owned dependency)
    |
    v
Temporal server / persistence  (external infrastructure; docker-compose.yml)
```

`temporalio` is imported only from inside `product/automation/durable/`.
Nothing under SaaS-OS (`core`/`infra`/`api`/`control_plane`) imports this
package or `temporalio` — structurally impossible, not merely
undesired: SaaS-OS is a pinned upstream dependency of this product, never
the reverse, so no SaaS-OS code path can import a Product-side package at
all. This repository's own `[tool.importlinter] root_packages =
["product"]` cannot express a "core does not import product" contract
(SaaS-OS's source is outside that root) — the boundary is enforced by the
one-way dependency pin itself. Verified empirically for this spike: no
`import product` exists anywhere in the installed `saas-os` source at the
pinned commit.

The existing `[[tool.importlinter.contracts]] name = "Automation does not
depend on any product module except CRM"` (`source_modules =
["product.automation"]`) already covers `product.automation.durable` as
a subpackage — re-ran `lint-imports` after adding the new package (172
files analyzed, up from 163) and all 11 contracts remain KEPT, with no
new contract added: three of this spike's four requested boundaries
("automation may depend on the durable adapter," "durable adapter may
depend on the external SDK," "no reverse dependency from durable
infrastructure into Product") were already true/enforced with zero new
lines, and the fourth ("SaaS Core remains unaware of Temporal") cannot be
expressed by this repository's own import-linter config at all (previous
paragraph) — adding a contract that cannot fire would be dead
configuration, not enforcement.

`product/api/main.py` deliberately never imports
`product.automation.durable` — verified both by a dedicated test
(`test_product_api_main_never_imports_the_durable_adapter`) and by
direct inspection. This is what makes "Product remains usable if
Temporal is not configured/started" and "the engine can be disabled
without affecting existing 10.2 single-step automation" true by
construction, not by discipline alone.

### Worker architecture

A dedicated entrypoint, `product/automation/durable/worker.py`
(`python -m product.automation.durable.worker`), run as its own Docker
Compose service (`temporal-worker`) — never merged into FastAPI startup,
never merged into a (nonexistent, confirmed by inspection) ARQ worker,
never merged into the API process. `Client.connect()` is allowed to raise
on an unreachable endpoint rather than being wrapped in a bespoke retry
loop — Temporal's own client/worker handles ordinary reconnection once
started; a container orchestrator's restart policy
(`docker-compose.yml`'s `temporal-worker: restart: on-failure`) is the
intended layer for "the process exited, start it again."

### Persistence architecture

Temporal server, backed by PostgreSQL. `docker-compose.yml`'s `temporal`
service reuses the existing `db` Postgres server
(`temporalio/auto-setup:1.29.7`, `POSTGRES_SEEDS: db`) rather than
introducing a second database engine — its own bootstrap creates
`temporal`/`temporal_visibility` databases inside that same server,
structurally separate from this product's own `POSTGRES_DB` database and
never touched by `scripts/bootstrap-db.py` or this product's own Alembic
migration history. This product's Alembic migration system does not, and
must not, manage Temporal's internal schema.

### Determinism boundary

Enforced by construction in `product/automation/durable/workflows.py`:
`ProbeWorkflow.run()` contains exactly an activity call, a durable
`asyncio.sleep()` (the SDK's own sanctioned durable timer), and a second
activity call — no SQL, no network call, no filesystem access, no random
number generation, no uncontrolled wall-clock read, no `core.rbac` call,
no `core.audit_log` write. The Python SDK's own sandboxed workflow
execution environment enforces part of this automatically (restricted
imports, no thread/process spawning); this codebase does not rely on the
sandbox alone. **Rule for every future production activity**: it must
re-enter the existing Product action/RBAC boundary — call
`product.automation.actions.execute_action()` (or an equivalent
already-RBAC-gated Product function) — at the exact moment it executes,
never caching a permission decision from workflow-submission time. This
holds because `core.rbac.can()` (`core/rbac/authorization.py`) is
evaluated live, under a tenant-lifecycle row lock, on every call — never
cached — so "re-check at every step" is a real, load-bearing guarantee,
not a hope, confirmed by reading `can()`'s own implementation directly.

### Privacy / history findings

Determined by reading the SDK's actual behavior, not assumed: Temporal's
server persists a workflow's complete event history — the workflow's own
start input, every activity's own scheduled input and completed result —
as the literal mechanism it uses to replay and recover execution (the
property this whole spike exists to validate). Concretely, for this
spike's own `ProbeWorkflow`/`probe_activity`: `tenant_id` and
`resource_id` (echoed back unchanged) are written into Temporal's history
by the default, unencrypted `DataConverter`. **Every test and every
manual run in this spike used synthetic identifiers only** (e.g.
`"spike-tenant-1"`, `"restart-proof-tenant"` — never a real
`core.tenants` row) — no real customer data was put into Temporal history
by this spike, anywhere. A future production integration that passes
real ids as workflow/activity input (ids only, never full row content —
mirroring `product/automation/dispatcher.py`'s own "tenant identity is
never trusted from event payloads, the dedup key carries only ids"
discipline) must either accept that those ids land in Temporal's history,
or configure the SDK's own `DataConverter` with a `PayloadCodec`
(Temporal's documented encryption-at-rest hook) — **not implemented or
guaranteed by this spike**; no encryption guarantee is invented here that
was not actually built.

### Tenant/security boundary

`tenant_id` is explicit, plain workflow/activity input in this spike —
never resolved from arbitrary payload content. No authorization decision
is delegated to Temporal, and no second RBAC implementation is
introduced anywhere in `product/automation/durable/`. The tenant-lifecycle
purge interface this spike proves out (not a full purge-participant
integration — explicitly out of scope): `product/automation/durable/
client.py::list_workflows_for_tenant()`/`terminate_workflows_for_tenant()`
implement and test the workflow-ID-prefix strategy (every workflow id
this module starts is prefixed `automation-durable-probe:<tenant_id>:`;
listing/terminating filters client-side on that prefix) — works on any
Temporal deployment with zero server-side setup, at the cost of listing
every execution in the namespace to find one tenant's own. A production
implementation should instead register a custom Keyword search attribute
(`temporal operator search-attribute create --name TenantId --type
Keyword`, once per namespace) for server-side query filtering — not
implemented here (would be speculative production purge code, out of
this spike's own scope). Defense in depth already exists regardless: a
stray, un-terminated Temporal execution can never by itself re-authorize
anything for a closed tenant, since `core.rbac.can()` already fails for
`SUSPENDED`/`DELETED`/`PURGING`/`PURGED` tenants
(`core/tenancy/lifecycle.py::PRINCIPAL_INACCESSIBLE_STATUSES`) regardless
of what a future real activity's own RBAC re-check would find.

### Restart/recovery test — procedure and actual result

**Not mocked. A genuine, separate-OS-process restart, executed and
observed directly**, not a unit test with a mocked restart:

1. Started a real Temporal dev server (`temporal` CLI 1.9.1, Server
   1.32.0, via `temporalio.testing.WorkflowEnvironment.start_local()`,
   which manages the actual upstream dev-server binary) bound to
   `127.0.0.1:17233`, with a real on-disk SQLite persistence file — its
   own separate OS process (confirmed via `Get-CimInstance
   Win32_Process`, PID recorded, distinct from every other process).
2. Started worker process #1 (`python -m
   product.automation.durable.worker`) as its own, separate OS process,
   confirmed connected.
3. Submitted one `ProbeWorkflow` execution (synthetic tenant id
   `restart-proof-tenant`).
4. **Force-killed the entire worker process tree** (`taskkill /T /F`,
   confirmed by process list showing zero durable-worker processes
   remaining) within roughly 1-2 seconds of submission — well inside the
   workflow's own 8-second inter-activity durable sleep, i.e. genuinely
   mid-execution, not after completion.
5. Queried the still-running server directly (a separate client script,
   not the dead worker): workflow status was **RUNNING**, with
   confirmed zero worker processes alive anywhere on the machine at that
   moment — the execution existed only in the server's own persisted
   state, held by no worker.
6. Started worker process #3 — a brand-new, independently-launched OS
   process, sharing no state with worker #1 beyond the same task queue
   name and the same server.
7. Within ~3 real seconds, the workflow reached status **COMPLETED**.
   Fetched the final result directly: both activities had executed
   correctly, each echoing back the correct synthetic `tenant_id`/
   `resource_id` — the execution resumed exactly where it had been left
   and finished correctly, having survived a real worker-process death
   with zero worker present for a real, confirmed gap of time.
8. Cleaned up: terminated the dev server and worker process trees,
   removed the scratch SQLite file. Confirmed via process listing that
   zero Temporal-related processes remained, and via `docker ps` that
   the user's own persistent `marketstack-db-1`/`marketstack-redis-1`/
   other containers were completely unaffected throughout.

**What this validates**: server-side persistence of in-flight workflow
state is independent of any single worker process, and a brand-new
worker process can resume and correctly complete an interrupted
execution with no data loss and no silent disappearance — the entire
premise this ADR's Phase 10.1 section named as the reason a durable
engine would eventually be needed.

**What this does not validate**: the actual `docker-compose.yml`
`temporal`/`temporal-worker` service definitions were not live-started
end-to-end as part of this spike (deliberately, to avoid interacting
with the developer's own persistent `db`/`redis` containers and the
separately-owned, untouched `docker-compose.override.yml` sharing this
same Compose project). `docker compose config` was used instead — a
safe, read-only validation confirming the merged configuration parses
correctly and both new services resolve with no schema error, alongside
every existing service unaffected. The restart proof above exercises the
identical underlying mechanism (a real Temporal server process plus
separate, real worker OS processes, both reachable exactly the way the
Compose services would be) — the Compose topology itself should be
validated live in a disposable environment before this is relied on in
CI, as a follow-up, not claimed equivalent here.

### Known limitations

- The full Docker Compose `temporal`/`temporal-worker` topology was
  validated for config correctness only, not live-started (previous
  section).
- The tenant-scoped list/terminate interface uses client-side listing
  (workflow-ID-prefix), not a server-side search attribute — documented
  as a production follow-up, not built here.
- No `PayloadCodec`/history encryption is configured or guaranteed —
  privacy findings section above.
- No cron-quality scheduler exists for a future "sweep all tenants"
  need — the pre-existing, separately-disclosed gap
  (`core.tenancy.service` has no tenant-enumeration primitive) is
  unchanged by this spike.
- This spike's own inter-activity sleep (`_INTER_ACTIVITY_SLEEP_SECONDS`
  in `workflows.py`) exists purely as restart-proof test scaffolding —
  it is not a delayed-business-workflow feature and must not be mistaken
  for 10.3 production scope.

### Explicit statement

**Production Phase 10.3 workflow functionality (multi-step business
workflow definitions, branching graphs, delayed business workflows,
wait-for-event business workflows, workflow-versioning UI) is NOT
implemented by this spike.** This ADR's own Decision section above,
extended by this spike, establishes only that the chosen durable engine
(Temporal) integrates safely with this product's deployment and security
model — a precondition for that future work, not that work itself.

---

## Phase 10.3 Production Implementation (2026-09-20)

Built on the infrastructure spike above, once reviewed and approved.
**Implements the narrow production multi-step workflow engine only** --
no visual builder, no frontend, no AI/accounting actions, no arbitrary
code execution, no new scheduler. `product/automation/durable/` gained
seven new modules (`models`, `dsl`, `permissions`, `definitions`,
`business_activities`, `production_workflow`, `runs`, `triggers`,
`routes`, `production_worker`) alongside the spike's own unmodified
`config`/`client`/`worker`/`activities`/`workflows` (the probe workflow
remains, unused by production code, a standing infra smoke-test).

**Domain model**: `Workflow` (stable identity) -> `WorkflowVersion`
(`draft`/`published`, immutable once published, steps as bounded JSON,
never a separate steps table) -> `Run` (business execution state,
pins the exact `workflow_version_id` it executes, forever) -> `RunStep`
(per-step business outcome ledger). Four new tables
(`automation.durable_workflows`/`durable_workflow_versions`/
`durable_runs`/`durable_run_steps`), hand-written migrations 0037-0040
(revision ids shortened to fit Alembic's own 32-character `version_num`
column -- a real bug this implementation found and fixed, not a stylistic
choice). Temporal's own execution history is never duplicated into these
tables -- no retry-attempt counts, no serialized activity payloads, no
timer state.

**Step vocabulary**: exactly four types (`action`, `condition`, `delay`,
`wait_for_event`) -- `action` reuses `product.automation.actions`'s
closed 5-member set unchanged; `condition` reuses `product.automation
.conditions.validate_conditions()`/`evaluate_conditions()` unchanged,
never a second expression language. Branching is explicit-destination
only; loops are rejected by a directed-cycle check at publish time
(`dsl.py::_reject_cycles()`) -- every published graph is a finite DAG.

**Determinism boundary**: `production_workflow.py::DurableWorkflow.run()`
contains only `workflow.execute_activity(...)`, `asyncio.sleep(...)`
(the durable timer), and a pure, in-memory `evaluate_conditions()` call
-- every business action, every Postgres write, every `core.rbac`/
`core.audit_log` call lives one layer down, in
`business_activities.py`'s five plain, synchronous activities, dispatched
through a `ThreadPoolExecutor` (`production_worker.py`) the same way the
infrastructure spike's own `worker.py` never needed to (the spike's
`probe_activity` was `async def` and did no I/O; every production
activity does real, blocking Postgres I/O).

**Authorization**: unchanged from 10.2's own load-bearing discipline,
extended to multi-step -- `execute_step_action_activity()` calls straight
into `product.automation.actions.execute_action()` using `Run
.actor_user_id`, re-evaluated fresh by the underlying CRM/email/webhook
function's own `core.rbac.can()` call at the instant each step actually
executes. Proven, not merely asserted: `test_permission_revoked_before_
later_step_denies_only_that_step` revokes the creator's own permission
while a run is genuinely paused (`wait_for_event`) and confirms the
already-executed step stays `succeeded` while the later one is denied at
execution time -- the identical adversarial shape 10.2's own checkpoint
required, now proven across a real pause with a real worker.

**Retry classification -- a real bug this phase's own adversarial test
found.** Temporal retries an activity until its `RetryPolicy` is
exhausted, so a *permanent* failure must be raised as
`ApplicationError(non_retryable=True)` or it is retried pointlessly.
`execute_action()` deliberately does not normalize the underlying
domain call's own exceptions (only `send_email`/`send_webhook`, which
have a provider boundary, are wrapped), so a CRM action's
`CrmAccessDeniedError` reaches the activity *raw*. The first
implementation classified only the `Automation*` error families, which
left exactly the most safety-critical permanent failure -- an
execution-time authorization denial -- falling through to the generic
retryable branch: retried five times, and never audited as
`automation.durable_run.authorization_denied`. Caught by
`test_permanent_authorization_denial_terminates_run_correctly`, and
fixed by classifying the domain-layer error types explicitly
(`business_activities.py::_PERMANENT_DENIAL_ERRORS`/
`_NON_RETRYABLE_ACTION_ERRORS`). Both lists are closed and enumerated,
matching this phase's own closed action vocabulary.

**Idempotency**: `execute_step_action_activity()` wraps `execute_action()`
in `core.idempotency.begin_idempotent_operation()`/
`finalize_idempotent_operation()`, keyed by `f"{run_id}.{step_key}"` --
reused, not reinvented; proven by calling the real activity function
directly, twice, with the identical key, and confirming exactly one
real CRM task was created.

**Wait-for-event / signals**: `DurableWorkflow.submit_event()` only
accepts a signal matching the step currently in flight
(`_expected_event_type`); `runs.py::signal_run()` independently checks
`Run.status == waiting` and `Run.waiting_for_event_type == event_type`
in Postgres *before* ever contacting Temporal -- two independent checks,
not one. Tenant isolation for signaling is structural, not a permission
check alone: the only way to obtain a `WorkflowHandle` at all is through
`runs.py`, which resolves `run_id` through a tenant-scoped Postgres
lookup first.

**Cancellation**: `runs.py::cancel_run()` calls `WorkflowHandle.cancel()`
and sets `Run.status = cancelled` in Postgres directly, from the calling
request -- never from inside workflow code, which lets Temporal's own
unhandled-cancellation propagation do the "no new activity starts" work
structurally (`production_workflow.py`'s own module docstring). No
compensation/saga behavior, as scoped.

**Tenant purge**: `product/automation/purge.py`'s existing
`AutomationDataPurgeParticipant` was extended in place (not replaced) --
before deleting the four new tables' rows, it queries this tenant's own
non-terminal `Run.temporal_workflow_id` values directly from Postgres
(the authoritative index of which Temporal executions belong to this
tenant -- **better than the infrastructure spike's own client-side
list-and-filter strategy**, which this production purge path does not
use at all) and terminates exactly those executions.  Fails closed: a
Temporal connection failure here propagates, and `core.tenancy
.purge_tenant()` will not mark the tenant `PURGED`. Proven against a
real waiting run: terminated on the Temporal side, deleted on the
Postgres side, and unreachable on any later `get_run()`/`signal_run()`
-- in practice denied at `require()` before the lookup even runs, since
purging also removes this tenant's own RBAC rows (the stronger of the
two rejections; `AutomationReferenceNotFoundError` is the fallback if a
grant ever survived).

**Trigger integration -- the disclosed sync/async gap is unchanged, not
solved by Temporal.** `triggers.py`'s own event-triggered adapter
subscribes synchronously (`product.foundation.events.subscribe()`,
identical to 10.2's own dispatcher) and performs only a bounded, sync,
Postgres-only reservation (`Run` row in `queued` status) -- it never
calls Temporal directly, because doing so would require exactly the
`asyncio.run()` bridge inside an already-risky sync call chain this
ADR's own Phase 10.1 section identified and rejected. Actually starting
a `queued` run on Temporal requires an explicit call to
`submit_queued_durable_runs()` -- the same disclosed, bounded scheduling
gap `product/automation/scheduled.py` already has for 10.2's own
`scheduled` trigger type (`core.tenancy` has no tenant-enumeration
primitive for a real cron sweep), **not a new gap, and not something
adopting Temporal resolves** -- Temporal solves durable *execution*, not
the sync-publisher/async-client boundary. 10.2's own triggers and
`dispatcher.py` are completely unmodified and untouched by this work.

**Privacy / history**: only bounded identifiers and scalars ever enter a
workflow's arguments -- a step's business data is fetched from Product
state *inside* the activity, after authorizing, never serialized into
the workflow input. `test_workflow_history_contains_only_bounded_
synthetic_context` proves this against a *real* CRM contact carrying
real PII: it creates a contact with a unique email, phone, and surname,
runs a workflow over that contact's id, fetches the completed run's own
Temporal history, and asserts the id and the step title appear while
none of the three PII values does. No `PayloadCodec`/encryption is
configured here either -- the spike's own disclosed limitation stands
unchanged, and nothing in this phase claims history is encrypted.

**What the tests themselves had to get right.** Two test-harness
defects in this phase's own execution suite produced failures that
looked like engine bugs and were not: (1) polling Postgres with a
blocking `time.sleep()` loop from *inside* a coroutine starves the
`temporalio.worker.Worker` sharing that event loop -- the workflow
cannot progress while the test blocks it, so runs sat in `queued` and
the poll "timed out" on a workflow the test itself was stalling
(`workflow_task_duration=20222` ms in the worker log, exactly the poll
timeout). The in-coroutine poll is now `await`-based
(`_await_run_status()`). (2) Temporal's automatic time skipping is
attached only to the handle object `Client.start_workflow()` itself
returns; a handle rebuilt from a workflow id via `get_workflow_handle()`
-- the only kind these tests can hold, since `runs.start_run()` owns the
`start_workflow()` call -- waits in *real* time, so the durable-delay
test now advances the server clock explicitly with `env.sleep()`.
Both are documented at their call sites so neither is reintroduced.

**Known limitations, explicit**:
- No cron/scheduling subsystem -- `submit_queued_durable_runs()` must be
  invoked explicitly (API route or external scheduler), identical
  standing gap to 10.2's own `scheduled` trigger type.
- `WorkflowVersion.steps` bounded JSON is validated at save/publish time
  but not further sandboxed at execution time beyond the closed
  `action_type`/`event_type` vocabularies already enforced.
- No workflow-history encryption (`PayloadCodec`) configured.
- The production `Worker`'s `ThreadPoolExecutor` is sized (20 workers)
  but not load-tested; this is a narrow engine proof, not a capacity-
  planned deployment.
- A version currently being drafted is fully mutable up to the moment of
  `publish_version()` -- no draft-level optimistic-locking/conflict
  detection exists for concurrent editors (out of this phase's own
  scope).

## Phase 10.4 Split: AI vs. Accounting Automation (2026-09-21)

Documentation correction only -- no code, no substrate change. The
"Consequences" section above was written in the 10.2 era, when neither
10.4 half was actionable and both were correctly described together as
unimplemented. That is no longer an accurate framing of the *current*
state, because the two halves' dependencies diverged:

- **10.4A (AI automation) is now unblocked.** *(SUPERSEDED -- this
  specific claim was disproved the next day; see "Phase 10.4A
  Prerequisites Discovered" below. The rest of this bullet's
  authorization-boundary requirement still stands.)* Phase 9 is built
  (`product/ai/` registers real tools behind
  `invoke_product_ai_tool()`) and Phase 10.3's durable engine is
  complete, so the AI-invocation action can be implemented on the
  existing action vocabulary -- on 10.2's synchronous path and 10.3's
  durable path alike, with no second executor. The 10.2-era caveat above
  ("only if it fits cleanly on 10.2's own synchronous... action model")
  is superseded by 10.3 existing: the durable path is now a supported
  destination for that action, not a hypothetical one. The binding
  constraint is unchanged and restated: Automation must not become a
  second AI authorization system -- tool authorization, Data
  Authorization, provider/model policy, and autonomy tier remain owned by
  the AI Control Plane and `product/ai/`, and this action passes the
  run's own execution identity through those existing gates rather than
  re-deciding anything itself.
- **10.4B (accounting automation) remains blocked on Phase 15.** Phase 15
  has not started; `product/accounting/` is a placeholder with no schema,
  models, services, or migrations, so there is no accounting domain
  contract for Automation to consume and no posting/immutability logic to
  reuse. Automation consumes accounting contracts, it never defines
  accounting semantics -- so no accounting model, migration, API, action,
  trigger, or placeholder contract belongs in Automation before Phase 15
  establishes them (`docs/ACCOUNTING-SCOPE.md`, `docs/ROADMAP.md` 10.4B).

Temporal remains the durable execution substrate for both halves; this
split introduces no new execution architecture and changes nothing about
the engine decided and implemented above.

## Phase 10.4A Prerequisites Discovered (2026-09-21)

Documentation correction only -- no code. The 10.4A implementation
attempt produced **no source changes**: an audit of the real seam,
performed before writing anything, disproved the bullet above. **"10.4A
(AI automation) is now unblocked" was wrong**, for two independent
reasons neither the 10.2-era section nor the split section knew about.
Both are now sequenced as explicit roadmap prerequisites rather than
absorbed into 10.4A:

- **The import boundary forbids the edge outright.** `pyproject.toml`'s
  import-linter contract "Automation does not depend on any product
  module except CRM" lists `product.ai` in `forbidden_modules`, so
  `product.automation` cannot import `invoke_product_ai_tool()` at all.
  Adding one narrow `automation -> ai` layers edge does not resolve it
  either: `product.ai` itself imports `product.conversations` and
  `product.telephony`, both also forbidden to Automation, so the edge
  creates forbidden *indirect* chains (this repository sets no
  `allow_indirect_imports` anywhere, by design). The resolution is
  dependency inversion -- a generic Automation-owned action
  protocol/registry a domain capability registers against -- scoped as
  `docs/ROADMAP.md` **10.3A**, with its own ADR to be written when that
  subphase is scheduled. **That registry does not exist today**, and
  nothing in this ADR should be read as describing a shipped mechanism.
- **Phase 9 is not production-executable, deliberately.** No product tool
  is registered in `control_plane.orchestration.default_registry()`
  (`product/ai/__init__.py` states the reason: a Fake-backed handler must
  never return synthetic output to a real tenant), and
  `product.ai.policy.resolve_tenant_ai_policy()` returns `None` for every
  tenant, so Data Authorization default-denies. Every 9.1-9.3 test that
  exercises an allow path necessarily supplies *both* its own
  `ToolRegistry` and its own permissive `TenantAIDataPolicy`. So the
  earlier bullet's "`product/ai/` registers real tools behind
  `invoke_product_ai_tool()`" overstated it: the tool *definitions* are
  real and complete, their production *registration* is not, and that
  deferral is documented and intentional. Closing that gap is
  `docs/ROADMAP.md` **9.4**, a follow-on production-readiness subphase --
  9.1-9.3 remain valid and complete for their own stated scope.

A deny-only AI workflow action -- correctly wired but guaranteed to fail
for every real tenant until 9.4 lands -- is explicitly not an acceptable
way to close 10.4A. Temporal remains the durable execution substrate, and
neither prerequisite changes the engine decided and implemented above:
10.3A changes how an action implementation *reaches* the closed
vocabulary, never the vocabulary's closed nature, the publish-time
validation's determinism, or either execution path.

## Phase 10.3A Implemented: Action Registry / Dependency Inversion (2026-09-21)

The prerequisite above is now built. **No AI action exists** -- this
phase delivers the boundary only, and `ACTIONS` still names exactly
Phase 10.2's own five actions.

**Why a direct `product.automation -> product.ai` import is not
available.** The import-linter contracts forbid it in *both* directions:
`product.ai` is listed in Automation's own `forbidden_modules`, and
`product.automation` in AI's. A "narrow exception" edge is not available
either -- `product.ai` itself imports `product.conversations` and
`product.telephony`, both also forbidden to Automation, so a direct edge
would create forbidden *indirect* chains (no `allow_indirect_imports` is
set anywhere in this repository, by design). Since neither package may
import the other, the only correct resolution is a dependency inversion
onto a contract neither owns.

**Where the contract lives.** `product/foundation/workflow_actions.py`
-- the placement `docs/ARCHITECTURE.md` section 2.2 already prescribes
("the capability is generic enough to belong in `product/foundation`...
promote it, don't duplicate it"). `product/foundation/` is the one
always-allowed dependency *target* and itself imports no product module,
so the contract is domain-neutral by construction: every value crossing
it is a primitive, a `uuid.UUID`, or a plain mapping.

    product.automation  ---->  product.foundation.workflow_actions
                                          ^
                                          |
    product.<domain> adapter  ------------+

**The contract.** A `@runtime_checkable Protocol` (`WorkflowAction`:
`name`, `validate_config`, `execute`), a frozen-dataclass convenience
implementation (`WorkflowActionSpec`), three neutral error types
(`WorkflowActionConfigError`, `WorkflowActionDeniedError`,
`WorkflowActionExecutionError`), and `WorkflowActionRegistry`. The
neutral errors exist because a foreign adapter cannot import
`product.automation.errors`; `business_activities.py` classifies them
identically to their Automation/CRM counterparts, so a foreign action
gets exactly the same permanent-vs-retryable treatment as a built-in
one. Protocol parameters are position-only, which is what lets the
existing `_validate_*`/`_execute_*` functions satisfy the contract with
no rewrite.

**Why registration is deterministic, and why that mattered.** The
registry is constructed with an explicit, finite `allowed_names` set and
refuses anything outside it; a duplicate registration raises rather than
silently overwriting (last-one-wins is precisely how import order leaks
into behaviour); and the *publishable* vocabulary is a static constant
(`ACTIONS`) that `validate_action_type()` consults directly -- never the
registry's current contents. So importing an unrelated module can never
change which workflow definitions validate. `require_complete()` closes
the other half at bootstrap: a declared name with no implementation is a
loud startup failure, not a surprise at the first run that reaches it.
Automation's own five actions are registered unconditionally inside the
module that defines them, so that import is self-contained and
order-independent; a *foreign* domain's adapter is instead registered by
an explicit composition-root call through `get_action_registry()`, never
by an import side effect of the domain package.

**Compatibility.** `ACTIONS`, `validate_action_type()`,
`validate_action_config()`, and `execute_action()` kept their exact
signatures and behaviour, so 10.2's dispatcher, 10.3's DSL validation,
10.3's durable activity, and `workflows.py` needed no changes at all.
`execute_action()` still raises `AutomationValidationError` for an
unresolvable action type, preserving its permanent/non-retryable
classification. Authorization, tenant scoping, idempotency, audit, and
retry semantics are untouched -- the registry maps names to
implementations and holds nothing else: no cached actor, no tenant, no
authorization decision, and no `__dict__` to grow one.

**The remaining 10.4A integration point, deliberately not built.** A
`product.ai` adapter satisfying `WorkflowAction` and calling
`invoke_product_ai_tool()`, its action name added to `ACTIONS`, and one
composition-root registration call. Wiring any of that now would be
10.4A, and it stays blocked on 9.4 regardless. The seam is proven
instead by a test module that `product.automation` does not import,
supplying a working action purely by satisfying the neutral contract.
