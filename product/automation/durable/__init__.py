"""Phase 10.3 durable-execution infrastructure spike (docs/ROADMAP.md
Phase 10.3; docs/ADR/0007-automation-execution-substrate.md).

**This package proves infrastructure viability. It does NOT implement the
production multi-step Workflow Builder.** No branching workflow graphs, no
delayed business workflows, no wait-for-event business workflows, no
workflow-versioning UI, no 10.3 workflow domain, no 10.4. Those remain
future work, gated on a separate, explicit go-ahead -- this package exists
only to answer: "can the chosen durable engine be integrated safely with
this product's deployment and security model?"

**Engine selected: Temporal**, via the official `temporalio` Python SDK
(pinned `==1.33.0` in `pyproject.toml`) -- approved architecture review
recommended "Temporal or equivalent"; this spike makes the concrete
selection. Compatibility verified directly against PyPI before adding it:
`temporalio` 1.33.0 declares `requires_python >= 3.10` and lists Python
3.13 in its own classifiers, matching this repository's `requires-python
= ">=3.13"` exactly, and ships a prebuilt `cp310-abi3` wheel for
win_amd64/linux/macos -- no C toolchain needed on either this Windows dev
machine or the `python:3.13-slim` Docker image. No blocker found.

**Dependency boundary (docs/ARCHITECTURE.md section 2; the approved
architecture review's own §7):**

    product.automation (domain: Workflow, WorkflowRun, actions, conditions)
        |
        v
    product.automation.durable   <-- this package (adapter only)
        |
        v
    temporalio SDK                (external, Product-owned dependency)
        |
        v
    Temporal server / persistence (external infrastructure, Docker Compose
                                    service in local dev)

`temporalio` is imported ONLY from inside this package. Nothing under
`core`/`infra`/`api`/`control_plane` (SaaS-OS) imports this package or
`temporalio` -- SaaS-OS remains entirely unaware Temporal exists, and
cannot import it even if it wanted to: SaaS-OS is a pinned upstream
dependency of this product, never the reverse, so no code path in SaaS-OS
can reach a Product-side package at all (docs/ARCHITECTURE.md section 1).
No import-linter contract can *express* "core does not import product"
inside this repository's own `[tool.importlinter] root_packages =
["product"]` configuration (SaaS-OS's own source is outside that root),
so this boundary is enforced structurally by the one-way dependency pin
itself, not by a linter rule added here -- verified empirically (this
spike's own audit) by confirming no `import product` exists anywhere in
the installed `saas-os` source.

`product/api/main.py` deliberately does NOT import this package. Wiring
a real product feature into the running API app is 10.3+ production
scope, not this spike's -- and doing so now would make ordinary API
startup depend on `TEMPORAL_ADDRESS` being configured, which is exactly
what "Product remains usable if Temporal is not configured/started" (this
phase's own required spike outcome) forbids. This package is reachable
only from its own dedicated worker entrypoint (`worker.py`) and from
tests/a client script that explicitly wants to exercise it.

**Determinism boundary (Temporal's own binding rule, restated here for
this product's own action-writers' benefit):** workflow code
(`workflows.py`) must never directly perform a SQL query, a network
request, a filesystem operation, uncontrolled randomness, uncontrolled
wall-clock access, a `core.rbac` call, or a `core.audit_log` write --
all of that belongs in an activity (`activities.py`), which Temporal
re-invokes (and, on replay, may re-invoke exactly once more per its own
at-least-once contract) outside the workflow's own deterministic replay
path. The Python SDK enforces part of this automatically via its default
sandboxed workflow execution environment (restricted imports, no thread/
process spawning, no direct socket access from workflow code); this
package still writes to that boundary deliberately rather than relying on
the sandbox alone, since the sandbox catches some but not all
non-determinism (e.g. it does not catch a `random.random()` call seeded
identically on every replay).

**Activity security boundary (established here, not yet exercised by a
real business action):** the one activity this spike defines
(`activities.py::probe_activity`) takes `tenant_id` as an explicit,
plain argument -- never resolved from arbitrary payload content -- and
makes zero `core.rbac`/`core.audit_log`/database calls itself (it has no
side effect to authorize). **Every future production activity must
re-enter the existing Product action/RBAC boundary at the moment it
actually executes** -- call the same `product.automation.actions
.execute_action()` this phase's single-step engine (`product/automation/
dispatcher.py`) already uses, which itself calls straight into
`core.rbac.can()`/`require()` through the underlying CRM/email/webhook
function, exactly as today. The engine (Temporal) never makes an
authorization decision and never caches one from workflow-submission
time -- see `core/rbac/authorization.py::can()`'s own docstring: it is
evaluated live, under a tenant-lifecycle row lock, on every call, which
is what makes "re-check at every step" a real, load-bearing guarantee
rather than a hope. No second RBAC implementation is introduced anywhere
in this package.

**Privacy / history**: see `client.py`'s own docstring for exactly what
this spike puts into Temporal's workflow history (synthetic identifiers
only, never real customer data).

**Tenant lifecycle / purge boundary**: see `client.py::list_workflows_for_tenant`/
`terminate_workflows_for_tenant`'s own docstrings for the interface this
spike proves out (not a full purge-participant integration -- that
remains future work, per this phase's own explicit scope limit).
"""
