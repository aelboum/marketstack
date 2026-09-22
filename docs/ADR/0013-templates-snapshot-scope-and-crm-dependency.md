# ADR-0013: Snapshot Domain Scope, ID-Elimination Design, and the CRM Dependency

Status: ACCEPTED
Date: 2026-09-22

## Context

`docs/ROADMAP.md` Phase 14 defines exactly one domain concept —
**snapshot**: "a named bundle of configuration... belonging to one
tenant" (14.1), applied to "a new or existing tenant, preserving tenant
isolation throughout" (14.2). It does not define a second, independently
versioned/published "Template" catalog distinct from a snapshot; a named,
reusable, appliable snapshot already *is* the reusable-configuration
concept the roadmap asks for. This ADR does not introduce a second
concept the roadmap's own Objective/Scope/Acceptance-Criteria text does
not name, mirroring the same "implement what the roadmap actually says,
not a generic superset" discipline `docs/ADR/0010-...`/`0012-...` already
applied to Reputation and Billing.

14.1's own Dependencies line names Phases 4 (CRM), 6 (Marketing), 7
(Appointments), 10 (Automation), 11 (Websites) as the modules whose
configuration might be bundled. Building export/import for all five in
one phase would require this module to depend on all five — a
cross-cutting dependency footprint far larger than any other module in
this codebase carries, and one this phase's own scope discipline ("Use a
small representative set... to prove the architecture," the identical
principle `docs/ADR/0012-...` already applied to entitlement mapping)
argues against. This ADR picks **one** representative configuration
domain, proves the full export -> store -> apply architecture against it,
and explicitly inventories the rest as deferred rather than silently
omitted.

## Decision 1: CRM Pipelines/Stages as the sole implemented domain

`product.crm.pipelines` (`Pipeline`, `PipelineStage`) is the domain this
phase implements, chosen after inspecting every candidate named in 14.1:

| Domain | Portable? | Reason |
|---|---|---|
| **CRM pipelines/stages** | Yes | `Pipeline{name, is_default}` / `PipelineStage{name, position, is_won, is_lost}` — no field is a cross-entity reference, a secret, or PII. Already create+read-only in `product/crm/pipelines.py` (no update/delete exists) — the exact "no mutation history to reconcile" shape a fresh-entity clone needs. |
| Marketing forms/campaign templates | Deferred | Not inspected against an equally strict portability test in this phase; would need its own dependency review. |
| Appointments calendars | Deferred | `Calendar.owner_user_id` is a `core.users` reference — **not portable**: a user in the source tenant is not necessarily a member of the target tenant. Cloning a calendar requires either remapping to a target-tenant member (a real product decision with no obvious default) or omitting ownership, neither of which this phase decides unilaterally. |
| Automation workflows | Deferred | `Workflow.trigger_config`/`action_config` are open-ended JSON that may itself embed tenant-local identifiers (e.g. a pipeline id, a specific contact filter) depending on trigger/action type — auditing every action type's config shape for embedded tenant-local references is a substantial review this phase does not perform. |
| Websites pages/content blocks | Deferred | Page content blocks may reference uploaded assets/media (`product/websites/content_blocks.py`) whose portability across tenants has not been reviewed. |

Every deferred domain is a documented scope boundary, not a silent gap —
extending `product/templates/` to a second domain is future work with its
own review, exactly as `docs/ADR/0012-...`'s own "Rejected Alternative"
section reasons about scope.

## Decision 2: no ID is ever captured — remapping is unnecessary by construction

`docs/ROADMAP.md` 14.2 requires "every foreign key inside the snapshot
must be remapped to the target tenant's own newly-created entities, never
left pointing at the source tenant's data." The safest possible
implementation of that requirement is to never let a tenant-local
identifier enter the payload in the first place: `product/templates
/snapshots.py::_export_crm_pipelines()` reads via `product.crm.pipelines
.list_pipelines()`/`list_stages()` and copies only `name`/`is_default`/
`position`/`is_won`/`is_lost` — never `id`, `tenant_id`, or `pipeline_id`.
Import (`_apply_crm_pipelines()`) always calls `create_pipeline()`/
`create_stage()`, which always generate fresh server-side ids in the
target tenant. There is structurally nothing to remap, and therefore
nothing to get wrong: a snapshot payload contains zero identifiers of any
kind, classifying every captured field as **portable** under this ADR's
own reference classification (`docs/ROADMAP.md` Phase 14's own "portable
/ tenant-local / global / external / secret" taxonomy) — the `tenant-
local`/`external`/`secret` classes are all empty sets for this domain by
design, not by a remapping step that could fail.

## Decision 3: apply is not fully transactional across the whole operation — disclosed, not hidden

14.2's Rollback line states "a failed/partial clone leaves no partially-
created data — the import is transactional, all-or-nothing." Verified
directly against `product/crm/pipelines.py`: it deliberately implements
**no update or delete** for `Pipeline`/`PipelineStage` ("the roadmap
states no update/delete requirement... deferred, not overlooked," that
module's own docstring). This means `product/templates/` has no CRM-
published way to compensate/roll back an already-created pipeline if a
later stage-create call in the same `apply_snapshot()` operation fails —
the only two ways to achieve true atomicity would be (a) CRM exposing a
delete it deliberately does not have, or (b) `product/templates/` writing
to `crm.pipelines`/`crm.pipeline_stages` directly, which would violate
the "a module never reads/writes another module's tables directly"
boundary this entire codebase enforces via import-linter.

Given that constraint, `apply_snapshot()` is made **practically** all-
or-nothing rather than transactionally so: every validation that can
fail — authorization on both tenants, schema-version support, payload
structural validation, domain-support validation — runs *before* any
`create_pipeline()`/`create_stage()` call is made, so the only residual
failure window is a genuine infrastructure-level failure mid-loop (a
dropped DB connection), not a business-logic rejection. This residual
risk is disclosed here explicitly, tested for detectability (an audit
`FAILURE` entry is still recorded), and accepted for this phase rather
than solved with unreviewed direct-table-write machinery. A future phase
revisiting this would need `product.crm` to publish a delete/compensating
primitive first.

## Decision: `product.templates` may depend on `product.crm` (one-directional)

Mirrors `docs/ADR/0005-...`/`0008-...`/`0010-...`'s identical shape.

1. `product.templates` MAY import `product.crm`'s own published service
   functions (`product.crm.pipelines`: `list_pipelines`, `list_stages`,
   `create_pipeline`, `create_stage`) — never `product.crm.models`
   directly, and never any other product module's internals.
   `product.crm` may NEVER import `product.templates`.
2. `product.templates` remains fully independent from every other product
   module. This is not a license for a second domain to be added to
   `product/templates/` without its own dependency review, even if that
   domain also happens to need CRM.
3. Enforced with import-linter (`pyproject.toml`): `"product.templates"`
   removed from the blanket independence contract; a new `forbidden`
   contract ("Templates does not depend on any product module except
   CRM") and a new `layers` contract ("Templates may depend on CRM, never
   CRM on Templates").

## Consequences

- `product/templates/snapshots.py` is the one place in this product that
  imports across the `templates -> crm` boundary.
- A snapshot's `payload` column is bounded (262144 bytes, enforced by a
  database `CHECK` constraint) — the same "bounded JSON, never an
  unbounded blob" discipline `product/websites/models.py::Page
  .content_blocks` and `product/automation/durable/models.py
  ::WorkflowVersion.steps` already establish.
- No `update`/`delete` service function exists for `Snapshot` — it is
  immutable from creation until tenant purge, the same "no mutation
  history to reconcile" shape its own source domain (CRM pipelines)
  already has.
