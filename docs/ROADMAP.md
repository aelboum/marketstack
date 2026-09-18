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

### 10.4 Automation-specific triggers/actions (invoicing, AI)
- **Objective**: the remaining brief-listed triggers/actions that depend on
  later phases — invoice overdue, payment received, create invoice, record
  payment (depends on Phase 15, Accounting), invoke AI (depends on Phase 9).
- **Dependencies**: 10.2, Phase 9, Phase 15.
- **Scope**: additional trigger/action registrations only — no new engine
  work, reuses 10.2/10.3's mechanism.
- **Tests**: mirrors 10.2.
- **Security considerations**: mirrors 10.2, with particular attention to
  financial actions (`create invoice`, `record payment`) — these must
  reuse Accounting's own posting logic and its immutability discipline
  (`docs/ACCOUNTING-SCOPE.md`), never a parallel, automation-only path
  that bypasses it.
- **Acceptance criteria**: an invoice-overdue trigger and a payment-received
  trigger both work correctly against real Accounting data.
- **Rollback**: standard.
- **Outcome**: not started.
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
- **Outcome**: not started.
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
- **Outcome**: not started.
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
- **Outcome**: not started.
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
- **Outcome**: not started.
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
- **Outcome**: not started.
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
- **Outcome**: not started.
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

## Notes on Sequencing Flexibility

Exactly like `saas-os`'s own roadmap states: phases within the same group
are ordered; phases across groups may be reordered if a listed dependency
doesn't actually block it. Marketing (6) could plausibly precede
Conversations (5) if email-only campaigns are the priority; Appointments (7)
and Telephony (8) have no dependency on each other and could swap. What must
not move: Phase 1 (repository foundation) first, Phase 2 (foundation) before
anything that needs branding/events, Phase 3 (agency/client tenancy) before
any tenant-scoped product module, and Phase 18 (hardening/compliance) last.
