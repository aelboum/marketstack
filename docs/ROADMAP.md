# Implementation Roadmap

Status: PROPOSED sequencing. Nothing below is implemented. Each phase follows
the same template `saas-os`'s own `docs/IMPLEMENTATION-ROADMAP.md` uses:
Objective, Dependencies, Scope, Tests, Security, Acceptance Criteria,
Rollback, Outcome, Checkpoint. "Outcome" is `not started` for every phase in
this document — it is filled in as each phase actually ships, the same
discipline `saas-os` follows. "Checkpoint" states what gets reviewed with you
before the next phase starts; no phase begins before its predecessor's
checkpoint is cleared.

Every phase respects `docs/RESPONSIBILITY-MATRIX.md`: Category A capability
is consumed, never rebuilt; Category B is built here as an interim, cleanly
interfaced, with the upstream-donation path noted; Category C is built here
permanently; Category D is adapter-isolated. Every phase respects
`docs/ARCHITECTURE.md` §2's internal module-boundary rule. No phase modifies
`saas-os`.

As of 2026-09-20 (Phases 0–7 checkpointed, per the outcomes recorded in each
phase below and `de26edc` for Phase 7), this document decomposes into **two
coordinated tracks** rather than one: the **Product Backend Track** (Phase 0
through Phase 20, unchanged below) and the **UI Track** (`UI-1` through
`UI-9`, added at the end of this document, after Phase 20). The UI Track
begins now, in parallel with the remaining backend phases, rather than
waiting for Phase 20 to close — see "UI Track" for the sequencing principle,
the frontend-first/backend-first rule, the feedback-loop and mock-data
policies, and `docs/ARCHITECTURE.md` §6.1 for the non-negotiable
frontend/backend layering both tracks are reviewed against. Nothing in
Phases 0–20 below is renumbered, resequenced, or reworded by this addition.

### Roadmap Overview — Two Parallel Tracks

```text
PRODUCT BACKEND TRACK
──────────────────────

0  Decisions                         ✓
1  Repo Foundation                   ✓
2  Product Foundation                ✓
3  Agency / Client                   ✓
4  CRM                               ✓
5  Conversations                     ✓
6  Marketing                         ✓
7  Appointments                      ✓  (de26edc)
8  Telephony
9  AI
10 Automation
11 Websites
12 Reputation
13 SaaS Resale / Billing
14 Templates / Snapshots
15 Mini Accounting
16 Reporting
17 Integrations Hardening
18 Production / Dutch Compliance
19 Prospecting & Lead Intelligence
20 Prospecting Automation & AI Agents


UI TRACK
────────

UI-1  Application Shell & Frontend Foundation   ← next
UI-2  Agency / Dashboard
UI-3  CRM
UI-4  Conversations
UI-5  Marketing
UI-6  Appointments
UI-7  Settings / Branding / Tenant Configuration
UI-8  Responsive / Accessibility / UX Hardening
UI-9  Mature Design System & Reusable Components
```

The two tracks run side by side: a UI phase begins once its corresponding
backend capability is sufficiently stable, not once the entire backend
track (through Phase 20) is complete. See "UI Track" below for the full
phase breakdown, dependencies, and the principles governing how the two
tracks stay in sync without the UI Track becoming a second, divergent
architecture.

---

## Phase 0 — Product Decisions & Architecture

- **Objective**: produce the documentation set this repository now contains
  (`README.md`, `docs/ARCHITECTURE.md`, `docs/RESPONSIBILITY-MATRIX.md`,
  `docs/REPOSITORY-STRATEGY.md`, this roadmap, and the supporting documents)
  and get your explicit sign-off before any code is written.
- **Dependencies**: none.
- **Scope**: documentation only. No repository scaffold, no dependency
  installed, no code.
- **Tests**: none (documentation phase).
- **Security considerations**: none beyond ensuring the security/privacy
  mapping (`docs/SECURITY-PRIVACY.md`) is reviewed before Phase 1 begins,
  given its downstream blast radius — mirrors `saas-os`'s own Phase 0.1
  treatment of its multi-tenancy/identity ADRs.
- **Acceptance criteria**: you have reviewed this document set and either
  approved it, or returned specific changes.
- **Rollback**: n/a — no system exists yet.
- **Outcome**: not started (this document set is the deliverable; awaiting
  your review).
- **Checkpoint**: **STOP HERE.** Do not proceed to Phase 1 without your
  explicit approval. See `docs/RISKS-AND-OPEN-QUESTIONS.md` for the specific
  decisions that need your input before Phase 1 can be scoped precisely.

---

## Phase 1 — Repository Foundation

Establishes the repository itself, the `saas-os` dependency, migrations, and
CI — before any product-specific module exists. Mirrors `saas-os`'s own
Phase 1 (Repository Foundations) at one remove.

### 1.1 Repository scaffold from the reference-consumer pattern
- **Objective**: create this repository's physical structure — `product/`
  module skeleton per `docs/ARCHITECTURE.md` §2.1 (empty modules with
  ownership docstrings, no logic yet), `pyproject.toml` pinning `saas-os` as
  a Git/VCS dependency at a specific commit SHA, Dockerfile/docker-compose
  skeleton, `.env.example`.
- **Dependencies**: a tagged/committed `saas-os` state to pin to (coordinate
  with `saas-os`'s own release discipline — see
  `docs/REPOSITORY-STRATEGY.md`).
- **Scope**: directory/config scaffolding only, copied-and-owned from
  `examples/reference-consumer`'s structural pattern (never its business
  logic, never a live path dependency on `saas-os`'s working tree).
- **Tests**: a clean clone installs successfully (`pip install -e ".[dev]"`
  resolves the pinned `saas-os` dependency).
- **Security considerations**: `.env` gitignored from the first commit;
  `.env.example` placeholder values only, per `saas-os`'s own
  `docs/ADR/0012-...` discipline, inherited here.
- **Acceptance criteria**: repository builds from a clean checkout; `import
  core.tenancy` succeeds against the pinned `saas-os` package.
- **Rollback**: delete the repository; nothing depends on it yet.
- **Outcome**: not started.
- **Checkpoint**: review the directory shape against
  `docs/ARCHITECTURE.md` §2.1 before continuing.

### 1.2 Two-environment migration bootstrap
- **Objective**: implement the bootstrap/upgrade script running `saas-os`'s
  core migrations then this product's own (initially empty) migration set,
  per `docs/REPOSITORY-STRATEGY.md`.
- **Dependencies**: 1.1.
- **Scope**: this product's own Alembic environment (`alembic_version`,
  separate from `saas-os`'s own `alembic_version_saas_os`); one bootstrap
  script; no product tables yet.
- **Tests**: against a disposable Postgres container — fresh install runs
  both migration sets in order; a second run is idempotent (no-op).
- **Security considerations**: migration role vs. runtime role split,
  mirrored from `saas-os`'s own `MIGRATIONS_DATABASE_URL`/`DATABASE_URL`
  convention.
- **Acceptance criteria**: a fresh database ends up with both `core.*`
  schemas and this product's own (still-empty) schema namespace correctly
  versioned.
- **Rollback**: drop the disposable database; no production data exists.
- **Outcome**: not started.
- **Checkpoint**: prove this against a real disposable Postgres before
  building on top of it.

### 1.3 Application composition root
- **Objective**: `product/api/main.py` built on `api.platform
  .build_platform_app()` (ADR-0017 in `saas-os`), health check wired, no
  product routes yet.
- **Dependencies**: 1.2.
- **Scope**: the FastAPI app instance and its SaaS-OS-provided
  auth/tenant-resolution/RBAC middleware chain only.
- **Tests**: end-to-end request through the real middleware chain (mirrors
  `saas-os` roadmap Phase 8.1's own test shape) — unauthenticated rejected,
  authenticated-but-unauthorized rejected, valid request passes.
- **Security considerations**: dedicated review — this is the one place
  every subsequent product route passes through; get it right once.
- **Acceptance criteria**: `/health` responds correctly; no route can be
  added later that bypasses this chain (enforced by 1.4's import-linter
  contract where feasible, mirroring `saas-os`'s own approach).
- **Rollback**: revert; no routes exposed yet.
- **Outcome**: not started.
- **Checkpoint**: confirm the middleware chain is genuinely SaaS-OS's own,
  not a reimplementation, before any product route is added.

### 1.4 Internal import-boundary enforcement
- **Objective**: wire an `import-linter` contract in this repository
  enforcing `docs/ARCHITECTURE.md` §2.2 (no `product/<module>` imports
  another `product/<module>` directly; only `product/foundation` and
  `saas-os` packages are always-allowed dependencies).
- **Dependencies**: 1.1.
- **Scope**: CI config + the contract itself; no product module exists yet
  to violate it, so this ships before Phase 2, not after.
- **Tests**: a deliberately-added violating import fails CI, then is
  removed — the same non-vacuousness proof `saas-os` requires of its own
  boundary contracts.
- **Security considerations**: this check is itself a design-integrity
  control, per `saas-os`'s own treatment of its equivalent contract.
- **Acceptance criteria**: CI red on a cross-module import; CI green
  otherwise.
- **Rollback**: revert CI config; no production impact.
- **Outcome**: not started.
- **Checkpoint**: none beyond CI passing — low-risk, mechanical.

### 1.5 CI pipeline
- **Objective**: mirror `saas-os`'s own `scripts/check-*.sh` /
  `check-all.sh` discipline for this repository (backend lint/type/test,
  frontend lint/build once 1.6 exists, security scan, Docker build).
- **Dependencies**: 1.1–1.4.
- **Scope**: CI workflow only.
- **Tests**: pipeline runs end-to-end on a trivial commit.
- **Security considerations**: dependency vulnerability scan (`pip-audit`)
  and secret scan (`detect-secrets`) present from day one, mirroring
  `saas-os`'s own Phase 1.4.
- **Acceptance criteria**: a PR triggers the full pipeline, reports
  pass/fail per stage.
- **Rollback**: revert CI config.
- **Outcome**: not started.
- **Checkpoint**: none — mechanical, low-risk.

### 1.6 Frontend scaffold
- **Objective**: Next.js app shell (per `docs/ARCHITECTURE.md` §6, fully
  product-owned), wired to `core.identity`'s OIDC login flow, no product UI
  yet beyond an authenticated placeholder page.
- **Dependencies**: 1.3.
- **Scope**: frontend project scaffold, auth flow only.
- **Tests**: a user can complete the OIDC login flow and land on an
  authenticated placeholder page.
- **Security considerations**: no client-side storage of any token beyond
  what the OIDC flow's own session mechanism already dictates.
- **Acceptance criteria**: login/logout works end-to-end against a real
  ZITADEL instance (dev/sandbox).
- **Rollback**: revert; no users onboarded yet.
- **Outcome**: not started.
- **Checkpoint**: demo the login flow before building any product screen on
  top of it.

---

## Phase 2 — Product Foundation

`product/foundation/` — the shared abstractions every later module depends
on, built before any module that needs them, so no later phase invents its
own ad hoc version.

### 2.1 Shared value objects and settings helpers
- **Objective**: `Money`, phone-number normalization, tenant-scoped settings
  read/write helpers.
- **Dependencies**: Phase 1.
- **Scope**: `product/foundation/values.py`, `product/foundation/settings.py`.
- **Tests**: unit tests per value object (currency rounding, phone-number
  edge cases).
- **Security considerations**: none beyond ordinary input validation.
- **Acceptance criteria**: at least CRM and Accounting's Phase 4/15 designs
  can name a concrete need each of these satisfies (proves they're not
  speculative).
- **Rollback**: revert; nothing depends on it yet.
- **Outcome**: not started.
- **Checkpoint**: none — low-risk foundation.

### 2.2 Product event dispatcher
- **Objective**: implement the mechanism described in `docs/ARCHITECTURE.md`
  §4 — in-process pub/sub plus an `infra.jobs`-backed durable variant, every
  event carrying `tenant_id`.
- **Dependencies**: 2.1.
- **Scope**: `product/foundation/events.py`. No module publishes real events
  yet — this phase proves the mechanism with a stub event.
- **Tests**: a stub event publishes, a subscribed handler receives it
  (in-process case); the durable variant survives a simulated process
  restart (via `infra.jobs`).
- **Security considerations**: an event handler must not receive an event
  for a tenant its own scope wouldn't otherwise permit — event delivery is
  never a side channel around RBAC. Test this adversarially.
- **Acceptance criteria**: matches `docs/ARCHITECTURE.md` §4's stated shape
  (`publish(event)` / `subscribe(event_type, handler)`); every event schema
  is versioned from its first definition.
- **Rollback**: revert; no module depends on it yet.
- **Outcome**: not started.
- **Checkpoint**: review the interface shape specifically for how easily it
  could be re-pointed at a future SaaS-OS-provided implementation — this is
  the Category B interim design's one real test.

### 2.3 White-label branding data model and `BrandingProvider`
- **Objective**: implement `docs/WHITE-LABEL.md` §2–§4 — the
  `white_label.tenant_branding` table, the fallback-chain resolution logic,
  and the `BrandingProvider` interface.
- **Dependencies**: 2.1; `core.tenancy` (A, already available).
- **Scope**: `product/white_label/`. No UI to edit branding yet (Phase 3+
  builds the agency-facing admin UI) — this phase proves resolution
  correctness.
- **Tests**: fallback-chain resolution across a 3-level hierarchy (client →
  agency → platform default), including the adversarial case
  (`docs/WHITE-LABEL.md` §6 — one agency's branding never appears when
  resolving for an unrelated tenant).
- **Security considerations**: fail-closed on an unrecognized/malformed
  tenant id; no default-tenant fallback.
- **Acceptance criteria**: resolution is correct for all three levels and
  for a tenant with no customization at any level (falls through cleanly to
  platform default).
- **Rollback**: revert; no tenant depends on custom branding yet.
- **Outcome**: not started.
- **Checkpoint**: review test coverage of the adversarial cross-agency case
  specifically before this ships — this is the one place a bug becomes a
  real brand-leakage incident.

### 2.4 Custom domain resolution middleware
- **Objective**: implement `docs/WHITE-LABEL.md` §3.
- **Dependencies**: 2.3; Phase 1.3 (the composition root this middleware
  sits in front of).
- **Scope**: `product/white_label/domains.py` + ingress wiring. TLS
  provisioning automation is out of scope for this subphase (may start as a
  manual operational step).
- **Tests**: a request for a mapped domain resolves the correct tenant; an
  unmapped domain is rejected (never falls through to any tenant).
- **Security considerations**: fail-closed, per §2.3's pattern; no
  domain-to-tenant cache staleness beyond a documented, tested bound (a
  domain remapped/removed must not continue routing to the old tenant
  indefinitely).
- **Acceptance criteria**: matches `docs/WHITE-LABEL.md` §3's request flow
  exactly.
- **Rollback**: revert; no domain depends on it yet (agencies use the
  default subdomain until this ships).
- **Outcome**: not started.
- **Checkpoint**: none beyond the security test above passing.

---

## Phase 3 — Agency / Client Management

Consumes SaaS-OS's tenant hierarchy directly, per `docs/ARCHITECTURE.md` §3.
Sequenced before CRM/Marketing/etc. because every later module's data is
scoped per client tenant — the hierarchy must exist first.

### 3.1 Agency and client tenant provisioning
- **Objective**: agency signup creates a root tenant; agency creates client
  tenants as children, using `core.tenancy`'s existing hierarchy mechanism
  unchanged.
- **Dependencies**: Phase 2.
- **Scope**: `product/agency/` provisioning workflow, product-specific
  default data seeding (a starter pipeline, default settings) for a new
  client — the seeding logic itself is Category C; the tenant creation
  underneath it is Category A.
- **Tests**: agency creates N clients; `core.tenant_ancestry` reflects the
  hierarchy correctly; a client cannot create its own sub-children beyond
  whatever depth policy is set (`TENANT_MAX_HIERARCHY_DEPTH`, already
  configurable in `core.tenancy`).
- **Security considerations**: dedicated review — first real use of the
  hierarchy in this product; confirm hierarchy alone grants no
  authorization (`saas-os` `docs/MULTI-TENANCY.md` §8) holds under this
  product's own provisioning code path too.
- **Acceptance criteria**: agency onboarding → first client creation works
  end-to-end.
- **Rollback**: standard — no production tenant data yet at this phase.
- **Outcome**: not started.
- **Checkpoint**: demo agency + client creation before building
  role/delegation UI on top.

### 3.2 Client onboarding and membership
- **Objective**: invite a client's own users, using `core.identity
  .create_invitation()`/`accept_invitation()` and `core.rbac.assign_role()`
  unchanged.
- **Dependencies**: 3.1.
- **Scope**: product-facing invitation UI/API only — the underlying
  invitation lifecycle is Category A.
- **Tests**: invitation lifecycle (send, accept, one-time, replay-resistant
  — already covered by `saas-os`'s own test suite; this phase's tests
  confirm the product-level UI/API wraps it correctly, not re-testing
  `core.identity` itself).
- **Security considerations**: no new security surface — this phase must
  not introduce a second invitation mechanism.
- **Acceptance criteria**: a client user can be invited, accept, and land
  in their own tenant with the correct starting role.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond tests passing — thin wrapper phase.

### 3.3 Delegated administration and explicit deny (product UI)
- **Objective**: agency-facing UI/API over `core.rbac`'s existing
  `SUBTREE`-scoped role assignment, `create_delegation()`, and
  `create_deny()`/`revoke_deny()`.
- **Dependencies**: 3.2.
- **Scope**: UI/API wrapper only — the authorization mechanics are already
  implemented and already tested in `saas-os`.
- **Tests**: an agency-level `SUBTREE` role reaches a new client
  automatically upon creation (live re-evaluation, per `saas-os`
  `docs/MULTI-TENANCY.md` §9); an explicit deny on one specific client
  correctly overrides an otherwise-reaching subtree role.
- **Security considerations**: dedicated review — this is the UI surface
  for a high-consequence capability (an agency user's reach across every
  client). Confirm the UI cannot construct a grant broader than
  `core.rbac.can()` would actually honor.
- **Acceptance criteria**: matches the scenarios already demonstrated in
  `saas-os`'s `examples/reference-consumer/reference_consumer/scenarios.py`,
  exercised now through this product's own UI/API instead of directly
  against `core.rbac`.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: walk through the delegation + explicit-deny scenarios
  live before this ships to any real agency.

### 3.4 Support access workflow
- **Objective**: product UI over `core.rbac`'s existing support-access
  request/approve/deny/revoke workflow, for platform or agency staff
  troubleshooting a client's data.
- **Dependencies**: 3.3.
- **Scope**: UI/API wrapper only.
- **Tests**: a support-access grant is time-boxed, audited, and revocable;
  an expired/revoked grant is denied at the same `core.rbac.can()`
  chokepoint every other check uses.
- **Security considerations**: dedicated review — this is explicitly named
  in the brief as a required capability, and is exactly the kind of
  "temporary convenience backdoor" `saas-os` `docs/SECURITY.md` §1 warns
  against building outside the sanctioned mechanism. No shortcut.
- **Acceptance criteria**: full propose → approve → time-boxed access →
  automatic/manual revoke cycle works, fully audited.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: security review sign-off required before this ships.

---

## Phase 4 — CRM

Pure Category C, per `docs/RESPONSIBILITY-MATRIX.md`. First module because
Marketing, Conversations, Appointments, and Automation all reference
contacts/companies/pipelines.

### 4.1 Contacts and companies
- **Objective**: `crm.contacts`, `crm.companies`, the relationship between
  them, tenant-scoped.
- **Dependencies**: Phase 3.
- **Scope**: data model, CRUD service, CRUD API — no pipeline/tasks yet.
- **Tests**: tenant isolation (a client cannot see another client's
  contacts, including across the agency hierarchy unless an explicit
  `SUBTREE` grant permits it); CRUD correctness.
- **Security considerations**: standard tenant-isolation test suite,
  mirroring `saas-os`'s own Phase 3.1 cross-tenant leakage test discipline,
  applied to this product's first tenant-owned table.
- **Acceptance criteria**: contact/company CRUD works; cross-tenant leakage
  test suite passes.
- **Rollback**: standard — revert code, no dependents yet.
- **Outcome**: not started.
- **Checkpoint**: this is the first product-owned tenant data table —
  review the isolation test suite specifically before any later module
  builds on this pattern.

### 4.2 Leads, opportunities, pipelines, stages
- **Objective**: pipeline/stage configuration (tenant-customizable),
  opportunities linked to contacts/companies, stage-change tracking.
- **Dependencies**: 4.1.
- **Scope**: data model, service, API. Publishes a `crm.opportunity
  .stage_changed` event via the Phase 2.2 dispatcher (first real consumer of
  it) — Automation (Phase 10) and Reporting (Phase 16) are the eventual
  subscribers, not built yet.
- **Tests**: stage transitions, event publication correctness.
- **Security considerations**: none beyond 4.1's inherited isolation.
- **Acceptance criteria**: a lead can move through a configurable pipeline;
  each stage change is a correctly-shaped published event.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: confirm the published event shape before Phase 10
  (Automation) commits to consuming it — a late event-shape change is
  cheap now, expensive once Automation depends on it.

### 4.3 Tasks, notes, activities
- **Objective**: tasks/notes/activity timeline attached to a contact,
  company, or opportunity.
- **Dependencies**: 4.1, 4.2.
- **Scope**: data model, service, API.
- **Tests**: CRUD correctness; activity timeline ordering/pagination.
- **Security considerations**: none beyond inherited isolation.
- **Acceptance criteria**: a task/note can be attached to any of the three
  entity types and appears correctly in the activity timeline.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 4.4 Custom fields, tags, search/filtering
- **Objective**: tenant-defined custom fields on contacts/companies/
  opportunities; tagging; search/filter API.
- **Dependencies**: 4.1–4.3.
- **Scope**: data model (a flexible-schema approach — e.g. a typed
  key/value table or JSONB column, decided at implementation time), service,
  API.
- **Tests**: custom-field CRUD; search/filter correctness across standard
  and custom fields.
- **Security considerations**: input validation on custom-field definitions
  (a tenant defining a custom field must not be able to collide with a
  reserved column name or inject into the search query path — parameterized
  queries only, no dynamic SQL from tenant-supplied field names).
- **Acceptance criteria**: a tenant can define a custom field, populate it,
  and filter by it.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: review the custom-field storage approach's query-injection
  surface specifically before this ships.

### 4.5 Import/export
- **Objective**: CSV import/export for contacts/companies, including custom
  fields.
- **Dependencies**: 4.4.
- **Scope**: import/export service + API; runs as an `infra.jobs` background
  job for large files.
- **Tests**: round-trip correctness (export then re-import matches); a
  malformed import file fails cleanly with a clear per-row error report,
  never a partial silent failure.
- **Security considerations**: uploaded file size/type validation; the
  import job is tenant-scoped exactly like any other job
  (`saas-os` `docs/MULTI-TENANCY.md` §4's job-payload convention).
- **Acceptance criteria**: a real-world-shaped CSV imports correctly; export
  round-trips.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: this closes out CRM's initial scope — review before
  moving to Conversations.

---

## Phase 5 — Conversations

Unified inbox, built before Marketing/Telephony/AI since those all send or
receive through it.

### 5.1 Conversation and message data model
- **Objective**: `conversations.threads`, `conversations.messages`,
  channel-agnostic (email/SMS/WhatsApp/chat share one thread/message shape,
  with a `channel` discriminator), linked to a CRM contact.
- **Dependencies**: Phase 4.1 (contact linkage).
- **Scope**: data model, service. No sending yet — this phase proves the
  storage/threading model.
- **Tests**: thread/message CRUD; correct contact linkage; multi-channel
  threading correctness (one contact, multiple channels, correctly grouped
  or correctly kept separate — a specific product decision to make at
  implementation time, not assumed here).
- **Security considerations**: standard inherited isolation.
- **Acceptance criteria**: a thread can be created and populated across at
  least two channel types in the data model, even before real sending
  exists.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: review the channel-agnostic thread model before building
  provider adapters on top of it — this is the one design choice expensive
  to change later.

### 5.2 Outbound email (reuses `core.email`, Category A)
- **Objective**: wire `product/conversations/` to `core.notifications`/
  `core.email` for actual sending.
- **Dependencies**: 5.1.
- **Scope**: adapter wiring only — no new email-sending mechanism.
- **Tests**: an outbound message sends and is correctly recorded in the
  thread.
- **Security considerations**: none beyond what `core.email` already
  provides.
- **Acceptance criteria**: end-to-end send through `core.email` in a test
  environment.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 5.3 Outbound/inbound SMS (Category D)
- **Objective**: `SmsProvider` adapter (`docs/INTEGRATIONS.md`), one
  concrete provider, inbound webhook handling.
- **Dependencies**: 5.1.
- **Scope**: adapter + inbound webhook route, signature-verified.
- **Tests**: send/receive round-trip against the provider's sandbox;
  webhook signature verification (a forged webhook is rejected).
- **Security considerations**: inbound webhook signature verification is a
  hard requirement, not optional — see `docs/INTEGRATIONS.md`
  §"Webhook Security."
- **Acceptance criteria**: a real SMS sends and a reply is correctly
  threaded.
- **Rollback**: disable the provider adapter; conversation data model
  unaffected.
- **Outcome**: not started.
- **Checkpoint**: none beyond the webhook-security test passing.

### 5.4 WhatsApp (Category D)
- **Objective**: `WhatsAppProvider` adapter, same pattern as 5.3.
- **Dependencies**: 5.1, 5.3 (reuses the inbound-webhook pattern proven
  there).
- **Scope**: adapter + inbound webhook route.
- **Tests**: mirrors 5.3.
- **Security considerations**: mirrors 5.3; additionally, WhatsApp Business
  API template-message approval constraints are a provider-specific detail
  this adapter must respect, not something product code works around.
- **Acceptance criteria**: mirrors 5.3.
- **Rollback**: disable the provider adapter.
- **Outcome**: not started.
- **Checkpoint**: none.

### 5.5 Assignment, internal notes, templates
- **Objective**: assign a conversation to a team member; internal (non-sent)
  notes on a thread; reusable message templates.
- **Dependencies**: 5.1–5.4.
- **Scope**: data model additions + service + API.
- **Tests**: assignment correctness; internal notes never sent to the
  contact (a specific, tested guarantee — this is the kind of bug that
  becomes a real incident if a note leaks as an outbound message).
- **Security considerations**: the internal-note/outbound-message
  distinction must be enforced at the data-model or service layer, not by
  UI convention alone.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: review the internal-note isolation test specifically
  before this ships.

---

## Phase 6 — Marketing

### 6.1 Campaigns (email, reusing `core.email`)
- **Objective**: campaign definition, audience segmentation query, send via
  `core.email`/`core.notifications` in bulk (background job).
- **Dependencies**: Phase 4 (CRM, for segmentation), Phase 5.2.
- **Scope**: `product/marketing/` campaign data model, service, API.
- **Tests**: segmentation query correctness; bulk-send job completes and
  records delivery status per recipient.
- **Security considerations**: unsubscribe/suppression list honored before
  every send — a hard gate, not a UI convenience (relevant to CAN-SPAM/GDPR
  obligations, flagged here as an architecture requirement, not a legal
  claim).
- **Acceptance criteria**: a segmented campaign sends correctly to its
  matching audience and respects suppression.
- **Rollback**: standard; a bad campaign can be paused mid-send (job-level
  cancellation).
- **Outcome**: not started.
- **Checkpoint**: review the suppression-list enforcement specifically.

### 6.2 SMS campaigns
- **Objective**: same as 6.1, over the Phase 5.3 SMS adapter.
- **Dependencies**: 6.1, 5.3.
- **Scope**: campaign type extension, reusing 6.1's segmentation/send
  infrastructure.
- **Tests**: mirrors 6.1.
- **Security considerations**: mirrors 6.1; SMS-specific opt-out (STOP
  keyword handling) is a hard requirement.
- **Acceptance criteria**: mirrors 6.1.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: confirm STOP-keyword handling before real sends.

### 6.3 Forms and lead capture
- **Objective**: tenant-defined forms, public submission endpoint, captured
  submissions create/update a CRM contact.
- **Dependencies**: Phase 4.1.
- **Scope**: form builder data model, public (unauthenticated, tenant
  identified by form token) submission API, CRM linkage.
- **Tests**: submission correctness; spam/abuse protection on the public
  endpoint (rate limiting, already available via `infra.ratelimit`,
  Category A).
- **Security considerations**: the public submission endpoint is the one
  place in this product deliberately reachable without authentication —
  scope it tightly (one form token → one tenant → one form, nothing else
  reachable from that token).
- **Acceptance criteria**: a public form submission correctly creates/
  updates a contact and is rate-limited.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: security review of the unauthenticated endpoint's scope
  before this ships — the one deliberately-open door in this product.

### 6.4 Landing pages and campaign templates
- **Objective**: reusable landing-page templates and campaign templates.
- **Dependencies**: 6.1, 6.3.
- **Scope**: template data model, service, API. Full visual page building is
  Phase 11 (Websites) — this phase covers template reuse for
  campaigns/forms specifically, not a general page builder.
- **Tests**: template CRUD, cloning correctness.
- **Security considerations**: none beyond inherited isolation.
- **Acceptance criteria**: a template can be created and reused across
  campaigns.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none — this phase's scope boundary against Phase 11 is
  the thing to confirm before starting either.

### 6.5 Tracking and segmentation refinement
- **Objective**: open/click tracking on email campaigns; segmentation
  criteria expanded to include engagement history.
- **Dependencies**: 6.1–6.4.
- **Scope**: tracking pixel/link-wrapping mechanism; segmentation query
  extension.
- **Tests**: tracking event correctness; segmentation query correctness
  against tracked engagement data.
- **Security considerations**: tracking data is tenant-owned and
  contact-linked — same isolation guarantee as everything else, no
  exception for analytics data.
- **Acceptance criteria**: opens/clicks are recorded and usable in
  segmentation.
- **Rollback**: standard; tracking can be disabled per-campaign without
  affecting send capability.
- **Outcome**: not started.
- **Checkpoint**: none.

---

## Phase 7 — Appointments

### 7.1 Calendars and availability
- **Objective**: staff calendars, availability rules, multiple calendars per
  tenant.
- **Dependencies**: Phase 3 (staff = tenant members).
- **Scope**: `product/appointments/` data model, availability computation
  service.
- **Tests**: availability computation correctness across time zones and
  overlapping rules.
- **Security considerations**: standard inherited isolation.
- **Acceptance criteria**: availability correctly reflects configured rules
  and existing bookings.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 7.2 Booking, rescheduling, cancellation
- **Objective**: a contact (or the public, via a booking link) books an
  available slot; reschedule/cancel flows.
- **Dependencies**: 7.1, Phase 4.1 (contact linkage).
- **Scope**: booking service, public booking API (tenant-scoped by link
  token, same pattern as Phase 6.3's form token).
- **Tests**: double-booking prevention under concurrent requests (a race
  condition test, not just a happy-path test); reschedule/cancel
  correctness.
- **Security considerations**: public booking endpoint scoped identically
  to Phase 6.3's form endpoint — one link token, one tenant, one calendar
  set, rate-limited.
- **Acceptance criteria**: concurrent booking attempts for the same slot
  never both succeed.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: review the concurrency test specifically — double-booking
  is a real-world trust failure, not just a bug.

### 7.3 Reminders (reuses `core.notifications`/`core.email`, Category A)
- **Objective**: scheduled reminder dispatch before an appointment.
- **Dependencies**: 7.2.
- **Scope**: `infra.jobs`-scheduled reminder job, sending via existing
  notification channels (email now; SMS once Phase 5.3 exists).
- **Tests**: reminder fires at the correct offset; a cancelled appointment's
  pending reminder is correctly suppressed.
- **Security considerations**: none beyond inherited channel security.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 7.4 Calendar provider sync (Category D)
- **Objective**: Google Calendar / Microsoft 365 two-way sync adapter.
- **Dependencies**: 7.1–7.3.
- **Scope**: `CalendarProvider` adapter (`docs/INTEGRATIONS.md`), OAuth
  credential handling via `infra.secrets`.
- **Tests**: sync correctness (a booking appears in the external calendar;
  an external change is reflected back, per whatever conflict-resolution
  rule is chosen at implementation time).
- **Security considerations**: OAuth token storage via `infra.secrets`/
  `core.crypto`, never plaintext; token refresh handled without exposing
  the token to any log line (mirrors `saas-os`'s own secret-redaction
  discipline).
- **Acceptance criteria**: matches the tests above.
- **Rollback**: disable the sync adapter; core booking functionality
  unaffected.
- **Outcome**: not started.
- **Checkpoint**: none beyond the OAuth-security review.

---

## Phase 8 — Telephony

### 8.1 Phone numbers and provider abstraction
- **Objective**: `TelephonyProvider` adapter (`docs/INTEGRATIONS.md`),
  number provisioning/assignment per tenant.
- **Dependencies**: Phase 2 (foundation), Phase 4.1 (contact linkage for
  caller-ID matching).
- **Scope**: adapter + number-management data model/service.
- **Tests**: a substitution test proving a second (fake) provider adapter
  satisfies the same Protocol — the leaky-abstraction proof, per
  `docs/INTEGRATIONS.md`'s stated pattern.
- **Security considerations**: provider credentials via `infra.secrets`.
- **Acceptance criteria**: a number can be provisioned and correctly
  attributed to a tenant.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 8.2 Inbound/outbound calls, routing
- **Objective**: call initiation, inbound call routing to the correct
  agent/queue, call state tracking.
- **Dependencies**: 8.1.
- **Scope**: call data model, routing service, provider webhook handling
  (signature-verified per `docs/INTEGRATIONS.md`).
- **Tests**: routing correctness under a defined routing policy; inbound
  webhook signature verification.
- **Security considerations**: mirrors Phase 5.3's webhook-security
  treatment.
- **Acceptance criteria**: an inbound call routes correctly and its state
  is tracked accurately.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 8.3 Call records, recordings, history
- **Objective**: call record storage, recording storage (where legally/
  configurably permitted), call history UI/API.
- **Dependencies**: 8.2; the object-storage capability
  (`docs/RESPONSIBILITY-MATRIX.md` "Object/file storage" row — build this
  as part of this subphase if not already built by an earlier phase needing
  it, e.g. Phase 2's branding-asset storage).
- **Scope**: call-record data model, recording storage wiring, retention
  policy hook (per-tenant configurable, since recording-consent rules vary
  by jurisdiction — flagged, not resolved, here).
- **Tests**: recording storage/retrieval correctness; retention-policy
  enforcement (a recording past its retention window is actually deleted,
  not just hidden).
- **Security considerations**: recordings are highly sensitive tenant data
  — field/object encryption at rest, tenant-namespaced storage paths (no
  shared bucket path across tenants, per `saas-os`
  `docs/MULTI-TENANCY.md` §4's storage-isolation principle applied here),
  strict access-control (who can listen to a recording is an RBAC
  permission, not implicit from general call-history access).
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard; recordings can be disabled per-tenant without
  affecting call functionality.
- **Outcome**: not started.
- **Checkpoint**: dedicated security review before recordings are enabled
  for any real tenant — this is one of the highest-sensitivity data types
  in this entire product.

### 8.4 Human handoff
- **Objective**: transfer an in-progress AI-handled call to a human agent.
- **Dependencies**: 8.2; Phase 9 (AI) — sequenced here as the natural
  completion of Telephony, implemented once Phase 9's AI call-handling
  exists to hand off *from*.
- **Scope**: handoff service + UI notification to the receiving agent.
- **Tests**: handoff preserves call context (the human agent sees what the
  AI already gathered, not a cold transfer).
- **Security considerations**: none beyond inherited call-record access
  control.
- **Acceptance criteria**: a simulated handoff preserves context correctly.
- **Rollback**: standard; AI calls can fall back to a defined default
  routing if handoff is disabled.
- **Outcome**: not started.
- **Checkpoint**: none.

---

## Phase 9 — AI

Builds on the AI Control Plane (Category A, already mature) — this phase is
almost entirely about registering this product's own tools, never about
building agent infrastructure.

9.1–9.3 deliver tool *definitions*. They deliberately stop short of
production execution: no tool is registered into the production registry,
and no tenant AI policy is persisted, so Data Authorization default-denies
for every real tenant. That is a documented decision, not a gap in those
subphases — **9.4** below is the follow-on that closes it, and
`docs/ROADMAP.md` 10.4A depends on 9.4 rather than on 9.1–9.3 alone.

### 9.1 Product tool registrations: CRM assistance
- **Objective**: register `control_plane` tools for lead qualification,
  suggested next actions, and conversation summarization, each scoped and
  RBAC-gated per `saas-os` `docs/AI-CONTROL-PLANE.md` §3.
- **Dependencies**: Phase 4 (CRM), Phase 5 (Conversations).
- **Scope**: `product/ai/tools/` — tool definitions only, each wrapping
  exactly one bounded action, at autonomy tier 0 or 1 per `saas-os`
  `docs/AI-CONTROL-PLANE.md` §5 (never tier 2/3 without a separate, later,
  evidence-based decision).
- **Tests**: mirrors `saas-os` roadmap Phase 7.1's own tool-registration
  test shape — a tool invokes correctly under permission, is denied without
  it, and every invocation (allowed or denied) is audit-logged.
- **Security considerations**: every tool touching tenant data passes
  through Data Authorization (ADR-0013) before any content reaches an
  external LLM provider — no exceptions, no "temporary" direct calls, per
  `docs/SECURITY-PRIVACY.md`.
- **Acceptance criteria**: each registered tool is independently testable
  and independently revocable, matching `saas-os`'s own stated tool
  properties.
- **Rollback**: disable the specific tool via `control_plane`'s existing
  kill-switch anticipation (`saas-os` `docs/AI-CONTROL-PLANE.md` §9) once
  available, or simply unregister it — no production risk from a disabled
  tool.
- **Outcome**: not started.
- **Checkpoint**: security review of the Data Authorization wiring
  specifically, before any tool goes live against real tenant data.

### 9.2 AI receptionist (voice)
- **Objective**: an AI agent handling inbound calls (Phase 8), using
  registered tools for call context, with human handoff (Phase 8.4) as the
  defined escalation path.
- **Dependencies**: 9.1, Phase 8.
- **Scope**: `product/ai/` voice-agent orchestration, STT/TTS provider
  adapter (Category D, `docs/INTEGRATIONS.md`).
- **Tests**: a simulated call is correctly handled or correctly escalated
  per a defined confidence/scope boundary (mirrors `saas-os`
  `docs/AI-CONTROL-PLANE.md` §4's stated pattern for autonomous customer
  support: "escalates outside a defined confidence/scope boundary").
- **Security considerations**: voice data is call-recording-adjacent
  sensitivity (§8.3) — same encryption/access-control discipline applies to
  any transcript this agent produces or retains.
- **Acceptance criteria**: matches the tests above; every AI action taken
  during the call is audit-logged with the same completeness
  `saas-os` `docs/SECURITY.md` §8 requires ("what did the AI do, on whose
  behalf, and was it approved").
- **Rollback**: disable the AI receptionist tool; calls fall back to
  ordinary human routing (Phase 8.2).
- **Outcome**: not started.
- **Checkpoint**: security + UX review before this is enabled for any real
  tenant's live phone number — this is the highest-blast-radius AI
  capability in the initial roadmap (real customers interacting with an
  autonomous agent on a live phone line).

### 9.3 AI sales assistant and suggested replies
- **Objective**: suggested-reply drafting inside Conversations, using
  registered tools scoped to the conversation being viewed.
- **Dependencies**: 9.1, Phase 5.
- **Scope**: tool registration + Conversations UI surface for suggestions
  (a human always sends; the AI drafts, never auto-sends at this phase —
  tier 0/1 only).
- **Tests**: mirrors 9.1.
- **Security considerations**: mirrors 9.1.
- **Acceptance criteria**: a drafted reply never sends without explicit
  human action.
- **Rollback**: disable the tool.
- **Outcome**: not started.
- **Checkpoint**: none beyond 9.1's standing review.

### 9.4 Production AI readiness (follow-on)
- **Objective**: make an approved AI capability genuinely executable for a
  real tenant through the existing Control Plane. **This is a follow-on
  production-readiness subphase, not a correction** — 9.1–9.3 are valid
  and complete for their own stated scope ("tool definitions only"), and
  every deferral below was an explicit, documented decision at the time,
  not an omission (`product/ai/__init__.py`, `product/ai/policy.py`).
- **Dependencies**: 9.1–9.3.
- **Scope**: the production-readiness gaps those modules disclose, at
  roadmap level only — a production LLM/voice **provider boundary and
  vendor selection** (no vendor is chosen here, and none is implied:
  `docs/RISKS-AND-OPEN-QUESTIONS.md` item 6 still owns that open
  question); **production tool registration** into
  `control_plane.orchestration.default_registry()`, which today registers
  no product tool deliberately, so a Fake-backed handler can never return
  synthetic output to a real tenant; a **persisted tenant AI policy**
  store behind `product.ai.policy.resolve_tenant_ai_policy()`, which today
  returns `None` for every tenant by design; and the resulting
  **production Data Authorization path** and policy/authorization
  configuration that a real tenant's approved capability actually passes
  through.
- **Tests**: a real tenant executes one approved capability end-to-end
  through the existing Control Plane — RBAC, autonomy tier, Data
  Authorization, and audit all exercised on the production path, not via
  a test-constructed registry and a test-constructed permissive policy
  (which is how every 9.1–9.3 test necessarily exercises the allow path
  today).
- **Security considerations**: the whole point of the current default-deny
  posture is that **no tenant data can reach an LLM provider through any
  tool in this codebase today**. Lifting that is the single most
  security-sensitive change in this phase and must not be done implicitly
  as a side effect of some other subphase's work.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: unregister the production tool(s) / remove the tenant
  policy — the default-deny posture is the safe resting state, and
  returning to it is always available.
- **Outcome**: not started.
- **Checkpoint**: dedicated security review before any real tenant data
  can reach a real provider — this is the gate that decision passes
  through, and it is reviewed on its own, never bundled.

---

## Phase 10 — Automation / Workflow Builder

The largest single product capability, per the brief. Sequenced after CRM,
Conversations, Marketing, Appointments, and Telephony exist, since those are
where most trigger sources come from — building the trigger library before
the triggers exist would be speculative.

### 10.1 Workflow durability spike and engine decision
- **Objective**: resolve `docs/ARCHITECTURE.md` §5's flagged open decision —
  evaluate a durable workflow engine (Temporal or equivalent) against this
  product's actual trigger/action catalog (informed by everything built in
  Phases 4–9), and record the decision as this product's own ADR.
- **Dependencies**: Phases 4–9 (informs the real trigger/action catalog this
  decision is made against).
- **Scope**: spike + ADR only, no production workflow code yet.
- **Tests**: n/a (a decision record, not code).
- **Security considerations**: if a third-party workflow engine is adopted,
  it becomes a new integration surface — credential handling via
  `infra.secrets`, tenant-scoping discipline extended to it explicitly in
  the ADR.
- **Acceptance criteria**: an ADR is written and reviewed with you before
  10.2 begins.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: **review the engine decision with you before committing**
  — this is a significant new infrastructure dependency, warranting the
  same scrutiny `saas-os` gives its own infrastructure ADRs.

### 10.2 Trigger/condition/action framework (single-step)
- **Objective**: the trigger library (new contact, form submitted,
  appointment booked/cancelled, pipeline stage changed, payment received,
  invoice overdue, email/SMS received, call completed, review received,
  scheduled time) wired to the Phase 2.2 event dispatcher; condition
  evaluation; single-step action execution on `infra.jobs`.
- **Dependencies**: 10.1; every phase that publishes an event this trigger
  library consumes (4.2's stage-change event is the first concrete
  consumer).
- **Scope**: `product/automation/` core engine, single-step actions only
  (send email, send SMS, create task, update contact, move opportunity,
  create appointment, send webhook, notify user).
- **Tests**: each trigger fires correctly from its source event; condition
  evaluation correctness; action execution correctness and idempotency
  (a retried job never double-executes a visible action like "send email"
  — reuses `core.idempotency`, Category A).
- **Security considerations**: an automation action must never be able to
  exceed the permissions of the tenant user who configured it — a
  workflow is not a privilege-escalation path. Test this adversarially
  (a workflow configured by a lower-privileged user cannot be used to
  perform an action that user couldn't perform directly).
- **Acceptance criteria**: the full trigger list above is implemented and
  tested; a configured automation runs correctly end-to-end for each
  trigger type.
- **Rollback**: a misbehaving automation can be paused/disabled per-tenant
  without affecting the rest of the platform.
- **Outcome**: not started.
- **Checkpoint**: review the privilege-escalation adversarial test
  specifically before this ships.

### 10.3 Multi-step, branching, delayed workflows
- **Objective**: extend 10.2 with the durable engine chosen in 10.1 —
  branching, delays ("wait 3 days"), wait-for-event semantics.
- **Dependencies**: 10.1, 10.2.
- **Scope**: durable workflow orchestration layer, invoking the same
  action library 10.2 already built (no action-logic duplication).
- **Tests**: a multi-day delayed workflow survives a process restart; a
  branching workflow takes the correct path under each condition; a
  cancelled workflow does not continue executing.
- **Security considerations**: mirrors 10.2's privilege-escalation test,
  extended to multi-step workflows specifically (a chain of individually
  low-privilege actions must not compose into an unauthorized outcome).
- **Acceptance criteria**: matches the tests above.
- **Rollback**: a bad workflow definition can be halted mid-execution;
  already-executed steps are not retroactively undone (each action's own
  rollback, if any, is that action's own concern, per action).
- **Outcome**: not started.
- **Checkpoint**: review the restart-survival test specifically — this is
  the entire reason the durable engine was adopted in 10.1.

### 10.3A Automation action registry / dependency inversion
- **Objective**: introduce a generic Automation action protocol/registry
  boundary so a domain-specific capability can register an action
  implementation **without Automation importing that domain**.
- **Dependencies**: 10.2, 10.3 (the action vocabulary and both execution
  paths this boundary has to keep working unchanged).
- **Why this exists**: discovered during the 10.4A implementation audit,
  not assumed. `pyproject.toml`'s own import-linter contract "Automation
  does not depend on any product module except CRM" lists `product.ai` in
  `forbidden_modules`, so `product.automation` cannot import
  `product.ai.invocation.invoke_product_ai_tool()` at all. A single
  narrow `automation -> ai` edge does not fix it either: `product.ai`
  itself imports `product.conversations` and `product.telephony` (for the
  summarize/suggest-reply and receptionist tools), both of which are
  *also* forbidden to Automation, so the edge would create forbidden
  indirect chains. Dependency inversion is the resolution that keeps
  every existing boundary intact.
- **Scope**: Automation owns the generic protocol and dispatch contract;
  a domain capability registers its implementation against that contract;
  Automation never imports the domain. Registration must be
  **deterministic**, and publish-time closed-vocabulary validation must
  stay deterministic and **independent of module import order** — a
  workflow definition must never validate differently depending on which
  modules happen to have been imported first. Existing 10.2/10.3 actions
  keep working unchanged, as do existing action execution, idempotency,
  and retry behaviour.
- **Explicitly not in scope**: no AI provider implementation; no tenant AI
  policy implementation; no accounting automation; no workflow-DSL
  redesign beyond the minimum the registry boundary itself requires; no
  SaaS-OS changes.
- **Boundaries that must survive unchanged**: no `product.automation ->
  product.ai` import; no broad relaxation of any import-linter contract;
  no `allow_indirect_imports`; no removal of Conversations/Telephony (or
  any other unrelated domain) from Automation's own forbidden list.
- **Tests**: existing 10.2 and 10.3 suites pass unchanged; publish-time
  validation of the closed vocabulary is proven order-independent;
  import-linter still reports every contract kept.
- **Security considerations**: the module-isolation boundary is itself a
  security control — it is what stops Automation acquiring read paths
  into domains it has no business reaching. This subphase exists
  specifically to extend Automation's capability *without* weakening it;
  any proposal that relaxes a contract instead of inverting the
  dependency is out of scope by definition.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard — the registry boundary is additive; removing a
  registered implementation returns the engine to its current vocabulary.
- **Outcome**: not started.
- **Checkpoint**: architecture review, recorded as its own ADR when the
  subphase is actually scheduled (referenced from here rather than
  written twice — this roadmap entry is not itself the decision record).

### 10.4 Automation extensions

Originally written as one phase covering both the AI-invocation action and
the Accounting-dependent actions. Split into **10.4A** and **10.4B**
because their dependencies are not the same: 10.4A is blocked on two
Automation/AI prerequisites, 10.4B on the accounting domain contract
Phase 15 has not yet created (`product/accounting/` is a placeholder with
no schema, no models, no services, and no migrations). The two halves are
sequenced independently; neither blocks the other, and they share no
prerequisite.

**Both halves are blocked, for unrelated reasons.** 10.4A was originally
recorded here as "ready to implement"; the 10.4A implementation audit
disproved that and found two concrete prerequisites — the import boundary
resolved by **10.3A**, and the production-AI capability resolved by
**9.4**. Neither was known when the split was written, and both are now
sequenced explicitly rather than absorbed into 10.4A's own scope.

```text
9.4 Production AI readiness
         |
         +--------------+
         v              |
10.3A Action registry / |
      dependency        |
      inversion         |
         |              |
         +------+-------+
                v
       10.4A AI Automation          10.4B Accounting Automation
                ^                              ^
                |                              |
       10.3 Durable Workflows         10.3 Durable Workflows
                                               ^
                                               |
                                      Phase 15 Mini Accounting
```

Neither subphase introduces a new execution substrate: both extend the
existing action vocabulary dispatched through
`product.automation.actions.execute_action()`, executed by 10.2's
synchronous path and 10.3's Temporal durable path (ADR-0007), with no
second executor, no second scheduler, and no second expression language.
10.3A changes *how* an action implementation reaches that vocabulary, not
the vocabulary's closed nature or either execution path.

### 10.4A AI automation action
- **Objective**: the brief-listed "invoke AI" action — a bounded workflow
  action that calls one already-registered Phase 9 product AI tool.
- **Dependencies**: 10.3 (durable execution); **10.3A** (the action
  registry/dependency-inversion boundary — without it Automation cannot
  reach the AI seam at all without breaking an import-linter contract);
  **9.4** (production AI readiness — without it an AI action cannot
  succeed for any real tenant, because no product tool is registered in
  the production registry and Data Authorization default-denies). Phase
  9.1–9.3 supply the tool definitions and authorization gates themselves
  and are complete.
- **Scope**: one additional action in 10.2/10.3's existing closed action
  vocabulary, reaching `product.ai.invocation.invoke_product_ai_tool()`
  **through 10.3A's registry boundary — never by importing `product.ai`
  from `product.automation` directly**, which the import-linter contract
  forbids. Bounded, typed action config naming which already-registered
  tool to invoke and which bounded inputs to pass; a bounded, typed
  result. No new engine work.
- **Tests**: mirrors 10.2, plus 10.3's own durable-path coverage —
  execution-time authorization (including permission revoked between
  workflow submission and the AI step, denied at execution time),
  cross-tenant denial, idempotency under duplicate activity invocation,
  permanent-vs-retryable error classification, and no sensitive AI input
  or output text entering Temporal workflow history (bounded identifiers
  and references only, per 10.3's own privacy discipline).
- **Security considerations**: **Automation must not become a second AI
  authorization system.** Tool authorization, Data Authorization,
  model/provider policy, autonomy tier, and the human-approval gate all
  remain owned by the AI Control Plane and `product/ai/`
  (`docs/RESPONSIBILITY-MATRIX.md` §"AI Control Plane"; `saas-os`
  `docs/AI-CONTROL-PLANE.md` §3/§5). This action passes the run's own
  execution identity through to those existing gates and honours their
  decision; it never caches an authorization decision made at workflow
  submission time, never calls an LLM/voice provider directly, and never
  bypasses the Data Authorization boundary. The action vocabulary stays
  closed: no arbitrary prompts, no arbitrary tool selection beyond the
  registered set, no arbitrary code execution — mirroring 10.2's own
  privilege-escalation rule (a workflow may never exceed the permissions
  of the user who configured it).
- **Acceptance criteria**: a workflow step invokes a registered product AI
  tool end-to-end on both the synchronous and durable paths, is denied at
  execution time when the configuring user's permission is revoked, and
  produces the same audit trail a direct tool invocation produces.
- **Rollback**: standard — the action can be removed from the vocabulary
  without affecting the rest of the engine.
- **Outcome**: not started — blocked on prerequisites (10.3A, 9.4). An
  earlier revision of this entry recorded it as "ready to implement";
  the 10.4A implementation audit disproved that and produced no code.
  A deny-only AI action — one wired correctly but guaranteed to fail for
  every real tenant until 9.4 lands — is explicitly **not** an acceptable
  way to close this subphase.
- **Checkpoint**: none beyond 10.2's standing security review, extended to
  the AI action specifically (the "no second AI authorization system" rule
  above is the thing to review), plus 10.3A's and 9.4's own checkpoints,
  which are cleared before this subphase begins rather than as part of it.

### 10.4B Accounting automation triggers/actions
- **Objective**: the brief-listed accounting triggers/actions — invoice
  overdue, payment received, create invoice, record payment.
- **Dependencies**: 10.3 (durable execution), **Phase 15 (Mini
  Accounting)**. Phase 15 is not started, so this subphase is blocked.
- **Scope**: additional trigger/action registrations only — no new engine
  work, reuses 10.2/10.3's mechanism. Automation consumes Accounting's own
  service/domain contract; it never defines accounting semantics, never
  touches `accounting.*` tables directly, and never duplicates Accounting's
  models or persistence.
- **Tests**: mirrors 10.2, plus 10.3's durable-path coverage, with
  particular weight on idempotency — a durable retry must never create a
  duplicate invoice, payment, or journal entry.
- **Security considerations**: mirrors 10.2, with particular attention to
  financial actions (`create invoice`, `record payment`) — these must
  reuse Accounting's own posting logic and its immutability discipline
  (`docs/ACCOUNTING-SCOPE.md`), never a parallel, automation-only path
  that bypasses it.
- **Acceptance criteria**: an invoice-overdue trigger and a payment-received
  trigger both work correctly against real Accounting data.
- **Rollback**: standard.
- **Outcome**: not started — blocked on Phase 15; deferred until Phase 15
  establishes the accounting domain contract. No accounting model,
  migration, API, action, trigger, or placeholder contract is to be created
  in Automation before then (`docs/ACCOUNTING-SCOPE.md`).
- **Checkpoint**: none beyond 10.2's standing security review, extended to
  the financial actions specifically.

---

## Phase 11 — Websites / Funnels

### 11.1 Page builder foundation
- **Objective**: a visual page builder (block-based), tenant-owned pages,
  published/draft states.
- **Dependencies**: Phase 2.3 (branding, applied to published pages), Phase
  6.4 (reuses the template concept, extended to full pages).
- **Scope**: `product/websites/` data model, builder API, rendering.
- **Tests**: published-page rendering correctness; draft/publish state
  transitions.
- **Security considerations**: published pages are public — the same
  unauthenticated-surface discipline as Phase 6.3/7.2's public endpoints
  applies (scoped strictly to what's meant to be public, rate-limited).
- **Acceptance criteria**: a page can be built, published, and rendered
  correctly under the tenant's own branding and (optionally) custom domain.
- **Rollback**: standard; a bad publish can be reverted to the prior
  version.
- **Outcome**: not started.
- **Checkpoint**: none beyond the public-surface security review.

### 11.2 Funnels (multi-page flows) and lead capture integration
- **Objective**: chain pages into a funnel; wire page-level forms into
  Phase 6.3's lead-capture mechanism.
- **Dependencies**: 11.1, Phase 6.3.
- **Scope**: funnel data model, form embedding.
- **Tests**: funnel-step correctness; lead-capture correctness (reuses
  6.3's tests, applied to page-embedded forms).
- **Security considerations**: none beyond 11.1's inherited discipline.
- **Acceptance criteria**: a multi-step funnel correctly captures a lead
  into CRM.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 11.3 Website-level tracking and analytics
- **Objective**: page-view/conversion tracking, feeding Phase 16's
  reporting.
- **Dependencies**: 11.1, 11.2, Phase 6.5 (reuses the tracking mechanism
  built there).
- **Scope**: tracking wiring, no new tracking mechanism.
- **Tests**: mirrors 6.5.
- **Security considerations**: mirrors 6.5.
- **Acceptance criteria**: page views/conversions are correctly attributed
  and available to reporting.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

---

## Phase 12 — Reputation Management

### 12.1 Review requests and tracking
- **Objective**: trigger a review request (manually or via Automation),
  track its status.
- **Dependencies**: Phase 10 (automation trigger integration), Phase 5
  (send mechanism).
- **Scope**: `product/reputation/` data model, service.
- **Tests**: request lifecycle correctness.
- **Security considerations**: none beyond inherited isolation.
- **Acceptance criteria**: a review request can be triggered and its status
  tracked.
- **Rollback**: standard.
- **Outcome**: implemented (domain/service/API layer) --
  `product/reputation/models.py`, `review_requests.py`, `reviews.py`,
  `permissions.py`, `event_handlers.py`, `purge.py`, `routes.py`;
  migrations 0044-0046. Manual triggering works end-to-end (synchronous
  send via `core.email`, status tracked through
  `pending`/`sent`/`failed`/`cancelled`/`fulfilled`). The Automation
  trigger-integration half of this phase's own Dependencies line is
  **deferred, not implemented** -- see `docs/ADR/0010
  -reputation-depends-on-crm.md`'s "Deferred: Automation Integration"
  section; `reputation.review_request.created/.sent/.failed` are
  published via the existing event dispatcher so that integration can be
  added later without a Reputation-side change. `product/api/main.py`
  wiring (router mount, purge-participant registration, event-handler
  import) is also deferred -- an explicitly protected, pre-existing
  uncommitted local change in that file made it out of this phase's
  scope; see `product/reputation/__init__.py`'s own module docstring for
  the exact follow-up diff. Covered by `tests/reputation/` (unit +
  integration against disposable PostgreSQL; see this phase's own
  implementation/audit report for exact counts).
- **Checkpoint**: none.

### 12.2 Review platform integrations (Category D)
- **Objective**: adapters for the review platforms the brief names (Google
  Business Profile, Facebook, others as prioritized).
- **Dependencies**: 12.1.
- **Scope**: one adapter per provider, `docs/INTEGRATIONS.md` pattern.
- **Tests**: substitution test per provider; a review pulled from a
  provider is correctly attributed to the right tenant/location.
- **Security considerations**: provider OAuth credentials via
  `infra.secrets`/`core.crypto`.
- **Acceptance criteria**: at least one real provider integration works
  end-to-end.
- **Rollback**: disable the specific provider adapter.
- **Outcome**: deliberately deferred, not implemented -- the
  provider-neutral interface itself is established
  (`product/reputation/providers.py::ReviewProvider`/
  `resolve_provider()`, plus `FakeReviewProvider` for tests), but no real
  Google Business Profile/Facebook adapter exists: no vendor has actually
  been committed to (mirrors Phase 9.4's own "no vendor is chosen here"
  treatment), and building one now would mean inventing credentials that
  do not exist. `resolve_provider()` returns `None` for every provider
  name today, by design. A tenant can record a review manually
  (`provider='manual'`, the only value the DB `CheckConstraint` accepts
  in this phase) and respond to it; posting a response to a real,
  non-`'manual'` review is implemented and unit-tested
  (`product/reputation/responses.py::_ensure_posted_externally()`) but
  unreachable through the full stack until a real Phase 12.2 adapter is
  actually built, since no such row can exist yet.
- **Checkpoint**: none.

### 12.3 Review response and automation hooks
- **Objective**: respond to a review from within the product; automation
  trigger on new review received (extends Phase 10's trigger library).
- **Dependencies**: 12.2, Phase 10.2.
- **Scope**: response API wired to each provider adapter; trigger
  registration.
- **Tests**: response correctness per provider; trigger firing correctness.
- **Security considerations**: none beyond 12.2's inherited discipline.
- **Acceptance criteria**: a response posts correctly to the real provider
  in a test environment.
- **Rollback**: standard.
- **Outcome**: partially implemented -- responding to a review from
  within the product is fully implemented
  (`product/reputation/responses.py`, `routes.py`'s
  `/reviews/{review_id}/responses`) and tested for the only provider this
  phase can produce (`'manual'`). "Automation trigger on new review
  received" is **deferred, not implemented** -- see `docs/ADR/0010
  -reputation-depends-on-crm.md`'s "Deferred: Automation Integration"
  section (extending `product/automation/`'s own closed trigger
  vocabulary is a change to Automation's own files, out of this phase's
  scope); `reputation.review.received`/`reputation.review.responded` are
  published via the existing event dispatcher so that integration can be
  added later without a Reputation-side change. "Response posts correctly
  to the real provider" is not demonstrated end-to-end (12.2's own real
  provider is deferred) -- proven instead at the unit level for the
  provider-routing decision itself.
- **Checkpoint**: none.

---

## Phase 13 — SaaS Resale / Billing

Maps mostly onto `core.billing` (Category A) plus the reseller-specific UI
(Category C) per `docs/RESPONSIBILITY-MATRIX.md`.

### 13.1 Agency subscription (this product's own SaaS revenue)
- **Objective**: agency onboarding subscribes to a plan via `core.billing`,
  unchanged mechanism.
- **Dependencies**: Phase 3.1 (agency tenant exists).
- **Scope**: onboarding UI/API wrapping `core.billing.subscribe()` /
  `upgrade_subscription()` / `cancel_subscription()`.
- **Tests**: subscription lifecycle correctness (already covered by
  `saas-os`'s own test suite for the underlying mechanism; this phase's
  tests confirm the product UI wraps it correctly).
- **Security considerations**: payment-provider credential handling is
  already `core.billing`'s own concern (Stripe adapter) — no new secret
  surface here.
- **Acceptance criteria**: an agency can subscribe, upgrade, downgrade,
  cancel, through this product's own UI.
- **Rollback**: standard.
- **Outcome**: implemented (backend service/API layer; no UI in this
  backend-only phase) -- generalized beyond "agency" per
  `docs/ADR/0012-resale-billing-ownership-model.md`'s own "Plan ownership"
  section: `product/billing/subscriptions.py::create_platform_subscription()`
  wraps `core.billing.subscribe_idempotent()`/`upgrade_subscription()`/
  `cancel_subscription()` identically for any tenant subscribing directly
  to a global platform plan (an agency or a root "Direct Platform
  Client" -- nothing in `core.billing` or this wrapper distinguishes the
  two). Requires a caller-supplied idempotency key (`docs/ADR/0012-...`'s
  own "Idempotency" section). `GET /v1/billing/plans` lists the global
  catalog read-only; plan *creation* remains an ops/seeding concern, not
  exposed via this product's API (`docs/ADR/0012-...`'s own "Plan
  ownership" section). `product/api/main.py` wiring (router mount, purge
  registration, event-handler import) is deferred -- see
  `product/billing/__init__.py`'s own module docstring for the exact
  follow-up diff.
- **Checkpoint**: none — thin wrapper phase.

### 13.2 Agency-defined resale plans for clients
- **Objective**: an agency defines its own plan tiers to offer its clients,
  mapped onto `core.billing`/`core.usage` entitlement primitives.
- **Dependencies**: 13.1, Phase 3 (client tenants).
- **Scope**: `product/billing/` reseller-plan data model and service —
  entirely product-specific business logic layered over Category-A
  mechanics.
- **Tests**: an agency-defined plan correctly maps to entitlement checks a
  client's usage is evaluated against.
- **Security considerations**: an agency must not be able to define a plan
  that grants a client more platform-level entitlement than the agency's
  own subscription actually has (a resale-tier ceiling check).
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: implemented -- `product/billing/models.py::ResalePlan`
  (the only new product-owned table this phase introduces,
  `docs/ADR/0012-resale-billing-ownership-model.md`), `resale_plans.py`
  (CRUD + the resale-tier ceiling check against `core.billing
  .get_entitlements()`, live and hierarchy-aware). Commercial terms
  (price/entitlements) are immutable after creation -- `core.billing`
  exposes no `update_plan()` to propagate a change onto existing
  subscribers, so this phase does not half-support one (see
  `resale_plans.py`'s own module docstring). Migration `0047
  _billing_resale_plans` (RLS enabled+forced, verified against a
  disposable PostgreSQL bootstrap). Covered by `tests/billing
  /test_resale_plans_integration.py` -- the ceiling check
  (numeric/boolean/absent-key/unsupported-type cases), tenant isolation,
  owner/member authorization, and suspended-tenant denial; see 13.3's own
  Outcome for the full `tests/billing/` count across all three subphases.
- **Checkpoint**: review the resale-tier ceiling check specifically — this
  is the one place a bug becomes a revenue-integrity problem.

### 13.3 Client-facing billing/onboarding
- **Objective**: a client sees and manages its own resale-plan subscription
  (trial, upgrade, downgrade, cancellation) through this product's UI.
- **Dependencies**: 13.2.
- **Scope**: client-facing billing UI/API.
- **Tests**: mirrors 13.1's lifecycle tests, from the client's perspective.
- **Security considerations**: a client must never see or affect another
  client's billing state, including siblings under the same agency —
  standard tenant isolation, tested explicitly for this specific UI
  surface.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: implemented (backend service/API layer; no UI in this
  backend-only phase) -- `product/billing/subscriptions.py
  ::create_resale_subscription()`/`change_subscription_plan()`/
  `cancel_subscription()`/`get_effective_entitlements()`. A client's
  subscription to an ancestor's `ResalePlan` validates that plan actually
  belongs to one of the client's own ancestors
  (`core.tenancy.get_ancestor_chain()`) before subscribing -- cross-agency
  resale plans are rejected. Tenant isolation between sibling clients
  under the same agency, and an agency owner's pre-existing `SUBTREE`
  role (`product/agency/provisioning.py::provision_agency()`) correctly
  administering (create/read/cancel) a descendant client's subscription
  with zero additional authorization code, are both explicitly tested.
  `product.billing` total: 23 unit tests, 31 integration tests
  (`tests/billing/`), all passing.
- **Checkpoint**: none beyond the isolation test.

---

## Phase 14 — Templates / Snapshots

### 14.1 Snapshot definition and export
- **Objective**: define a snapshot as a named bundle of configuration
  (pipelines, forms, campaigns, automation, calendars, page templates,
  email/SMS templates, settings) belonging to one tenant.
- **Dependencies**: Phases 4, 6, 7, 10, 11 (the modules whose configuration
  is being bundled must already exist).
- **Scope**: `product/templates/` snapshot data model + export service.
- **Tests**: a snapshot correctly captures every declared configuration
  type without capturing tenant business data (contacts, conversations,
  financial records are never part of a snapshot — configuration only).
- **Security considerations**: a snapshot must never leak tenant-specific
  secrets (e.g. a client's own integration credentials) — explicitly
  excluded from the export, tested.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: review the secret-exclusion test specifically before
  import/clone (14.2) is built on top of export.

### 14.2 Snapshot import/clone
- **Objective**: apply a snapshot to a new or existing tenant, preserving
  tenant isolation throughout (every cloned entity is created fresh, scoped
  to the target tenant — never a cross-tenant reference surviving the
  clone).
- **Dependencies**: 14.1.
- **Scope**: import service, ID-remapping logic (every foreign key inside
  the snapshot must be remapped to the target tenant's own newly-created
  entities, never left pointing at the source tenant's data).
- **Tests**: a cloned snapshot is fully self-contained in the target
  tenant — no dangling reference back to the source tenant, verified by an
  adversarial test attempting exactly that.
- **Security considerations**: this is the second highest-risk isolation
  surface in this roadmap after Phase 3's delegation/deny (a cloning bug
  could leak one tenant's configuration structure, or worse, a live
  reference, into another tenant).
- **Acceptance criteria**: matches the tests above.
- **Rollback**: a failed/partial clone leaves no partially-created data —
  the import is transactional, all-or-nothing.
- **Outcome**: not started.
- **Checkpoint**: dedicated review of the ID-remapping logic and its
  adversarial test before this ships to any agency managing multiple
  clients.

---

## Phase 15 — Mini Accounting

Follows `docs/ACCOUNTING-SCOPE.md` exactly. Sequenced late because it is the
most novel, most regulation-sensitive module, and benefits from the product
event dispatcher (Phase 2.2) and automation (Phase 10) already existing to
integrate with.

### 15.1 Chart of accounts, journal entries, ledger, periods
- **Objective**: core bookkeeping primitives per `docs/ACCOUNTING-SCOPE.md`
  §"In Scope."
- **Dependencies**: Phase 2 (foundation — `Money` value object,
  `core.crypto` for sensitive fields).
- **Scope**: `product/accounting/` schema (`accounting.*`), immutable
  posted-journal-entry discipline built explicitly (never reused from
  `core.audit_log`, which is additive, not a substitute — per
  `docs/SECURITY-PRIVACY.md`).
- **Tests**: double-entry correctness (debits always equal credits); posted
  entries are provably immutable (an attempted UPDATE/DELETE on a posted
  entry is rejected at the data-access layer, not just by convention —
  mirrors the rigor `saas-os`'s own Phase 3.4 audit-log immutability test
  applied to `core.audit_log`).
- **Security considerations**: dedicated review — this is the financial
  system of record; the immutability guarantee is the single most
  important property of this subphase.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: this is foundational to every later accounting subphase —
  rollback after any real posted data exists requires a data-migration-aware
  plan, mirroring `saas-os`'s own treatment of its Phase 3.1 tenancy
  foundation.
- **Outcome**: not started.
- **Checkpoint**: dedicated security/correctness review — do not proceed to
  15.2 until the immutability test is proven, not merely written.

### 15.2 Customers and sales invoices
- **Objective**: tenant's own customers, invoices, invoice lines, VAT
  fields, sequential numbering, status, payments, outstanding balances.
- **Dependencies**: 15.1.
- **Scope**: matches `docs/ACCOUNTING-SCOPE.md` §"Sales." Explicit,
  named non-conflation with `core.billing`
  (`docs/ACCOUNTING-SCOPE.md` §"The One Mistake to Avoid") — verified by
  review, not just stated.
- **Tests**: invoice numbering has no gaps under concurrent invoice
  creation (a race-condition test, same discipline as Phase 7.2's
  double-booking test); VAT calculation correctness for each configured
  rate.
- **Security considerations**: `core.idempotency` applied to
  payment-webhook processing against invoices, per
  `docs/ACCOUNTING-SCOPE.md`.
- **Acceptance criteria**: matches the tests above; a hand-written sample
  invoice validates correctly end-to-end (create → send → mark paid →
  balance reflects correctly).
- **Rollback**: standard, subject to 15.1's data-migration caveat once real
  invoices exist.
- **Outcome**: not started.
- **Checkpoint**: the invoice-numbering concurrency test specifically —
  this is a legal requirement (gapless sequential numbering), not a nice
  -to-have.

### 15.3 Credit notes
- **Objective**: credit notes referencing an original invoice, preserving
  its immutability.
- **Dependencies**: 15.2.
- **Scope**: matches `docs/ACCOUNTING-SCOPE.md` §"Sales."
- **Tests**: a credit note never mutates the original invoice; the
  reference is always resolvable.
- **Security considerations**: none beyond 15.2's inherited discipline.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond 15.2's standing review.

### 15.4 Suppliers, purchases, expenses
- **Objective**: matches `docs/ACCOUNTING-SCOPE.md` §"Purchases."
- **Dependencies**: 15.1.
- **Scope**: supplier/expense data model, service, API.
- **Tests**: expense categorization correctness; ledger posting
  correctness.
- **Security considerations**: none beyond 15.1's inherited discipline.
- **Acceptance criteria**: an expense posts correctly to the ledger.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 15.5 Banking — manual import and reconciliation
- **Objective**: matches `docs/ACCOUNTING-SCOPE.md` §"Banking" and §"Bank
  Integration Phasing" step 1 (manual CSV/MT940 import only).
- **Dependencies**: 15.2, 15.4.
- **Scope**: import service, matching algorithm, reconciliation workflow.
- **Tests**: matching-algorithm correctness against a realistic sample
  statement; reconciliation state transitions.
- **Security considerations**: bank statement data is sensitive financial
  data — same encryption/isolation discipline as everything else in this
  module.
- **Acceptance criteria**: a sample bank statement imports and matches
  correctly against open invoices/expenses.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond 15.1's standing review.

### 15.6 Reports — P&L, balance sheet, VAT summary, GL, AR/AP, cash
- **Objective**: matches `docs/ACCOUNTING-SCOPE.md` §"Reports," including
  export (CSV/PDF).
- **Dependencies**: 15.1–15.5.
- **Scope**: report-generation service, export.
- **Tests**: report correctness against a known, hand-verified sample
  dataset (a golden-output test, not just "it renders").
- **Security considerations**: report generation must respect the same
  tenant isolation as everything else — no cross-tenant data in a
  hierarchy-aware rollup unless explicitly, deliberately built (and this
  roadmap does not build automatic multi-entity consolidation, per
  `docs/ACCOUNTING-SCOPE.md`'s explicit out-of-scope list).
- **Acceptance criteria**: matches the golden-output test; **the VAT
  summary report's exact box structure has accountant sign-off before this
  subphase is considered complete**, per `docs/ACCOUNTING-SCOPE.md`.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: **accountant/legal review required before this subphase
  is marked complete** — not an engineering-only sign-off.

### 15.7 Retention and tenant-purge participation
- **Objective**: resolve the retention-vs-erasure tension
  (`docs/ACCOUNTING-SCOPE.md` §"Dutch Market Considerations" retention
  bullet, `docs/SECURITY-PRIVACY.md`) by registering `product/accounting/`'s
  `TenantPurgeParticipant` with the correct, deliberately-chosen behavior
  (anonymize, not delete, for records inside the legal retention window).
- **Dependencies**: 15.1–15.6.
- **Scope**: purge-participant implementation.
- **Tests**: mirrors `saas-os`'s own purge-participant test discipline
  (`saas-os` `docs/MULTI-TENANCY.md` §6) — idempotent, tenant-scoped,
  fail-closed.
- **Security considerations**: this is the resolution of a genuine legal
  tension flagged in Phase 0 — do not implement without the same
  legal-review checkpoint as 15.6.
- **Acceptance criteria**: a tenant purge correctly anonymizes (not
  deletes) in-retention-window accounting records, verified by test.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: **legal review of the chosen retention behavior required**
  before this ships — this closes out Phase 15.

---

## Phase 16 — Reporting

### 16.1 Operational analytics
- **Objective**: leads, conversion, pipeline, appointments, campaigns,
  communication dashboards — reading CRM/Marketing/Conversations/
  Appointments data.
- **Dependencies**: Phases 4–8.
- **Scope**: `product/reporting/` operational-analytics service, dashboard
  API.
- **Tests**: report correctness against known sample data.
- **Security considerations**: standard inherited isolation.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 16.2 Accounting reports surfacing
- **Objective**: surface Phase 15.6's accounting reports in this product's
  broader reporting UI, explicitly kept as a distinct section/data source
  from operational analytics (`docs/RESPONSIBILITY-MATRIX.md`'s explicit
  "never conflated" requirement).
- **Dependencies**: 16.1, Phase 15.6.
- **Scope**: UI/navigation wiring only — no new report logic.
- **Tests**: none beyond confirming the two report families remain visibly,
  structurally distinct in the UI/API (a review criterion, not just a
  test).
- **Security considerations**: none beyond what 15.6 already established.
- **Acceptance criteria**: an accounting report and an operational report
  are reachable from clearly separate UI sections.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

### 16.3 Usage/entitlement reporting
- **Objective**: surface `core.usage`/`core.billing` data (Category A) in
  this product's reporting UI — a thin presentation layer.
- **Dependencies**: 16.1, Phase 13.
- **Scope**: UI wiring only.
- **Tests**: correctness against `core.usage`'s own aggregation output.
- **Security considerations**: none beyond inherited.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none.

---

## Phase 17 — Integrations Hardening

By this phase, most integrations already exist per their owning module's
phase (SMS in Phase 5, telephony in Phase 8, etc.). This phase formalizes
the adapter layer as a first-class, consistently-tested surface rather than
scattered per-module adapters.

### 17.1 Adapter consistency audit
- **Objective**: audit every `product/integrations/` adapter built so far
  against `docs/INTEGRATIONS.md`'s pattern (Protocol, substitution test,
  credential handling via `infra.secrets`, webhook signature verification
  where applicable) — fix any that drifted.
- **Dependencies**: every phase that introduced an adapter (5, 7.4, 8, 12).
- **Scope**: audit + remediation, no new integrations.
- **Tests**: every adapter has a passing substitution test.
- **Security considerations**: this phase exists specifically to catch
  security-relevant drift (e.g. a webhook handler that skipped signature
  verification under deadline pressure earlier in the roadmap).
- **Acceptance criteria**: every adapter passes the audit checklist.
- **Rollback**: n/a — audit/fix phase.
- **Outcome**: not started.
- **Checkpoint**: review the audit findings with you before Phase 18.

### 17.2 New integrations backlog (as prioritized)
- **Objective**: any integration named in the brief not yet built by this
  point (payment collection for tenant invoicing, bank AIS provider,
  analytics provider, domain/DNS provider) — prioritized against real
  demand, not built speculatively.
- **Dependencies**: 17.1; the owning module's phase.
- **Scope**: one adapter at a time, `docs/INTEGRATIONS.md` pattern.
- **Tests**: substitution test per adapter.
- **Security considerations**: per-adapter, mirrors the pattern established
  throughout this roadmap.
- **Acceptance criteria**: per-adapter.
- **Rollback**: per-adapter — disabling one never affects another.
- **Outcome**: not started.
- **Checkpoint**: reviewed per-adapter as each is prioritized, not as one
  bundled decision.

---

## Phase 18 — Production Hardening & Dutch Compliance Review

### 18.1 Cross-cutting security review
- **Objective**: a full review of every isolation/authorization boundary
  this roadmap introduced, against `docs/SECURITY-PRIVACY.md`, before any
  real tenant's production data flows through this product.
- **Dependencies**: every prior phase.
- **Scope**: review, not new features. Findings become their own scoped
  fix phases, never bundled into this checkpoint's own sign-off.
- **Tests**: the adversarial test suites flagged throughout this roadmap
  (Phase 3.3, 3.4, 4.1, 6.3, 7.2, 9.2, 10.2, 14.2, 15.1) are re-run
  together as one regression pass.
- **Security considerations**: this is the security consideration.
- **Acceptance criteria**: every flagged adversarial test passes; no open
  finding above low severity.
- **Rollback**: n/a — review phase.
- **Outcome**: not started.
- **Checkpoint**: sign-off required before production launch.

### 18.2 Dutch legal/compliance review
- **Objective**: the accountant/legal review flagged throughout
  `docs/ACCOUNTING-SCOPE.md` (VAT box structure, invoice-numbering
  compliance, retention-vs-erasure resolution, GDPR posture) performed by
  a qualified professional, not assumed by this roadmap at any point.
- **Dependencies**: Phase 15 complete.
- **Scope**: review, not code — any finding becomes a scoped fix.
- **Tests**: n/a.
- **Security considerations**: this review is itself the control.
- **Acceptance criteria**: a qualified reviewer's sign-off, on record.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: **required before this product's accounting module is
  offered to any real Dutch tenant** — this is a hard gate, not a
  recommendation.

### 18.3 Load/operational readiness
- **Objective**: mirror `saas-os`'s own deployment-hardening discipline
  (`saas-os` `docs/DEPLOYMENT-ARCHITECTURE.md`) for this product's own
  production topology, backup/restore drill (extending `saas-os`'s own
  `infra/db/backup` operational pattern to this product's own schemas),
  and observability dashboards.
- **Dependencies**: 18.1.
- **Scope**: operational readiness, not new features.
- **Tests**: a real backup/restore drill, per `saas-os`'s own documented
  precedent (`saas-os` `docs/BACKUP-RESTORE.md`).
- **Security considerations**: same as `saas-os`'s own — non-root
  containers, no secret in image layers, firewall posture matching
  `saas-os`'s documented production topology.
- **Acceptance criteria**: a real restore drill succeeds.
- **Rollback**: n/a — this phase's entire purpose is proving rollback/
  recovery works.
- **Outcome**: not started.
- **Checkpoint**: sign-off required before production launch, alongside
  18.1 and 18.2.

---

## Phase 19 — Prospecting & Lead Intelligence

Status: PROPOSED, roadmap/design only — no subphase below is implemented.
This phase and Phase 20 are appended after Phase 18, not inserted before it:
Phase 18 remains the production/compliance gate for everything in Phases
1–18 (CRM, Conversations, Marketing, Accounting, ...), and that gate is not
reopened or diluted by adding more roadmap scope after it. Prospecting is a
new, later capability that itself depends on CRM (4), the AI Control Plane
tool-registration pattern (9), and the Automation engine (10) already
existing, and carries its own data-governance/legal review gate (19.1, and
Phase 20's cost/consent controls) analogous to, but distinct from, Phase
18's Dutch/accounting-specific one. Existing phase numbers are unchanged;
nothing here is renumbered.

External prospect discovery and lead intelligence, functionally comparable
in scope to modern "find and qualify local businesses" prospecting tooling,
designed from the outset as **provider-agnostic and country-agnostic** —
Netherlands, Belgium, Morocco, and France are the initial target countries,
with the architecture required to support additional countries later without
a redesign. Per `docs/RESPONSIBILITY-MATRIX.md`'s categorization discipline:
the prospecting domain model and orchestration are Category C
(product-specific); every external data source is Category D, isolated
behind a provider adapter, never hardcoded; the CRM (Phase 4) remains the
one system of record for Company/Contact/Opportunity — Phase 19 never
creates a second CRM.

### 19.1 Provider & Data-Licensing Spike

- **Objective**: before any production provider integration, investigate
  and document, per candidate provider: country/geographic coverage,
  API capabilities, pricing/cost model, rate limits, data freshness,
  commercial-use rights, retention/storage restrictions, attribution
  requirements, redistribution restrictions, personal-data implications,
  GDPR/privacy implications, provider-specific acceptable-use restrictions,
  business-data vs. contact-data coverage, registry-data availability, and
  enrichment capabilities. Candidate categories: (1) global/local business
  discovery (e.g. Google Places/Maps Platform, DataForSEO, Outscraper),
  (2) business directory providers, (3) licensed B2B/company-data providers
  (e.g. Apollo, Cognism, People Data Labs), (4) contact enrichment
  providers, (5) official/registry data providers (e.g. Dutch KVK, Moroccan
  OMPIC/ICE/RC ecosystem, Belgian/French equivalents), (6) customer-owned
  imports, (7) audit/website-intelligence providers. These are candidates
  to evaluate, **not approved dependencies** — no vendor is selected by this
  spike; vendor selection is a later, phase-level decision per
  `docs/INTEGRATIONS.md`'s closing statement, made against each provider's
  *current* terms at that time, not the terms found during this spike.
- **Dependencies**: Phase 18 (this product is production-hardened and
  compliance-reviewed before a new externally-sourced-data capability is
  designed on top of it); Phase 4 (CRM, the eventual handoff target).
- **Scope**: research and a written findings document per provider category
  (per-country coverage matrix, licensing/compliance matrix). No code, no
  provider account/credential is provisioned, no adapter is written.
- **Tests**: n/a (a research/documentation subphase, mirroring Phase 10.1's
  and Phase 0's own "spike + decision record, no code" shape).
- **Security considerations**: none yet (no integration exists); the
  findings document is itself the input to 19.3's provider-abstraction
  design and to the compliance requirements in this phase's own "Compliance
  and data governance" scope below.
- **Acceptance criteria**: a findings document exists covering every
  category and country above, explicitly flags which providers have
  acceptable-use terms incompatible with this product's intended use (e.g.
  no-storage, no-redistribution, no-commercial-enrichment clauses), and is
  reviewed with you before 19.2–19.10 are treated as more than a paper
  design.
- **Rollback**: n/a — no system exists yet from this subphase.
- **Outcome**: not started.
- **Checkpoint**: **STOP HERE.** Provider terms must be re-verified as
  current, not assumed from this spike's findings, at the point any
  provider adapter is actually implemented (a later, not-yet-scheduled
  phase) — terms and pricing drift over time, and this spike's findings are
  a snapshot, not a standing guarantee.

### 19.2 Prospecting Domain

- **Objective**: define, in writing, the domain concepts this capability
  will eventually need — `Prospect`, `ProspectCandidate`, `ProspectSearch`,
  `ProspectSource`, `ProspectSignal`, `ProspectEnrichment`, `ProspectAudit`,
  `ProspectQualification`, `ProspectAssignment` — and the distinction
  between an **external candidate** (raw, unverified, provider-sourced),
  a **normalized prospect** (deduplicated, provider-agnostic, this
  product's own representation), an **existing CRM company/contact**
  (Phase 4.1's system of record), and an **opportunity** (Phase 4.2). The
  CRM remains the system of record for CRM entities; this phase does not
  create a second CRM, a second contact model, or a second company model.
- **Dependencies**: 19.1 (informs what a `ProspectSource`/`ProspectSignal`
  actually needs to represent, given real provider shapes found there);
  Phase 4.1–4.2 (the CRM entities this domain hands off into).
- **Scope**: a domain-model design document (`product/prospecting/`'s
  future module boundary, per `docs/ARCHITECTURE.md` §2.1's pattern) — no
  SQLAlchemy models, no migration, no schema.
- **Tests**: n/a (design document).
- **Security considerations**: the design must state, per concept, whether
  it can hold personal data (a `ProspectCandidate`'s contact fields, most
  plausibly) — flagged here for 19.6's provenance/retention design, not
  resolved here.
- **Acceptance criteria**: every concept above has a one-paragraph
  definition and an explicit statement of what it is not (e.g. "a
  `Prospect` is not a `crm.contacts` row and never bypasses 19.9's handoff
  step to become one").
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: review the external-candidate/normalized-prospect/CRM-
  entity boundary specifically before 19.3 assumes it.

### 19.3 Provider Abstraction

- **Objective**: define a provider-agnostic architecture distinguishing
  `DiscoveryProvider`, `EnrichmentProvider`, `RegistryProvider`, and
  `AuditProvider` capabilities, following the exact Protocol + adapter
  pattern already established by `docs/INTEGRATIONS.md` and demonstrated
  in `saas-os` for `core.billing`/`core.email`. No single provider is
  required to implement every capability — a discovery-only provider and a
  registry-only provider can both be plugged in independently.
- **Dependencies**: 19.1 (real provider capability shapes), 19.2 (the
  domain concepts each Protocol operates on).
- **Scope**: `product/integrations/prospecting/` design (Protocol
  definitions, one design doc per capability), per
  `docs/INTEGRATIONS.md`'s existing `provider.py` / `<name>_provider.py` /
  `errors.py` layout — design only, no implementation.
- **Tests**: n/a at design time; the design must state that a substitution
  test (a fake adapter satisfying the same Protocol) will be required for
  every future concrete adapter, per `docs/INTEGRATIONS.md`'s standing
  rule.
- **Security considerations**: adapters must isolate provider API
  contracts, authentication, rate limits, provider-specific fields,
  provider-specific retention rules, provider-specific licensing
  restrictions, and provider-specific errors — the domain/application layer
  must not depend directly on a specific vendor's types, exactly as
  `docs/INTEGRATIONS.md` already requires for every other Category D
  integration.
- **Acceptance criteria**: each of the four Protocols is defined with a
  minimal method signature set and an explicit statement of what a
  provider-specific adapter owns vs. what the domain layer owns.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: review that no capability design silently assumes a
  single vendor's field shape (e.g. assuming every provider returns a KVK
  number) — this is the specific failure mode 19.4 exists to prevent.

### 19.4 International / Country-Aware Prospecting

- **Objective**: ensure the architecture supports multiple countries from
  the beginning, with no Netherlands-specific assumption baked in anywhere
  in 19.2–19.3's design. Define normalized concepts: country, region, city,
  postal code, geographic coordinates, radius, language, local business
  categories, local identifiers, registry identifiers — and allow
  country-specific provider capability (e.g. Netherlands: KVK and
  licensed/compliant business-data sources; Morocco: ICE, RC, the OMPIC
  ecosystem, local business directories, plus globally-available discovery
  sources like Google).
- **Dependencies**: 19.1 (per-country provider coverage findings), 19.3
  (the `RegistryProvider`/`DiscoveryProvider` shape this country-awareness
  plugs into).
- **Scope**: a country-capability matrix design document; no country-specific
  code, no per-country adapter.
- **Tests**: n/a (design document); the design must state the test this
  will eventually require — a search for the same business category in two
  different countries returns results shaped by that country's actual
  available identifiers, not a Netherlands-shaped result forced onto
  Morocco's data.
- **Security considerations**: none beyond what 19.1/19.6 already flag for
  personal-data handling per jurisdiction (GDPR for NL/BE/FR; Morocco's own
  Loi 09-08 data-protection regime is a distinct, separately-verified
  requirement, not assumed equivalent to GDPR).
- **Acceptance criteria**: the design explicitly states, for each of the
  four initial countries, which identifiers are and are not assumed to
  exist (a country is never assumed to have the same identifier set as
  another).
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: none beyond confirming no country-specific assumption
  leaked into 19.2/19.3's supposedly-generic design.

### 19.5 Business Identity & Entity Resolution

- **Objective**: design deduplication across multiple sources using
  provider-specific IDs, domain, phone, country-specific registry
  identifiers (KVK, ICE, RC), VAT/tax identifiers where legally usable, and
  normalized business name/address — distinguishing **source identity**
  (what one provider returned) from **canonical business identity** (this
  product's own resolved entity). A company found through multiple
  providers must be resolvable to one CRM company where evidence supports
  that conclusion; destructive automatic merging without sufficient
  confidence is explicitly out of scope for the design.
- **Dependencies**: 19.2 (the `Prospect`/`ProspectCandidate` distinction
  this resolution operates between), 19.4 (country-specific identifiers
  feeding the match).
- **Scope**: a matching-strategy design document (candidate signals, a
  confidence-tiering approach, a human-review path for low-confidence
  matches) — no matching algorithm implementation.
- **Tests**: n/a (design document); the design must state the adversarial
  test this will eventually require — two genuinely different businesses
  sharing a weak signal (e.g. same building address, different companies)
  must not auto-merge.
- **Security considerations**: none beyond what 19.6 flags for the
  provenance metadata this resolution logic reads.
- **Acceptance criteria**: the design states a confidence threshold concept
  and states explicitly that below-threshold matches surface for human
  review rather than auto-merging.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: review the "no destructive auto-merge without sufficient
  confidence" guarantee specifically — this is the one design choice most
  likely to corrupt real CRM data if under-specified.

### 19.6 Enrichment

- **Objective**: design provider-agnostic enrichment for company
  information, contact information, website information, business/category
  information, registry information, and public business signals. Every
  externally sourced datum is designed to retain provenance metadata
  (source, `observed_at`, confidence, and a data/license classification
  where required) — reusing `core.crypto` (Category A) for any
  field-level-sensitive value, the same pattern already used for accounting
  PII (`docs/RESPONSIBILITY-MATRIX.md` "Mini Accounting"). PII is not placed
  into audit events beyond what `core.audit_log`'s existing
  redaction/summarization discipline already permits for any other
  product-owned data. No unsupported legal-retention-period claim is made
  here — Dutch/EU retention specifics remain subject to a future
  Phase-18-style legal/compliance gate, not decided by this design.
- **Dependencies**: 19.3 (the `EnrichmentProvider` Protocol this design
  fills in), 19.5 (provenance feeds the confidence signal entity
  resolution consumes).
- **Scope**: a provenance-metadata schema design (field names/types, not a
  migration); no enrichment logic implementation.
- **Tests**: n/a (design document).
- **Security considerations**: this design explicitly names which fields
  are expected to carry personal data (a contact's name/email/phone from
  an enrichment provider) so 19.1's per-provider personal-data findings and
  a future GDPR/Loi-09-08 legal review have a concrete field list to
  evaluate against, rather than an abstract capability.
- **Acceptance criteria**: the provenance schema design covers every
  enrichment category above with source/`observed_at`/confidence/license
  fields.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: none beyond confirming the provenance schema is complete
  enough that 19.9's CRM handoff can carry it forward without loss.

### 19.7 Prospect Qualification

- **Objective**: design deterministic qualification first — industry
  match, geographic match, employee range, company characteristics,
  website presence, contact availability, and other configured business
  signals — with qualification retaining explainable reasons/signals. An
  opaque AI score is explicitly not the foundational mechanism; AI may
  later assist with interpretation or prioritization on top of the
  deterministic result, not replace it.
- **Dependencies**: 19.2, 19.6 (qualification reads enriched, provenance-
  tagged data).
- **Scope**: a qualification-rule design document (rule shape, how a
  tenant configures its own criteria) — no implementation.
- **Tests**: n/a (design document); the design must state the eventual
  test — a qualification decision is always traceable to the specific
  signals that produced it.
- **Security considerations**: none beyond inherited tenant-isolation
  (qualification criteria are tenant-configured data, isolated exactly like
  any other tenant-owned configuration, per `docs/ARCHITECTURE.md` §2.3).
- **Acceptance criteria**: the design shows, for a worked example, which
  signals produce which qualification outcome and why.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: none beyond confirming the "explainable, not opaque"
  requirement is met by the design as written.

### 19.8 Business / Marketing Audit

- **Objective**: design a reusable audit capability — website, SEO, online
  presence, business listings, reviews/reputation, local visibility,
  technical website signals — operable independently of prospect discovery,
  and reusable for prospects, existing CRM contacts/companies, sales
  workflows, reporting, AI, and automation. Findings are represented as
  structured evidence (a future `AuditFinding` concept: category, severity,
  evidence, source, `observed_at`) rather than only one opaque score.
- **Dependencies**: 19.3 (the `AuditProvider` Protocol), 19.1 (audit/
  website-intelligence provider category findings).
- **Scope**: a design document for `AuditFinding`'s shape and the audit
  capability's intended reuse surface. **Not implemented in this roadmap
  update** — this subphase is explicitly design-only, per the brief.
- **Tests**: n/a.
- **Security considerations**: none beyond what 19.1's provider findings
  already flag for the specific audit providers evaluated.
- **Acceptance criteria**: the `AuditFinding` shape is defined and the
  design explicitly lists every reuse surface named above.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: none — this subphase produces a design document only, by
  explicit instruction.

### 19.9 CRM Handoff

- **Objective**: explicitly define the integration with Phase 4's CRM:
  external candidate → Prospect → Company/Contact → Opportunity → Pipeline.
  This reuses Phase 4's existing `crm.contacts`/`crm.companies`/
  opportunity/pipeline entities and services unchanged — **no duplicate
  Company/Contact/Opportunity model is created**. CRM tenancy,
  authorization (per ADR-0002's `get_current_actor` +
  service-layer-`core.rbac.can()` pattern, which this handoff inherits
  exactly since it writes into `crm.*`), audit, and existing security
  boundaries remain authoritative and unmodified.
- **Dependencies**: 19.2 (the entity distinction this handoff crosses),
  Phase 4.1–4.2 (the CRM entities being written into).
- **Scope**: a handoff-flow design document (what triggers a
  Prospect→Company/Contact conversion, what data carries over, what
  provenance metadata from 19.6 is preserved on the resulting CRM record) —
  no implementation.
- **Tests**: n/a (design document); the design must state the eventual
  test — a converted prospect's resulting CRM company/contact passes the
  same tenant-isolation and cross-tenant-leakage test suite Phase 4.1
  already established, with no separate isolation mechanism invented for
  prospecting-originated CRM records.
- **Security considerations**: the design must state explicitly that a
  handoff never bypasses `crm.*`'s existing `core.rbac.can()` checks — a
  prospecting-originated write is not a privileged path into CRM.
- **Acceptance criteria**: the handoff flow above is fully specified,
  entity by entity, with no ambiguity about which system (Prospecting vs.
  CRM) owns the resulting record once handoff completes (CRM does, always).
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: review this handoff boundary specifically before any
  future implementation phase — this is the one place a bug could produce
  a second, competing CRM.

### 19.10 Prospecting Events

- **Objective**: define future domain events useful to Automation/AI —
  `prospect.discovered`, `prospect.enriched`, `prospect.qualified`,
  `prospect.audit_completed`, `prospect.converted` — following the existing
  product event dispatcher conventions (`docs/ARCHITECTURE.md` §4: every
  event carries `tenant_id`, schemas are versioned from their first
  definition). Event payloads do not carry unnecessary PII or business-
  content payloads — an event signals that something happened and carries
  an identifier a subscriber can look up, not the underlying sensitive data
  itself.
- **Dependencies**: 19.2 (the lifecycle these events describe), Phase 2.2
  (the event dispatcher mechanism itself).
- **Scope**: an event-schema design document (name, version, minimal
  payload shape per event) — no publisher/subscriber implementation.
- **Tests**: n/a (design document).
- **Security considerations**: each event's payload is reviewed against
  the "no unnecessary PII" rule as part of this design, not deferred to
  implementation time.
- **Acceptance criteria**: all five events are defined with a minimal
  payload shape.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: none beyond the payload-minimalism review above.

---

## Phase 20 — Prospecting Automation & AI Agents

Status: PROPOSED, roadmap/design only — no subphase below is implemented.
The automation layer on top of Phase 19. This phase explicitly does not
duplicate the generic automation engine built in Phase 10 — it *consumes*
Phase 10's trigger/condition/action framework (and, once built, its
durable multi-step engine) the same way Phase 12 (Reputation) and Phase
10.4 (10.4A AI automation, 10.4B accounting automation) are themselves
designed to, per `docs/ROADMAP.md` Phase 10's existing design. No second
workflow engine, no second scheduler, no second job runner is introduced.

Example future user intent this phase is designed against: "Every Monday
find 50 dentists in Casablanca within 50 km that match these criteria,
enrich them, audit their online presence, and place qualified prospects
into my CRM pipeline." Architecturally: Schedule → Discovery →
Deduplication → Enrichment → Audit → Qualification → CRM → Phase 10
Automation.

### 20.1 Prospecting trigger/action registrations on Phase 10

- **Objective**: register prospecting-specific triggers and actions
  (scheduled prospect search, recurring discovery, automatic enrichment,
  qualification, audit execution, CRM handoff, prospect assignment) into
  Phase 10's existing trigger/condition/action framework — design only, no
  new engine.
- **Dependencies**: Phase 19 (the domain/provider design this automation
  operates over), Phase 10.2–10.3 (the framework being extended, exactly
  as Phase 10.4A/10.4B are designed to extend it for AI and accounting
  triggers/actions).
- **Scope**: a design document listing each new trigger/action and which
  Phase 19 capability it invokes — no implementation, no new trigger
  engine, no new job runner.
- **Tests**: n/a (design document); the design must state the eventual
  test — each new action executes with no more privilege than the tenant
  user who configured it, mirroring Phase 10.2's existing adversarial
  privilege-escalation test requirement, applied to prospecting actions
  specifically (a scheduled search must not be usable to reach data or
  providers the configuring user's own tenant isn't entitled to).
- **Security considerations**: prospecting provider credentials are
  designed to flow through `infra.secrets`'s `SecretsProvider`, per
  `docs/INTEGRATIONS.md`'s existing credential-handling rule — never stored
  in a CRM record, never a second secrets mechanism.
- **Acceptance criteria**: every trigger/action above is specified with its
  Phase 10 integration point named explicitly.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: none beyond confirming no new engine is implied by this
  design.

### 20.2 Provider selection, budget, and rate controls

- **Objective**: design provider fallback/selection logic, budget/rate
  controls (provider cost visibility, per-tenant usage, quotas, rate
  limits, maximum search size, enrichment limits, audit limits, provider
  budgets, retry controls, duplicate-request prevention), and human
  approval gates where appropriate — consuming `core.usage`/`core.billing`
  (Category A) for entitlement/usage tracking rather than building a second
  usage system, per `docs/RESPONSIBILITY-MATRIX.md`'s existing "Usage
  metering, quota checks" row.
- **Dependencies**: 20.1; `core.usage`/`core.billing` (already available,
  Category A).
- **Scope**: a design document for how a per-tenant prospecting budget maps
  onto existing usage/entitlement primitives, and where a human-approval
  gate sits in the Schedule → Discovery → ... → CRM flow (e.g. before a
  large-cost enrichment batch runs). No implementation.
- **Tests**: n/a (design document); the design must state the eventual
  test — a tenant's configured budget/quota is enforced before a
  cost-incurring provider call is made, not only logged after the fact.
- **Security considerations**: idempotency (`core.idempotency`, Category A)
  is the design's stated mechanism for duplicate-request prevention against
  cost-incurring provider calls, reused rather than reinvented, per
  `docs/INTEGRATIONS.md`'s webhook-idempotency precedent applied to
  outbound provider calls here.
- **Acceptance criteria**: the design states, per cost-incurring operation
  (search, enrichment call, audit run), which existing SaaS-OS primitive
  enforces its budget/rate ceiling.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: review that no second usage/entitlement/billing system is
  implied anywhere in this design — reuse `core.usage`/`core.billing`
  throughout, per the compliance/architecture requirements this roadmap
  update carries.

### 20.3 AI-assisted prospecting agents

- **Objective**: design AI-assisted prospect research and prospecting
  agents (configurable prospecting campaigns, AI-assisted qualification
  interpretation per 19.7's "AI may later assist" note) as `control_plane`
  tool registrations, per `saas-os` `docs/AI-CONTROL-PLANE.md` §3 and this
  product's own Phase 9.1 pattern — never a second agent runtime.
- **Dependencies**: 20.1, 20.2, Phase 9.1 (the tool-registration pattern
  this reuses).
- **Scope**: a design document naming the prospecting-specific tools this
  phase would eventually register (e.g. "summarize prospect audit
  findings," "suggest next prospecting action") and their autonomy tier
  (tier 0/1 only, per Phase 9.1's existing constraint — never tier 2/3
  without a separate, later, evidence-based decision) — no implementation.
- **Tests**: n/a (design document); the design must state the eventual
  test — mirrors Phase 9.1's tool-invocation test shape (invokes correctly
  under permission, denied without it, every invocation audit-logged) and
  Phase 9.1's Data Authorization gate (every tool touching tenant data
  passes through Data Authorization, ADR-0013, before any content reaches
  an external LLM provider).
- **Security considerations**: mirrors Phase 9.1 exactly — no exception for
  prospecting data.
- **Acceptance criteria**: every named tool has a stated autonomy tier and
  a stated Data Authorization touchpoint.
- **Rollback**: n/a.
- **Outcome**: not started.
- **Checkpoint**: none beyond Phase 9.1's standing review, extended to
  these tools once actually registered in a future implementation phase.

---

# UI Track

Status: PROPOSED sequencing, parallel to the Product Backend Track above.
`UI-1` is the next phase to be implemented across either track; no UI phase
below has started. Same template as every backend phase (Objective,
Dependencies, Scope, Tests, Security, Acceptance Criteria, Rollback,
Outcome, Checkpoint); "Outcome" is `not started` for every UI phase.

The UI Track exists because the backend now has enough real, stable API
surface (Agency/Client, CRM, Conversations, Marketing, Appointments,
SaaS-OS auth/tenancy, branding/custom-domain) to build the user-facing
application against, rather than waiting for Phases 8–20 (Telephony, AI,
Automation, Websites, Reputation, Billing, Templates, Accounting,
Reporting, Integrations Hardening, Production/Compliance, Prospecting) to
close first. It is a second track, not a replacement for the backend track:
Phases 8–20 continue exactly as scoped above, unchanged.

### Architecture the UI Track must not violate

Per `docs/ARCHITECTURE.md` §6.1 (added alongside this track):

```text
                    SaaS-OS
                       │
                       ▼
              Product Backend
                       │
                 REST / OpenAPI
                       │
                       ▼
              Product Frontend
```

The frontend consumes the Product REST/OpenAPI API; never imports `saas-os`
code; never accesses the Product database directly; never replaces backend
authorization with its own authoritative rule; contains no authoritative
business rules of its own; treats the backend as the source of truth
throughout. It may hide or disable a control for UX purposes (permission
visibility), but a 403 from the backend is still authoritative even if a
hidden control were somehow reached. Every UI phase below is reviewed
against this boundary; a UI phase that would require reimplementing
backend authorization, duplicating backend domain logic, or reaching the
database directly is out of scope as written and needs a narrowly-scoped
backend correction instead (see "UI/backend contract policy" below).

### Replaceable application-shell architecture

The initial UI layout built in `UI-1` is **not the permanent product
design**. `UI-1` establishes a replaceable shell so that navigation style,
layout, and visual theme can change later without rewriting the domain
pages built in `UI-2`–`UI-7`:

```text
Product Frontend
│
├── AppShell
│   ├── Navigation
│   ├── TopBar
│   └── MainContent
│
├── Dashboard
├── CRM
├── Conversations
├── Marketing
└── Appointments
```

Domain pages consume the shell's layout primitives (navigation, top bar,
content container) rather than each implementing the global chrome
themselves. Concretely, this means the application must be able to evolve
from, e.g., a sidebar layout:

```text
┌──────────────┬────────────────────────────┐
│              │ Top Bar                    │
│   Sidebar    ├────────────────────────────┤
│              │                            │
│              │        Page Content        │
│              │                            │
└──────────────┴────────────────────────────┘
```

to, e.g., a top-nav layout:

```text
┌────────────────────────────────────────────┐
│ Logo   CRM   Conversations   ...   User    │
├────────────────────────────────────────────┤
│                                            │
│                 Page Content               │
│                                            │
└────────────────────────────────────────────┘
```

without rewriting CRM, Conversations, Marketing, or Appointments. `UI-1`'s
acceptance criteria (below) require this to be demonstrated, not merely
claimed.

### UI design strategy: evolutionary, not finalized upfront

`UI-1` builds a lightweight design foundation (typography, spacing,
color/theme, and border/radius tokens; layout primitives; responsive
breakpoints; a handful of reusable basic primitives; navigation and
application-shell abstractions) — not a final design system. `UI-9`, at the
end of this track, is where that foundation matures into a consolidated
system, once real product screens (`UI-2`–`UI-7`) have exposed which
patterns actually repeat.

> The initial UI design is intentionally evolutionary. UI-1 establishes
> reusable foundations and a replaceable shell; later UI phases may change
> the visual language and navigation without requiring domain-page
> rewrites.

## UI-1 — Application Shell & Frontend Foundation

- **Objective**: build the frontend application shell and foundation so the
  product can begin being used through a real UI, without finalizing the
  permanent visual design.
- **Dependencies**: Phase 1.6 (frontend scaffold + OIDC login flow, already
  scoped in the Backend Track), Phase 2.3 (branding, for the shell's
  theming hook), Phase 3 (agency/client tenancy, for tenant context).
- **Scope**: replaceable application shell (`AppShell`/`Navigation`/`TopBar`/
  `MainContent`, per the diagram above); authenticated application/session
  integration on top of Phase 1.6's login flow; tenant/agency context;
  navigation architecture; lightweight design-token foundation (typography,
  spacing, color/theme, border/radius); a handful of reusable UI primitives;
  page/layout conventions; loading, error, empty, and permission-denied
  states; a responsive foundation; a dashboard shell (no real dashboard data
  yet); a Product API client generated from or hand-wired to the existing
  REST/OpenAPI contract. Explicitly **not** in scope: a complete CRM,
  Conversations, Marketing, or Appointments interface, and a finalized
  permanent visual design — both are deliberately deferred to `UI-2`–`UI-7`
  and `UI-9` respectively.
- **Tests**: an authenticated session reaches the dashboard shell through
  the real OIDC flow (Phase 1.6); a permission-denied state renders
  correctly for a route the signed-in user's role doesn't grant, sourced
  from a real 403 response, not a frontend-side permission guess; the
  shell's navigation/layout can be swapped (sidebar ↔ top-nav, per the two
  mockups above) without touching any domain-page component — this is the
  specific, checkable proof of "replaceable shell," not an aspiration.
- **Security considerations**: no client-side storage of any token beyond
  what the OIDC flow's own session mechanism dictates (mirrors Phase 1.6);
  the frontend never independently decides an action is allowed — every
  permission-denied state is rendered from a real backend response, never
  from a frontend-only role check standing alone.
- **Acceptance criteria**: matches the tests above; a reviewer can point at
  the `AppShell`/domain-page boundary and confirm no domain page imports
  navigation/layout internals directly.
- **Rollback**: standard; no real product data flows through this phase.
- **Outcome**: not started.
- **Checkpoint**: demo the shell-swap proof (sidebar → top-nav with no
  domain-page changes) before `UI-2` starts building the first real screen
  on top of it.

## UI-2 — Agency / Dashboard

- **Objective**: the first functional product experience, built on the
  existing Agency APIs (Backend Phase 3).
- **Dependencies**: UI-1; Backend Phase 3.
- **Scope**: agency context; client/tenant switching where the existing
  authorization (Backend Phase 3.3) already supports it; dashboard;
  agency/client overview; onboarding state; basic activity/status
  information; navigation integration into `UI-1`'s shell; permission-aware
  UI; useful empty states.
- **Tests**: dashboard/overview data matches real Agency API responses (no
  permanent mock data); tenant switching respects the same `SUBTREE`/deny
  rules Backend Phase 3.3 already enforces (a UI-level switch attempt the
  backend would reject is itself rejected, not silently allowed client-side).
- **Security considerations**: none beyond `docs/ARCHITECTURE.md` §6.1's
  standing rule — tenant switching is a UI convenience over the backend's
  existing authorization, never a second authorization mechanism.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond UI-1's standing shell-boundary review.

## UI-3 — CRM

- **Objective**: the UI for the existing CRM backend (Backend Phase 4).
- **Dependencies**: UI-1, UI-2; Backend Phase 4.
- **Scope**: contacts, companies, opportunities, pipelines, stages, tasks,
  notes, activities, tags, custom fields, search/filtering, pagination,
  import/export UX where Backend Phase 4.5 already supports it,
  permission-aware actions.
- **Tests**: CRUD/list/filter/paginate against the real CRM API; no
  frontend-only contact/company/opportunity model diverging from the API
  shape.
- **Security considerations**: none beyond §6.1's standing rule; custom-field
  rendering must not assume a shape the API doesn't actually guarantee.
- **Acceptance criteria**: matches the tests above; the CRM domain model
  used by the UI is demonstrably the API's own shape, not a parallel one.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond UI-1's standing shell-boundary review.

## UI-4 — Conversations

- **Objective**: the UI for the existing Conversations backend (Backend
  Phase 5).
- **Dependencies**: UI-1, UI-3 (contact context); Backend Phase 5.
- **Scope**: conversation/thread list, thread view, messages, contact
  context, message templates where Backend Phase 5.5 supports them, sending
  states, error/retry UX, pagination/history, permission handling.
- **Tests**: send/receive flow matches real Conversations API state
  transitions; an internal note (Backend Phase 5.5) never renders as an
  outbound message and vice versa.
- **Security considerations**: none beyond §6.1's standing rule. Do not
  introduce a real-time transport (websockets/SSE) unless the corresponding
  backend capability exists and a roadmap phase explicitly requires it —
  polling against the existing REST API is the default until then.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond UI-1's standing shell-boundary review.

## UI-5 — Marketing

- **Objective**: the UI for the existing Marketing backend (Backend
  Phase 6).
- **Dependencies**: UI-1, UI-3; Backend Phase 6.
- **Scope**: campaigns, campaign recipients, suppressions, forms, form
  submissions, templates, tracking information already exposed by the API
  (Backend Phase 6.5), relevant filtering/search, permission-aware actions.
- **Tests**: suppression-list state shown in the UI matches what the
  backend actually enforces (Backend Phase 6.1's hard gate) — the UI never
  implies a suppressed contact will be reachable.
- **Security considerations**: none beyond §6.1's standing rule. Any
  provider capability the backend has not yet implemented (e.g. a specific
  channel/provider integration not yet built) must render as a clearly
  unavailable/"not yet connected" state — never presented as a working
  integration.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond UI-1's standing shell-boundary review.

## UI-6 — Appointments

- **Objective**: the UI for the existing Appointments backend (Backend
  Phase 7, checkpointed at `de26edc`).
- **Dependencies**: UI-1, UI-3; Backend Phase 7.
- **Scope**: calendars, availability, appointments, booking links,
  appointment management, booking/reschedule/cancel flows, reminder status
  where exposed (Backend Phase 7.3), timezone-aware presentation, provider
  status where applicable (Backend Phase 7.4).
- **Tests**: the UI's booking flow cannot double-book a slot the backend's
  own concurrency guard (Backend Phase 7.2) would reject — a UI-level
  optimistic-booking bug must not present a false success; timezone display
  correctness across at least two zones.
- **Security considerations**: none beyond §6.1's standing rule. Since
  Backend Phase 7.4 (calendar provider sync) is a Category D adapter and
  its actual provider status depends on what's genuinely wired up, the UI
  must not imply Google/Microsoft calendar synchronization exists beyond
  whatever the backend actually reports (fake/provider-neutral status
  surfaced as such, not dressed up as a real sync).
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond UI-1's standing shell-boundary review.

## UI-7 — Settings, Branding & Tenant Configuration

- **Objective**: the user-facing configuration experience for capabilities
  the backend already provides (Backend Phase 2.3–2.4, Phase 3).
- **Dependencies**: UI-1; Backend Phase 2.3–2.4, Phase 3.
- **Scope**: profile/account settings, tenant settings, branding, logo/brand
  configuration where Backend Phase 2.3 supports it, custom-domain
  configuration where Backend Phase 2.4 supports it, role/permission-related
  settings where appropriate, product preferences.
- **Tests**: branding changes made through this UI resolve correctly
  through the existing fallback-chain (Backend Phase 2.3) with no separate
  frontend-side resolution logic.
- **Security considerations**: none beyond §6.1's standing rule. TLS
  provisioning for custom domains is explicitly out of scope (Backend
  Phase 2.4 defers it) — this UI must not imply it exists.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: none beyond UI-1's standing shell-boundary review.

## UI-8 — Responsive, Accessibility & UX Hardening

- **Objective**: after `UI-2`–`UI-7` exist, consolidate the UX patterns
  they exposed rather than duplicating fixes page by page.
- **Dependencies**: UI-2–UI-7.
- **Scope**: responsive layouts, mobile/tablet behavior, accessibility,
  keyboard navigation, consistent loading/error/empty states, confirmation
  flows, destructive-action UX, pagination/filter consistency, navigation
  consistency, visual consistency, performance improvements, frontend
  security hardening.
- **Tests**: a representative set of pages pass a keyboard-navigation and
  screen-reader pass; a destructive action (e.g. delete contact) requires
  confirmation consistently across every module.
- **Security considerations**: frontend security hardening here means
  standard web-client hygiene (XSS-safe rendering, no secret in client
  bundle, CSRF posture matching the backend's own) — no new authorization
  surface is introduced at this phase.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started.
- **Checkpoint**: review pattern consolidation against `UI-9` before that
  phase starts — `UI-8` is where duplication is found, `UI-9` is where it's
  resolved into reusable components.

## UI-9 — Mature Design System & Reusable Product Components

- **Objective**: mature and consolidate the patterns UI-1's lightweight
  foundation and `UI-2`–`UI-8`'s real screens have proven — not a from-zero
  design-system build.
- **Dependencies**: UI-1 (the foundation being matured), UI-8 (the
  duplication it surfaced).
- **Scope**: finalized component patterns — tables, forms, dialogs/drawers,
  tabs, cards, badges, notifications, command/search interfaces, consistent
  data-loading patterns, error boundaries, permission-aware controls — plus
  a matured theme/token system and refined navigation/layout patterns
  building on `UI-1`'s shell, not replacing its architecture.
- **Tests**: each component in the matured system has at least one real
  call site across `UI-2`–`UI-8` it was extracted from (no component built
  speculatively ahead of a proven need).
- **Security considerations**: permission-aware controls here still defer
  to the backend per §6.1 — a mature component library does not become a
  place where authorization logic quietly gets reimplemented for
  convenience.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard; component consolidation is refactor-shaped, not
  behavior-shaped.
- **Outcome**: not started.
- **Checkpoint**: review that no component's authorization behavior
  diverges from what the backend already enforces.

### UI Track sequencing

The UI Track is intentionally not strictly dependent on backend roadmap
completion (Phases 8–20). A UI phase may begin once its own backend
capability is sufficiently stable — it does not wait for later, unrelated
backend phases:

```text
BACKEND                         UI

Phase 3 Agency ───────────────► UI-2 Agency
Phase 4 CRM ──────────────────► UI-3 CRM
Phase 5 Conversations ────────► UI-4 Conversations
Phase 6 Marketing ────────────► UI-5 Marketing
Phase 7 Appointments ─────────► UI-6 Appointments
                                │
                                ├── UI-7 Settings
                                ├── UI-8 UX Hardening
                                └── UI-9 Mature Design System
```

Phases 8–20 (Telephony, AI, Automation, Websites, Reputation, Billing,
Templates, Accounting, Reporting, Integrations Hardening,
Production/Compliance, Prospecting) continue on the Backend Track; each
gets its own UI phase, numbered and scoped when that backend capability is
sufficiently stable — not pre-allocated here, for the same reason Phase
19.1's provider spike declines to pre-select a vendor: scoping it now would
be speculative against capability that doesn't exist yet.

### Frontend-first / backend-first rule

- **Existing, stable backend capability** (CRM, Conversations, Marketing,
  Appointments, Agency/Client, branding/custom-domain, as of this
  addition): **frontend is normally built next** — this is exactly what
  `UI-2`–`UI-7` above do.
- **New capability requiring new domain logic, security rules, data
  models, or infrastructure** (e.g. Telephony, Accounting, Automation's
  durable engine): **backend/domain design comes first**, per those
  phases' own existing Backend Track scoping — no corresponding UI phase is
  opened before the backend design is settled.
- **Large, genuinely new capability**: **backend and frontend are developed
  in parallel around an agreed API contract** — avoids both building
  backend years before it's usable and building a frontend mockup with no
  real backend behind it.

### UI as a product-validation mechanism

Building `UI-2`–`UI-7` against the real APIs may surface: missing API
operations; unsuitable response shapes; missing pagination/filtering;
authorization UX gaps; tenant-context problems; missing loading/error
states; unclear terminology; onboarding problems; missing empty states;
workflow inconsistencies. When this happens:

1. document the issue;
2. classify it — a narrowly-scoped backend correction, a dependency on a
   not-yet-built backend phase, or genuinely new future scope;
3. if it's a narrowly-scoped correction, fix it as such — do not silently
   expand the current backend phase's stated scope;
4. otherwise, record it against the relevant future phase rather than
   building around it in the frontend.

### Mock-data policy

The frontend may use temporary mocks while building against a backend
endpoint that does not yet exist. Mocks must be clearly isolated (never
indistinguishable from a real API response at the code level); must never
become the permanent data source for a completed UI phase; a completed UI
phase (`UI-2`–`UI-7`, once checkpointed) uses the real Product API wherever
the corresponding backend capability exists. No second, frontend-only
domain model is built that diverges from the backend's own.

### UI/backend contract policy

The Product REST/OpenAPI API is the standing contract between the two
tracks. Where an existing API is awkward for the UI actually being built:

1. document the mismatch;
2. determine whether it can be consumed as-is (most cases — an awkward
   shape is not automatically a backend bug);
3. if a backend adjustment is genuinely required, scope it as a narrow
   backend correction against the owning Backend Track phase, not a new
   parallel endpoint;
4. never introduce frontend-specific database access or duplicated
   business logic to work around it — `docs/ARCHITECTURE.md` §6.1 is not
   negotiable per-endpoint.

---

## Notes on Sequencing Flexibility

Exactly like `saas-os`'s own roadmap states: phases within the same group
are ordered; phases across groups may be reordered if a listed dependency
doesn't actually block it. Marketing (6) could plausibly precede
Conversations (5) if email-only campaigns are the priority; Appointments (7)
and Telephony (8) have no dependency on each other and could swap. What must
not move: Phase 1 (repository foundation) first, Phase 2 (foundation) before
anything that needs branding/events, Phase 3 (agency/client tenancy) before
any tenant-scoped product module, and Phase 18 (hardening/compliance) last
**among Phases 1–18**. Phase 19 (Prospecting & Lead Intelligence) and Phase
20 (Prospecting Automation & AI Agents) are a later, separately-gated
extension appended after Phase 18, not part of the 1–18 sequence Phase 18
closes out — see Phase 19's own opening note for why.

The UI Track (`UI-1`–`UI-9`, above) is a third kind of flexibility,
distinct from both: it runs *alongside* Phases 8–20 rather than before or
after them, starting as soon as `UI-1` and each domain phase's own backend
dependency (Phase 3 for `UI-2`, Phase 4 for `UI-3`, and so on) is stable.
It does not renumber, gate, or reorder any Backend Track phase — a UI phase
missing its backend dependency simply doesn't start yet, the same way any
other listed dependency above works.
