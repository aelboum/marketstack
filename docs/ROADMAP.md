# Implementation Roadmap

Status: **Phases 0–14 implemented** (corrected 2026-09-22 — see "Status
reconciliation" below); Phases 15–20 not started; Phases 21–30 (below,
added 2026-09-22) are the canonical forward-looking sequence following the
Full Product Experience & Smart-System Design Audit. Each historical phase
(0–20) follows the template `saas-os`'s own
`docs/IMPLEMENTATION-ROADMAP.md` uses: Objective, Dependencies, Scope,
Tests, Security, Acceptance Criteria, Rollback, Outcome, Checkpoint. Each
new phase (21–30) extends that template with three fields the audit found
necessary and this document now requires going forward — **Business
outcome**, **User-visible result**, and **Cross-domain integration** — per
"Definition of Done for Future Phases," below. "Checkpoint" states what
gets reviewed with you before the next phase starts; no phase begins
before its predecessor's checkpoint is cleared.

Every phase respects `docs/RESPONSIBILITY-MATRIX.md`: Category A capability
is consumed, never rebuilt; Category B is built here as an interim, cleanly
interfaced, with the upstream-donation path noted; Category C is built here
permanently; Category D is adapter-isolated. Every phase respects
`docs/ARCHITECTURE.md` §2's internal module-boundary rule. No phase modifies
`saas-os`.

## Status reconciliation (2026-09-22)

This document's own "Outcome" field silently stopped being updated after
Phase 7's checkpoint (`de26edc`) even as Phases 8–14 were implemented,
audited, checkpointed, and (Phase 13/14) pushed — a Full Product
Capability Re-Audit and a follow-on Full Product Experience & Smart-System
Design Audit (both 2026-09-22) found and corrected every stale entry
in-place, phase by phase, below (each corrected line is marked "Status
corrected 2026-09-22" with the commit that actually shipped it). Phases
1–7's individual subphases carry a lower-severity version of the same
staleness (never individually filled in, though the overview table below
was always correct) — see the note at the top of Phase 1. Nothing in
Phases 0–20's original Objective/Scope/Dependencies/Tests text was
rewritten; only stale status fields were corrected, with citations.

## Core product principle (added 2026-09-22)

> **Users should not need to understand the internal modules to operate
> the business.** An owner should be able to think "what needs my
> attention," "who hasn't replied," "which appointments are coming up,"
> "which AI actions need my approval" — never "which CRM/Automation/RBAC
> screen do I need." Technical concepts (tenant, RBAC, snapshot, autonomy
> tier, durable workflow, raw UUIDs, internal event names, backend module
> names) remain implementation detail, never primary user-facing product
> concepts, except on the narrow admin-only screens (e.g. agency access
> delegation) where a technical audience genuinely needs them.

This principle governs every Phase 21–30 acceptance criterion below and is
the reason Phases 21–30 exist at all: the Full Product Experience audit
found every individual Layer-2 business engine (CRM, Conversations,
Marketing, Appointments, Automation, Reputation, Websites, Billing,
Templates) to be genuinely real and well-built in isolation, but almost
entirely disconnected from its neighbors, and surfaced to the user as a
flat list of backend module names rather than as business workflows. See
"The Three-Layer Architecture" immediately below.

## The Three-Layer Architecture (added 2026-09-22)

```text
Layer 3 — Smart Business Experience   (Phases 21-23, 28-30; NEW direction)
    Cross-domain workflows, Command Center, Approval Inbox, Unified
    Inbox, business-language UI, default workflows. Composes Layer 2;
    never duplicates it.
        ▲
Layer 2 — Business Engines             (Phases 3-14, real, independent)
    CRM · Conversations · Marketing · Appointments · Automation ·
    Reputation · Websites · Templates · Billing · AI infrastructure ·
    Telephony foundations · Accounting (Phases 24-25, not yet started)
        ▲
Layer 1 — Technical Foundation         (SaaS-OS; consumed, never modified)
    Tenancy · RBAC · delegation · RLS · audit · lifecycle · billing
    primitives · approvals · autonomy tiers · orchestration · security
```

Layer 1 is complete and correctly never touched by this product. Layer 2
is where every phase from 3 through 14 (and, later, 24–25) lives — these
remain independent business/domain engines and this reorganization does
not merge them into one giant domain. **Layer 3 is the gap this roadmap's
new Phases 21–23 and 28–30 exist to close.** It sits above Layer 2,
composes its existing capabilities (new events, new subscribers, new
read-models, new UI compositions), and — critically — must never
reimplement anything Layer 1 or Layer 2 already provides. The clearest
concrete proof this is achievable without new infrastructure:
`control_plane.approvals`' complete `propose_action()` → `approve()`/
`reject()` → `execute_approved()` workflow, and the `autonomy_tier`
gate that enforces it, are **already fully built in SaaS-OS and
completely unused** by this product today (zero tools declare
`autonomy_tier >= 1`) — Phase 29 (Approval Inbox) is pure Layer-3
composition over infrastructure that has been sitting there paid-for
since Phase 9.

### Roadmap Overview — Two Parallel Tracks (corrected 2026-09-22)

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
8  Telephony                         ✓  (foundation only — no live call orchestration)
9  AI                                ✓  (substrate + fail-closed gate — zero live vendor)
10 Automation                        ✓  (10.1-10.3A; 10.4A wired but non-functional; 10.4B blocked on 15)
11 Websites                          ✓  (11.1 only — no lead capture; 11.2/11.3 genuinely not started)
12 Reputation                        ✓  (12.1/12.3; 12.2 deliberately deferred, per ADR-0010)
13 SaaS Resale / Billing             ✓  (8cb0ebc)
14 Templates / Snapshots             ✓  (144b693, 478b029)
15 Mini Accounting
16 Reporting
17 Integrations Hardening
18 Production / Dutch Compliance
19 Prospecting & Lead Intelligence
20 Prospecting Automation & AI Agents

── Smart Business Experience direction (added 2026-09-22) ──────────────

21 Agency Provisioning Loop         ✓  \
22 Lead Capture & Qualification Loop ✓  > Business-engine completion,
23 Customer Lifecycle Loop           ✓  /  Layer 2→3 wiring (`75a6d88`,
                                            corrected 2026-09-29 — was
                                            "not committed"/"not started")

24 Mini Accounting Foundation        ✓  \  (= old Phase 15, split;
25 Revenue & Money Workflow          ✓  >  both corrected 2026-09-29 —
                                            were "not started")

26 AI Vendor + AI Write-Back         ✓  \  makes AI/Telephony live
27 Inbound AI Call                      >  (26 corrected 2026-09-29 — was
                                            "not started"; 27 itself still
                                            not started/not
                                            implementation-ready — 27.1/
                                            27.2 done, 27.0/27.3 are not,
                                            see that phase's own entry)

28 Command Center & Navigation Redesign ✓ (substantially — see Phase 28's
                                            own corrected Outcome; nav
                                            labels still Dutch, not the
                                            English Product Reset target)
29 Approval Inbox                        > Layer 3 proper — see note below
30 Unified Inbox                        /

31 Platform Ownership Foundation         ✓  (added 2026-09-30, implemented
                                            same day — foundation only:
                                            Option A decided, `product
                                            .platform/` module, zero
                                            existing agency reparented, no
                                            route/UI/second-owner yet; see
                                            that phase's own entry. Does NOT
                                            imply Agency/Client (Phase 3) is
                                            incomplete — it is the layer
                                            above it, not a redesign of it)


UI TRACK
────────

UI-1  Application Shell & Frontend Foundation        ✓
UI-2  Agency / Dashboard                             ✓
UI-3  CRM                                            ✓
UI-4  Conversations                                  ✓
UI-5  Marketing                                      ✓
UI-6  Appointments                                   ✓
UI-7  Settings / Branding / Tenant Configuration     ✓
UI-8  Responsive / Accessibility / UX Hardening       ✓  (completed
                                                          2026-10-01;
                                                          2026-09-29 —
                                                          confirmation
                                                          audit + fix,
                                                          Menu keyboard
                                                          nav, CSRF
                                                          verified,
                                                          keyboard-nav/
                                                          screen-reader
                                                          pass all done;
                                                          2026-09-30 —
                                                          responsive
                                                          audit done,
                                                          1 real bug
                                                          found + fixed
                                                          (`a53574c`);
                                                          2026-10-01 —
                                                          audited, drawer
                                                          route-change/
                                                          resize/focus-
                                                          obscured fixes
                                                          (F1–F3) done;
                                                          performance
                                                          audit: no
                                                          justified work,
                                                          build/source
                                                          analysis only)
UI-9  Mature Design System & Reusable Components      ✓  (also shipped,
                                                          ahead of this
                                                          plan and now
                                                          given their own
                                                          numbers below:
                                                          Automation,
                                                          Websites, and
                                                          Reputation UI —
                                                          UI-10)

── Corrected 2026-09-27, retroactive numbering for already-shipped work ──

UI-10 Automation, Websites & Reputation UI            ✓  (git log
                                                          `532c376`,
                                                          `a187c7d`,
                                                          `3000591`)
UI-11 Self-Service Tenant Creation                    △  (create-and-own
                                                          is real; plan/
                                                          trial/billing/
                                                          guided onboarding
                                                          are not)
UI-12 Command Center & Business Navigation            ✓  (Backend Phase 28
                                                          — its UI half)
UI-13 Approval Inbox                                  ✓  (Backend Phase 29
                                                          — its UI half)

── Added — UI Track coverage for backend capability that had no UI-#  ──
── yet (see "UI Track" below, after UI-13, for full phase text)       ──

UI-14 Billing, Plans & Subscription Management        △  (implemented
                                                          2026-09-30,
                                                          checkpoint-
                                                          audited, not yet
                                                          committed —
                                                          pending review)
UI-15 Accounting & Financial Workspace                    (Backend Phases
                                                          24-25 — no UI
                                                          exists yet;
                                                          backend itself
                                                          not started per
                                                          those phases' own
                                                          Outcome fields)
UI-16 Reporting & Business Analytics                      (Backend Phase 16
                                                          — no UI exists
                                                          yet)
UI-17 Telephony & Call Center                             (Backend Phase 8
                                                          foundation-only,
                                                          Phase 27 not
                                                          implementation-
                                                          ready — no UI
                                                          exists yet; must
                                                          not be read as
                                                          production-
                                                          complete)
UI-18 AI Control Center                                   (Backend Phase 9
                                                          partial, Phase 26
                                                          not started — no
                                                          UI exists yet;
                                                          approvals surface
                                                          is UI-13, not
                                                          duplicated here)
UI-19 Integrations & Connected Services                   (Backend Phase 17
                                                          — no UI exists
                                                          yet)
UI-20 Notifications & Activity Center                     (`core.notifications`,
                                                          SaaS-OS Category
                                                          A — no dedicated
                                                          UI exists yet,
                                                          distinct from
                                                          UI-12's Command
                                                          Center)
UI-21 Prospecting / Lead Generation                       (Backend Phases
                                                          19-20, PROPOSED —
                                                          no UI exists yet)
```

The two tracks run side by side: a UI phase begins once its corresponding
backend capability is sufficiently stable, not once the entire backend
track (through Phase 20) is complete. The UI Track is capability-driven
rather than numerically coupled to the backend roadmap — a UI phase does
not imply that every preceding backend phase has completed, only that its
own named backend dependency has. See "UI Track" below for the full phase
breakdown, dependencies, and the principles governing how the two tracks
stay in sync without the UI Track becoming a second, divergent
architecture.

**Phase 28 does not require Phases 24–27 to begin** — it is the highest-
leverage single Layer-3 change available and needs no new Accounting, AI
vendor, or live telephony capability, only composition over data that
already exists (CRM, Appointments, Automation run history, and the
already-built-but-unused approvals infrastructure once Phase 29 lands
alongside it). See "Recommended strategic sequencing" after Phase 30 for
the full reasoning; phases are not silently reordered — every dependency
is stated explicitly where it exists.

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

**Status note (added 2026-09-22, Full Product Capability Re-Audit)**: every
individual subphase from here through Phase 7 still carries its original
template placeholder, `- **Outcome**: not started.` — that field was never
filled in per-subphase for these seven phases, even though the "Roadmap
Overview" table above has correctly shown all of Phase 0–7 checked off
(`✓`) since Phase 7's own checkpoint (`de26edc`). This is a lower-severity
instance of the same staleness pattern found and corrected throughout
Phases 8–14 below (see "Technical / Documentation Debt" after Phase 20):
unlike 8–14, there is no ambiguity at the phase level here — the overview
table, the git history (`c7dfaba` through `de26edc`), and every later
phase's own working code all agree Phases 1–7 are complete — so this note
records the correction once, here, rather than mechanically editing all
~33 individual subphase `Outcome` lines with citations this audit did not
re-verify at that granularity. Treat every subphase Outcome field in
Phases 1–7 as **implemented**, not as its literal stale text.

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
- **Outcome**: implemented, corrected 2026-09-27 (this entry previously
  said "not started," covered only by Phase 1-7's blanket staleness note
  above, never individually verified until now). **Self-service agency/
  tenant creation** — this subphase's own "agency signup creates a root
  tenant" half — is real: `POST /agencies` (`product/agency/routes.py:173`)
  → `provision_agency()` (`product/agency/provisioning.py:106`, whose own
  docstring calls it "Self-service agency signup") creates the tenant and
  assigns the calling user as owner, and the frontend wires this to a real
  "Create agency" form that redirects to the new tenant's dashboard on
  success (UI-2). This is a distinct capability from Phase 3.2's
  invitation-based membership below — no invitation token is involved; any
  authenticated identity with no tenant yet can create one and becomes its
  owner. **Not part of this implemented capability**: commercial plan
  selection, trial handling, signup billing/checkout (Phase 13 remains an
  agency→client resale model, never invoked from this path), and any
  guided onboarding wizard beyond the one-field creation form — those are
  separate, not-yet-scoped future work, not a gap in what this subphase
  itself set out to do. The "agency creates client tenants as children"
  half of this subphase's Objective is Phase 21's own scope, corrected
  separately below.
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

### 7.5 Calendar Foundation
- **Objective**: establish a generic calendar-event abstraction so the
  calendar can represent both an internal/general scheduled block and a
  business appointment, without turning `Appointment` itself into a
  generic event or duplicating `Calendar`.
- **Dependencies**: 7.1–7.2 (calendars, availability, booking).
- **Scope**: `appointments.calendar_events` table/model
  (`product/appointments/models.py::CalendarEvent`) and its service layer
  (`product/appointments/calendar_events.py`) -- create/get/list/update/
  delete, gated by the existing `appointments.calendar` permission (no
  new resource provisioned, no `event_handlers.py` change needed). A
  `CalendarEvent` row is either a generic event (`title` required,
  `appointment_id` NULL) or an appointment-backed event
  (`appointment_id` set, referencing an existing `Appointment` on the
  same calendar) -- Option A of the two relational directions considered
  (`CalendarEvent.appointment_id` nullable, rather than adding a
  `calendar_event_id` onto `Appointment`), chosen because it requires zero
  changes to `Appointment`'s own table, service functions, lifecycle, or
  automation/reputation triggers. No backfill: existing `Appointment` rows
  are not retroactively given a `CalendarEvent` row -- the relationship is
  optional from day one, per this phase's own smallest-viable-model
  mandate. No HTTP routes added this pass -- no current consumer requires
  API exposure yet; the domain/service layer alone establishes the
  boundary.
- **Tests**: `tests/appointments/test_calendar_events_lifecycle.py` --
  generic and appointment-backed creation, title-required-unless-
  appointment-backed validation, time-range validation, calendar/
  appointment reference resolution, appointment-must-match-calendar
  validation, tenant isolation (service-layer non-enumerating 404 and a
  direct DB-constraint proof), and the `ON DELETE SET NULL
  (appointment_id)` unlink-not-destroy behavior.
- **Security considerations**: identical structural tenant isolation to
  every other `appointments.*` table -- composite FKs against
  `(tenant_id, id)`, RLS via `tenant_rls_statements()`, the existing
  `require()` chokepoint. No new isolation boundary introduced (reuses
  `appointments.calendar`'s permission checks).
- **Acceptance criteria**: matches the tests above; the full
  `tests/appointments`, `tests/automation`, and `tests/reputation`
  integration suites remain green (146 passed against a disposable
  Postgres, this pass).
- **Rollback**: `downgrade()` drops `appointments.calendar_events`
  cleanly; nothing else in this phase touches an existing table.
- **Non-goals** (explicitly deferred, not silently narrowed): external
  calendar providers (unchanged from 7.4, still not started); Day/Month/
  Agenda-list calendar UI; drag-and-drop; recurrence; conferencing;
  attendees/invitations; `Opportunity` → `Appointment` (not required by
  this abstraction -- `CalendarEvent` needed no relation to `Opportunity`
  to satisfy its own scope); accounting.
- **Outcome**: implemented -- `product/appointments/models.py::CalendarEvent`,
  `product/appointments/calendar_events.py`, migration
  `0051_create_appointments_calendar_events_table`. `Appointment` itself
  is unmodified.
- **Checkpoint**: revisit before any Day/Month/Agenda-list UI work
  begins -- that phase is the first real consumer of
  `list_calendar_events()` and may surface API-exposure needs this pass
  deliberately deferred.

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
- **Outcome**: implemented (foundation only) — `product/telephony/`
  (`d878dcf`): number provisioning/assignment, `TelephonyProvider`
  Protocol, real HMAC-SHA256 webhook-signature verification. No real
  provider adapter is registered (provider-neutral by design, per
  `docs/RISKS-AND-OPEN-QUESTIONS.md` item 6 — vendor not yet chosen).
  Status corrected 2026-09-22 (Full Product Capability Re-Audit); this
  entry previously read "not started."
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
- **Outcome**: implemented (data model/CRUD + routing-target table only)
  — `d878dcf`. **No live call orchestration exists**: a receiver function
  for the inbound webhook exists in code but is not mounted to any route
  in `product/api/main.py`, so no real call reaches this product today.
  Status corrected 2026-09-22.
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
- **Outcome**: implemented (data model only) — `d878dcf`. Call-record/
  recording storage schema exists; no live call ever populates it today
  (8.2's own gap). Status corrected 2026-09-22.
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
- **Outcome**: implemented (tool definitions only, exactly this
  subphase's own stated scope) — `9b5bb84`: `product/ai/tools/`
  (`lead_qualification.py`, `conversation_summarization.py`,
  `suggested_next_actions.py`), each `autonomy_tier=0`,
  `side_effect="read_only"`, RBAC/Data-Authorization-gated, correctly
  none production-registered. Status corrected 2026-09-22.
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
- **Outcome**: partially implemented (advisory decision logic only) —
  `9b5bb84`: `product/ai/receptionist.py::decide_receptionist_action()`
  is a real confidence-threshold function, but by its own docstring
  there is no STT/TTS vendor, no LLM vendor, and no live audio/media
  stream anywhere in the codebase — Phase 8 carries call *metadata*
  only. Zero live wiring exists. Status corrected 2026-09-22.
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
- **Outcome**: implemented (tool definitions only, mirrors 9.1) —
  `9b5bb84`: `product/ai/tools/suggested_reply.py`, `autonomy_tier=0`,
  `side_effect="read_only"`. Not wired into any Conversations UI surface
  yet, and non-functional pending 9.4's vendor decision. Status corrected
  2026-09-22.
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
- **Outcome**: implemented (provider boundary + fail-closed gate) —
  `6738b3c`: `product/ai/production.py::get_production_llm_provider()`
  unconditionally raises `AIProviderNotConfiguredError` — no vendor
  adapter exists in this repository at all, and a fake/test provider is
  structurally refused from ever being registered as production
  (`_NON_PRODUCTION_PROVIDER_NAMES`). `PRODUCTION_CAPABILITIES`
  (`product/ai/capabilities.py`) names exactly one approved capability,
  `qualify_lead` — correctly, deliberately, still zero live vendor. This
  is the gate working as designed, not a gap. Status corrected
  2026-09-22.
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
- **Outcome**: implemented — Temporal chosen (`9661be0` spike,
  `docs/ADR/0007-automation-execution-substrate.md`). Status corrected
  2026-09-22.
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
- **Outcome**: implemented — `e091264`: `product/automation/` real
  trigger/condition/action engine. Confirmed real cross-domain trigger
  reach today: `crm.opportunity.stage_changed`, `crm.contact.created`,
  `appointments.appointment.booked`, `telephony.call.completed` — with a
  recursion guard (`MAX_AUTOMATION_DEPTH=1`) and `WorkflowRun`
  dedup. Real action vocabulary: `create_task`, `update_contact`,
  `move_opportunity`, `send_email`, `send_webhook` (plus 10.4A's
  `ai.crm.qualify_lead`, see below). No trigger/action reaches Marketing,
  Reputation, Websites, or Billing yet — those modules publish nothing
  this engine subscribes to (a Phase 22/23 gap, see the Smart Business
  Experience section below, not a 10.2 defect). Status corrected
  2026-09-22.
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
- **Outcome**: implemented — `f4dce23`: `product/automation/durable/`,
  Temporal-backed. Status corrected 2026-09-22.
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
- **Outcome**: implemented — `a4112da`:
  `product/foundation/workflow_actions.py` (the generic protocol/registry
  Automation owns) + `product/action_registry_composition.py` (the one
  module allowed to import both `product.automation` and `product.ai`,
  precisely because it is neither, wiring
  `wire_production_automation_actions()` into `create_app()`). No
  import-linter contract was relaxed to build this. Status corrected
  2026-09-22 — `docs/ARCHITECTURE.md` §5.1 previously still described this
  as "not started"/"no such registry exists"; corrected in the Product
  Reset documentation pass, same date (see Technical/Documentation Debt
  item 2 below, updated accordingly).
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
- **Outcome**: implemented, and reachable, but non-functional for every
  real tenant today — `18906b2`: `product/ai/automation_action.py`
  is a real, fully-built adapter (re-checks RBAC/autonomy-tier/Data
  Authorization fresh on every call, no cached decision), registered via
  `wire_production_automation_actions()` in `product/api/main.py`. Both
  prerequisites (10.3A, 9.4) are done. **However**: since 9.4's own
  `PRODUCTION_CAPABILITIES` names no vendor and none is configured
  anywhere in the repository, this action will fail every single
  invocation, for every tenant, today. This is precisely the
  "guaranteed to fail" state this entry's prior revision explicitly
  forbade calling "done" — status corrected 2026-09-22 to reflect that
  the code exists and is wired, while the underlying capability remains
  genuinely not live pending Phase 26 (AI Vendor + AI Write-Back, see
  below) and durable step-output chaining (also Phase 26 — no mechanism
  exists today for a later workflow step to consume this action's
  output, so even a configured vendor could not yet close the loop into
  a CRM write).
- **Checkpoint**: none beyond 10.2's standing security review, extended to
  the AI action specifically (the "no second AI authorization system" rule
  above is the thing to review), plus 10.3A's and 9.4's own checkpoints,
  which are cleared before this subphase begins rather than as part of it.

### 10.4B Accounting automation triggers/actions
- **Objective**: the brief-listed accounting triggers/actions — invoice
  overdue, payment received, create invoice, record payment.
- **Dependencies**: 10.3 (durable execution), the accounting domain
  contract this subphase's own four named triggers/actions (invoice
  overdue, payment received, create invoice, record payment) actually
  operate on.
  **Correction, 2026-09-30**: previously stated as "Phase 15 (Mini
  Accounting)... not started, so this subphase is blocked" — stale. 10.3
  is implemented (`f4dce23`). The accounting domain contract these four
  triggers/actions need is not original Phase 15 as a whole (which also
  covered credit notes/banking/reports/retention, several still separate)
  but specifically Phase 24's ledger foundation (accounts/periods/journal
  entries) and Phase 25's `Invoice`/`Bill`/`Payment`/`PaymentAllocation`
  domain — both implemented, corrected 2026-09-29. See Outcome below for
  what this does, and does not, establish about this subphase's own
  readiness.
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
- **Outcome**: not started. **Correction, 2026-09-30**: previously said
  "blocked on Phase 15; deferred until Phase 15 establishes the accounting
  domain contract" — that blanket blocker is stale, per the Dependencies
  correction above (10.3 and the accounting domain contract this
  subphase's own four named triggers/actions need are both now
  implemented). This does **not** mean 10.4B is implementation-ready: no
  trigger/action registration, idempotency test, or security review named
  in this subphase's own Scope/Tests/Checkpoint fields above has been
  done — that is real, separate, not-yet-started work this correction
  does not perform or design. No accounting model, migration, or API is
  to be created in Automation when that work begins (`docs/ACCOUNTING-SCOPE.md`);
  it consumes Accounting's own existing service/domain contract only,
  unchanged from this subphase's own Scope field above.
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
- **Outcome**: implemented (page CRUD + publish/draft state machine +
  one public render route only) — `a187c7d`. **`product/websites/`
  contains no form/lead-capture entity and no CRM or automation import
  anywhere in the module** — a published website cannot generate a lead
  today; that is 11.2's own gap, not built despite 11.1 being complete.
  Status corrected 2026-09-22.
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

This phase's subphases below are written in agency vocabulary, which must
not be read as an Agency-only customer model: when this phase is actually
scoped, its commercial model must distinguish `Platform → Direct Client`
from `Platform → Agency → Agency Client` where applicable, and must
separately establish plan ownership, subscription ownership, the
reseller/seller relationship, and the entitlement recipient. See
`docs/ADR/0011-one-frontend-multiple-user-contexts.md`. Scope, status and
subphase content below are unchanged by that ADR.

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
  registration, event-handler import) was deferred at first implementation
  time; closed by the 13.4 follow-up below (2026-09-30) -- see
  `product/billing/__init__.py`'s own module docstring for the exact diff
  applied.
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

### 13.4 API exposure (router wiring)

*(Added 2026-09-30. Closes the one gap 13.1-13.3 left open: the billing
implementation existed and was fully tested at the service layer, but its
HTTP surface was never reachable through the running application.)*

```text
Phase 13 billing implementation (13.1-13.3, this phase)
        ↓
API router exposure (13.4, this entry)
        ↓
UI-14 (separate frontend phase, not started by this entry)
```

- **Objective**: mount `product/billing/routes.py::router` into
  `product/api/main.py::create_app()`, so the already-implemented,
  already-tested billing HTTP contract (`GET /v1/billing/plans` and the
  resale-plan/subscription/entitlement routes) is actually reachable
  through the running product API. Not a billing feature change.
- **Dependencies**: 13.1-13.3 (this entry wires existing capability; it
  adds none). Independent of Phase 31 (Platform Ownership Foundation) in
  both directions — the platform tenant's own `SUBTREE` reach and this
  router's `product.billing.permissions.require()` gate are two unrelated
  authorization surfaces that happen to both sit on `core.rbac.can()`;
  neither entry depends on the other.
- **Scope**: `product/api/main.py` (router mount, `product/billing/purge.py`
  purge-participant registration, `product/billing/event_handlers.py`
  import for its `agency.role_provisioned` subscription — the exact,
  pre-planned diff `product/billing/__init__.py`'s own module docstring
  already documented before this entry closed it). `tests/billing
  /test_routes_integration.py` (new, HTTP-level).
- **Tests**: route availability (the router appears in the running app's
  own OpenAPI schema); unauthenticated access rejected (401); an agency
  owner can create/list its own resale plans over HTTP (proving the
  permission layer is reached, not bypassed, and that the newly-wired
  `event_handlers.py` import is what makes a freshly-provisioned owner
  role hold `billing.resale_plan`/`billing.subscription` permissions at
  all); cross-agency and unrelated-actor requests are rejected with the
  existing non-enumerating 404; the pre-existing Agency → Client `SUBTREE`
  reach is preserved through the HTTP layer for the read-only,
  provider-free subscription/entitlement routes. Subscription *creation*
  over HTTP is deliberately not exercised — `product/billing/routes.py`
  never exposes a payment-provider override, so exercising it needs real
  Stripe credentials, a pre-existing billing-implementation property, not
  a router-wiring concern this entry's scope covers.
- **Security considerations**: no new authorization surface — every route
  still resolves the actor via the platform's own `get_current_actor`,
  every mutation still calls `product.billing.permissions.require()` ->
  `core.rbac.can()` first, fail-closed, exactly as before this entry.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: revert the `product/api/main.py` diff; no migration, no
  schema change.
- **Outcome**: implemented. `product/api/main.py` now imports and mounts
  `billing_router` at `/v1/billing`, imports `product.billing
  .event_handlers` for its subscribe side effect, and registers
  `BillingDataPurgeParticipant`. `tests/billing/test_routes_integration.py`:
  9 new integration tests, all passing; the full pre-existing
  `tests/billing/` suite (40 tests) re-run unmodified and unaffected;
  `tests/agency`/`tests/platform`/`tests/accounting` (183 tests) re-run as
  a regression check, all passing. `ruff check`/`ruff format --check`/
  `pyright`/`lint-imports` all pass (22 import-linter contracts kept,
  unchanged — `product.billing` remains a fully independent module).
- **Checkpoint**: none — this entry closes a documented wiring gap with no
  new behavior. UI-14 is a separate frontend phase; this entry itself does
  not implement, unblock beyond "the API now exists", or mark ready any
  part of it (UI-14 was implemented separately, later the same day — see
  its own Outcome, updated 2026-09-30).

### 13.5 SaaS entitlement enforcement

*(Added 2026-09-30. Closes a different, adjacent gap from 13.4's: the
Billing HTTP surface was reachable, but nothing in this product yet
enforced a tenant's actual plan capacity/capability against any real
operation — `docs/ADR/0012-resale-billing-ownership-model.md`'s own
"Entitlement recipient... product capabilities... gated by
`get_entitlements()`" language named this, but no product code exercised
it before this entry.)*

```text
Phase 13 — Billing API Exposure (13.1-13.4)
        ↓
SaaS Entitlement Enforcement (13.5, this entry)
        ↓
Phase 14 — Templates / Snapshots (unchanged, unrelated -- see that
                                    phase's own entry below)
```

- **Objective**: enforce tenant SaaS entitlements and numeric quotas at
  the appropriate Billing operation boundary, using the existing,
  already-built, already-tested SaaS-OS primitives
  (`core.billing.has_entitlement()`/`require_entitlement()` for boolean
  capability gating; `core.usage.check_quota()`/`consume_quota()` for
  atomic numeric quota gating) -- neither primitive was called from any
  product code before this entry. Not a billing feature change, not a
  new entitlement engine, not a redesign of either SaaS-OS mechanism.
- **Dependencies**: Phase 13 (13.1-13.4, Billing API Exposure) plus the
  existing SaaS-OS entitlement/quota primitives named above. Independent
  of Phase 14 (Templates / Snapshots) in both directions -- this entry
  neither depends on it nor is depended on by it; the two are unrelated
  product surfaces that happen to sit adjacent in this roadmap's own
  numbering.
- **Scope**: `product/billing/resale_plans.py::create_resale_plan()` --
  the one operation this entry integrates (this product's own
  "smallest meaningful production integration," not a broad retrofit).
  Two named entitlement keys gate it, checked strictly after the
  pre-existing RBAC `require()` call: `RESELLER_ENABLED_ENTITLEMENT_KEY`
  (boolean -- may this tenant resell at all) and
  `RESALE_PLAN_CREATION_QUOTA_METRIC` (numeric -- how many resale plans
  this tenant may create in the current UTC calendar month).
  `product/billing/routes.py` maps `core.billing.EntitlementDeniedError`
  to `403` and `core.usage.QuotaExceededError` to `429` -- SaaS-OS's own
  established status codes for these exact errors
  (`api.dependencies.require_entitlement_and_quota()`'s own reference
  convention), both with fixed, generic `detail` strings.
- **Tests**: `tests/billing/test_entitlement_enforcement_integration.py`
  (new, 11 tests) -- allowed / not-entitled / missing-key for the
  boolean gate; allowed / exceeded / missing-key for the numeric gate
  (a deliberately OPPOSITE "missing means unlimited" default from the
  boolean gate's own "missing means denied" -- both are SaaS-OS's own
  pre-existing, documented conventions for their respective entitlement
  type, neither invented by this entry); RBAC still enforced even when
  the tenant itself is fully entitled; cross-tenant isolation for both
  the entitlement and the quota check; HTTP-level 403/429 mapping with
  no entitlement-key/quota-metric leakage into the response body.
  Existing `tests/billing/` fixtures (`_give_agency_a_platform_subscription`/
  `_agency_with_resale_plan`/`_seed_resale_plan`) updated to grant the
  new `reseller_enabled` precondition -- no existing assertion weakened.
- **Security considerations**: both checks are evaluated only against the
  literal target `tenant_id` (never a caller-supplied alternate); RBAC
  runs first, unchanged, and entitlement approval never substitutes for
  or bypasses it; the numeric gate is atomic and race-safe by
  `core.usage.consume_quota()`'s own pre-existing transaction-scoped
  advisory lock (not newly built here).
- **Acceptance criteria**: matches the tests above.
- **Rollback**: revert the `product/billing/resale_plans.py`/
  `product/billing/routes.py` diff; no migration, no schema change
  (`core.usage_events`/`core.billing_subscriptions` are pre-existing
  SaaS-OS tables).
- **Outcome**: implemented. `create_resale_plan()` calls
  `core.billing.require_entitlement()` immediately after RBAC, then,
  after input validation and the pre-existing resale-tier ceiling check,
  `core.usage.consume_quota()` immediately before creating the underlying
  `core.billing.Plan`. 11 new integration tests, all passing; the full
  pre-existing `tests/billing/` suite (40 tests) re-run with only
  shared-fixture updates, all passing (51 total, 23 deselected);
  `tests/agency`/`tests/platform`/`tests/accounting` (183 tests) re-run
  as a regression check, all passing. `ruff check`/`ruff format --check`/
  `pyright`/`lint-imports` all pass (22 import-linter contracts kept,
  unchanged -- `product.billing` remains a fully independent module;
  `core.usage` is a Core dependency, not a new product-module edge).
- **Explicit non-goals**: no Stripe/payment-provider integration, no
  checkout, no payment-method handling, no subscription-billing-provider
  work of any kind -- that remains separate, future billing work (this
  roadmap's own Phase 15, immediately below, is "Mini Accounting," an
  unrelated tenant-own-customer-invoicing phase, never a Stripe phase --
  Stripe/payment-provider work has no phase number yet in this document).
  No frontend/UI implementation. No redesign of SaaS-OS's own
  entitlement/quota infrastructure -- both primitives are used exactly as
  SaaS-OS already built and documented them. No broad retrofit of every
  product operation -- this entry integrates exactly the one operation
  named above, deliberately, not "every route now checks entitlements."
- **Checkpoint**: dedicated review of this entry before any future phase
  extends entitlement/quota enforcement to a second operation or product
  module.

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
- **Outcome**: implemented, checkpointed, pushed — `144b693`
  ("feat: add tenant configuration snapshots"), wired into
  `product/api/main.py` at `478b029`. **Scope narrowed at implementation
  time from this entry's original ambition**: `docs/ADR/0013-templates
  -snapshot-scope-and-crm-dependency.md` scopes Phase 14 to exactly one
  configuration domain, `crm.pipelines` — forms, campaigns, automation,
  calendars, and email/SMS templates are explicitly deferred, not
  captured by any snapshot today. The "no tenant business data, no
  secrets" invariant this entry's own tests describe is met exactly as
  specified. Status corrected 2026-09-22.
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
  the import is transactional, all-or-nothing **at the validation layer**:
  `docs/ADR/0013-...` Decision 3 documents that `apply_snapshot()` is
  **not** fully cross-call-transactional in the narrower sense this entry
  originally assumed — CRM's own `pipelines.py` has no delete API to
  compensate a partial failure mid-loop, so every validation that can
  fail (authorization, schema version, payload structure) runs before
  the first write, leaving only a genuine infrastructure fault as a
  residual, disclosed, non-hidden failure window. This is a deliberate,
  reviewed decision, not an oversight — see the ADR for the full
  reasoning.
- **Outcome**: implemented, checkpointed, pushed — `144b693`/`478b029`,
  same as 14.1. ID-remapping is real: every cloned entity is created
  fresh in the target tenant via CRM's own `create_pipeline()`/
  `create_stage()`, never a copied identifier. Status corrected
  2026-09-22.
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
- **Outcome**: implemented, corrected 2026-09-30 (this entry previously
  said "not started," which was stale) — `b9896ad` ("feat: add accounting
  credit notes"): `product/accounting/credit_notes.py`, migrations
  0067-0068. A credit note never mutates the original `Invoice`/
  `InvoiceLine` it corrects (including `outstanding_amount`) — matches
  this subphase's own literal Tests requirement above. Posting is atomic
  with Phase 24's own ledger, mirroring `invoices.py::post_invoice()`'s
  own gapless-numbering/journal-posting pattern. **Not built here,
  deliberately**: reconciling a credit note against what a customer still
  owes is left as a separate, not-yet-specified design decision (not a
  gap silently left open — see `CreditNote`'s own class docstring,
  `product/accounting/models.py`).
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
- **Outcome**: implemented, corrected 2026-09-30 (this entry previously
  said "not started," which was stale) — `7978e54` ("feat: add accounting
  banking reconciliation"): `product/accounting/banking.py`, migrations
  0069-0071. CSV import only this pass (MT940 deliberately deferred, same
  parsing boundary reused when it lands); semi-automatic matching against
  open invoices/expenses with a manual confirm step; no live bank-provider
  aggregation. No HTTP route exposure this pass — service-layer only,
  mirroring Phase 24's own precedent (routes are a separate, additive
  follow-up). **Distinct from, and not a substitute for**, a future PSD2/
  AIS live bank-provider integration (`docs/ACCOUNTING-SCOPE.md`'s own
  "Bank Integration Phasing" step 2) — that remains its own, separately
  scoped, deferred future phase, unaffected by this correction.
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

# The Smart Business Experience (Phases 21–30, added 2026-09-22)

Added by the Full Product Experience & Smart-System Design Audit
(2026-09-22), following directly from the Full Product Capability
Re-Audit's finding earlier the same day that Phases 3–14 individually
cross the bar of "real capability," but are almost entirely disconnected
from each other and surfaced to the user as backend module names rather
than business workflows (see "Core product principle" and "The
Three-Layer Architecture" at the top of this document).

**Nothing here replaces or restarts Phases 0–20.** Phases 21–23 and 26–27
close specific, named wiring gaps in already-shipped Layer-2 engines.
Phases 24–25 are Phase 15 itself, split (see Phase 24's own note). Phases
28–30 are the first real Layer-3 work — genuinely new, but composing
existing Layer-1/Layer-2 capability rather than duplicating any of it. No
phase below introduces a new authorization system, a new event bus, a new
workflow engine, or any SaaS-OS modification.

## Product Reset - Product Composition & Information Architecture Correction (2026-09-22)

Documentation-only correction, produced from a read-only competitor survey
(`docs/highlevel.md`, HighLevel/GoHighLevel, conducted 2026-09-22) that
this product's own leadership asked to be reconciled against this
roadmap. **No code, migration, dependency, test, or frontend
implementation change accompanies this section** - it corrects product
composition, information architecture, and sequencing, and states which
follow-on phases (not yet started) would carry the actual changes.

- **Conclusion, stated up front, because it is the one this section must
  not be misread as avoiding**: existing technical foundations remain
  valuable. This reset changes product composition, information
  architecture, and sequencing - it does not require a repository
  restart, and nothing below asks for one.

### Product vision

Marketstack is a **business operating system organized around the
customer relationship and the business's own lifecycle** - not a
collection of independently-branded modules (CRM, Automation, AI,
Reputation, ...) that a user has to learn to operate individually. A
small business owner should be able to open the product and answer "what
does my business need from me right now," across every channel and every
stage of a customer relationship, without first learning which backend
module owns which fact. This restates and extends, rather than replaces,
the "Core product principle" and "The Three-Layer Architecture" already
recorded above (added 2026-09-22, same audit) - see those sections for
the underlying layering this vision composes on top of, unchanged.

### Core business loop

The lifecycle a real customer relationship moves through in this product,
named explicitly so every phase below can state which stage it owns:

```text
Lead -> Contact -> Qualification -> Opportunity -> Appointment
     -> Customer -> Payment -> Retention -> Review / Referral
```

This is a **loop customers move through, not a rigid state machine** -
nothing in this product enforces a single linear path through it, no new
"lifecycle stage" enum or state-machine table is introduced by this
section, and no phase below is asked to build one. It exists so this
roadmap can say, precisely, which existing phase already owns each stage
(see "Lifecycle ownership" below) rather than leaving stage ownership
implicit and rediscovering gaps by accident, the way the 2026-09-22 Full
Product Capability Re-Audit had to.

**Lifecycle ownership** (existing phases only - no new implementation is
proposed by this table):

| Stage | Owned by | Status |
|---|---|---|
| Lead | Websites (capture), Marketing (form submit) | Phase 22, implemented |
| Contact | CRM | Phase 3, implemented |
| Qualification | CRM (assignment) today; AI-assisted qualification is `ai.crm.qualify_lead` | Assignment: Phase 22, implemented. AI-assisted: 10.4A implemented but non-functional pending Phase 26 (see "Prerequisite status" below) |
| Opportunity | CRM (pipelines/stages, `is_won`/`is_lost`) | Phase 4, implemented - `docs/highlevel.md`'s own comparison claim of "no opportunity/pipeline object" is stale/incorrect, see "HighLevel findings" below |
| Appointment | Appointments | Phase 7/10.2, implemented |
| Customer | CRM Contact + Appointments completion + Reputation auto-request | Phase 23, implemented |
| Payment | Accounting (not started) | Phase 24/25, not started |
| Retention | Automation (reminders/follow-up triggers) | Phase 21-23, implemented for the trigger surface that exists today |
| Review / Referral | Reputation | Phase 10.2/23, implemented |

No stage above requires a new domain module. Where a stage's real owner
is "not started" (Payment), that is Phase 24/25's existing scope,
unchanged by this section.

### Product architecture

- **Customer as the central business hub.** The Contact record is where
  Timeline, Conversations, Opportunities, Appointments, Tasks, Notes,
  Payments (once Phase 24/25 exist), Marketing history, Automation
  activity, Reputation requests, and AI-assisted actions (once Phase 26
  exists) all surface - a documentation/IA conclusion only. Every one of
  those relationships is real and queryable in the backend today (CRM
  contacts, Conversations threads, CRM opportunities, Appointments,
  Automation `WorkflowRun` history, Reputation requests) without any new
  schema; what does not exist yet is a single frontend surface that
  composes them onto the contact record, which is Layer-3 work for a
  future UI phase (a candidate extension of Phase 28's own Command
  Center pattern, not proposed as a new phase number here - no new phase
  is opened by this section beyond the one this section itself is).
- **Automation as the connective business engine.** Automation is not "a
  module among modules" - it is the mechanism by which every other
  domain's events become another domain's actions, already true in
  today's architecture (`product/automation/dispatcher.py` subscribes
  across CRM/Appointments/Marketing/Websites/Reputation event types with
  zero import-linter edges to any of them, per the existing subscribe-by-
  event-type-string boundary). The Trigger -> Condition -> Action ->
  Wait/Follow-up -> Next Event shape HighLevel exposes as a visual
  builder is already the real shape of `product/automation/` today
  (Phase 10.2 dispatcher, Phase 10.3 durable engine for the
  delay/wait-for-event half) - the gap is exposure (see "HighLevel
  findings" below), not engine shape.
- **AI as a capability operating on top of the business system, never a
  separate silo.** AI must never become a second product a user has to
  separately learn to operate - every AI capability shows up inside the
  business context it serves (lead qualification inside CRM/Sales,
  reception inside Inbox/Calendar, once Phase 26/27 exist), the same
  principle Phase 28 already applies to Automation/Reputation/Billing not
  being forced into top-level nav items. This does **not** relax the
  standing dependency-inversion requirement: `product.automation` must
  never import `product.ai` directly, and no future phase may reintroduce
  that edge - the 10.3A registry boundary exists specifically so AI
  capability can be exposed through Automation without that edge, and
  this section extends that same discipline to every future domain <-> AI
  integration point, not just Automation's.

### Information architecture - target navigation

Target top-level navigation concepts, in order: **Dashboard, Inbox,
Customers, Sales, Calendar, Growth, Automations, Accounting, Reputation,
AI** - then a separator - **Manage**.

| Item | Replaces / is | Notes |
|---|---|---|
| Dashboard | Cockpit - "what needs my attention now" | Composes Phase 28's own Command Center requirements (real data only, never fabricated) |
| Inbox | Unified communications center | Existing Conversations module, already the real backing data |
| Customers | Central relationship workspace | Not "Contacts" - signals the hub role described above |
| Sales | Opportunities/pipeline | Deliberately not "Opportunities" as a top-level label - matches HighLevel's business-first naming, same underlying CRM data |
| Calendar | Appointments/bookings | Existing Appointments module |
| Growth | Marketing + Websites + lead capture | Deliberately not "Marketing" alone - matches the broader business job this group already answers in `frontend/lib/nav/config.ts`'s "Marketing" group (Marketing + Websites), renamed to the less technical, broader business term |
| Automations | Rules/workflows, for power users | Not a default top-level distraction - surfaced advanced, matching Phase 28's own "Automation folds into Vandaag... plus an advanced Rules sub-page" design, renamed at the concept level only |
| Accounting | Mini-Exact/mini-Dext direction - invoices, expenses, VAT, payments, banking, bookkeeping, reports | Documentation only; not implemented. Backing module is Phase 24/25, not started. Deliberately not "Money" - this is a real bookkeeping surface, not a generic wallet |
| Reputation | Reviews/referrals | Existing Reputation module |
| AI | Also contextual elsewhere (qualification inside Sales, reception inside Calendar/Inbox once live) | Top-level entry point exists once Phase 26 lands; until then this remains empty/hidden, matching Phase 28's own "Geld... empty/hidden until Phase 25 exists" precedent - never faked |
| Manage (separator) | Business/Team/Services/Calendars/Communication/Integrations/Billing/Branding/Domains/Advanced | Deliberately not the technical word "Settings" |

**Reconciliation with Phase 28, stated honestly.** *(Updated 2026-09-22,
second pass — Phase 28's own Outcome field is now corrected in place; the
paragraph below is kept, lightly amended, as the record of how that
correction was found.)* `frontend/lib/nav/config.ts`, read directly during
this pass, showed a grouped, business-labeled, Dutch-language navigation
(Vandaag/Inbox/Goedkeuringen/Klanten/Agenda/Verkoop/Marketing/Geld/
Instellingen) that already implements Phase 28's underlying principle -
including a real Phase 29 (Goedkeuringen/Approvals) entry - corroborated
by real commits (`c58edb2` "feat: add command center and business
navigation", plus `4cc23d8`/`3000591`/`77e35fe`/`7cce234`). Phase 28's own
"Outcome" field has since been corrected in place to "substantially
implemented," rather than left stale - see that entry above for the full
implemented/remaining breakdown (Command Center read-model, grouped Dutch
nav, and both named translation-layer fixes are done; the Templates/
Snapshots "Business Setup" nav placement and the English/HighLevel target
labels below are not). The target navigation above is the **English, ten-item, HighLevel-
informed target concept set**; reconciling it against the already-shipped
Dutch grouping (merging "Growth" into the existing Marketing group,
promoting Reputation and a future AI entry to top-level, replacing
"Instellingen" with the broader "Manage" grouping described above) is
frontend implementation work for a future UI phase, not done here.

### HighLevel findings (summary, not a copy)

Read in full (`docs/highlevel.md`, 113 lines) and treated as a benchmark,
never a feature-parity checklist. Its own comparison section already
identified where marketstack leads (double-booking prevention via a
Postgres `EXCLUDE USING gist` constraint - more robust than HighLevel's
implied application-layer check; a real event-driven automation
dispatcher; the Phase 23 auto-review-request pattern) and named six gaps
- reminders not a real scheduled job (highest-value, pre-existing,
already-disclosed SaaS-OS gap), reminders email-only with a fixed lead
time, no named calendar-type variety (Round Robin / Class booking called
out as the two most useful presets), no visual workflow builder or
prompt-to-workflow generation, and deferred triggers already tracked
elsewhere in this document. **One correction to `docs/highlevel.md`'s own
text, found during this pass**: its claim "No opportunity/pipeline (deal-
stage) object" is false - CRM's `Opportunity`/pipeline/stage model with
`is_won`/`is_lost` predates this session significantly (Phase 4). Not
edited in `docs/highlevel.md` itself (that file is a dated, read-only
survey record of what was observed in the competitor's product, not a
living spec - correcting its prose would misrepresent when the
observation was made); the correction lives here instead, where it
affects this roadmap's own conclusions.

### Marketstack response per pattern

No ranking or score - classification only, and "not-copy" is a real,
deliberate category, not a placeholder for "later":

| HighLevel pattern | Response | Why |
|---|---|---|
| Unified multi-channel inbox | **Adopt** (already the Inbox nav concept) | Directly matches an existing, real gap: Conversations already exists as the backing data |
| Contact record as universal hub | **Adopt** (documented above) | Matches this section's own Product architecture conclusion; no new schema required |
| Kanban pipeline w/ stage probability | **Not-copy as a UI paradigm; underlying data already exists** | CRM's pipeline/stage/`is_won` model already exists (Phase 4) - a Kanban *view* is a future UI concern, not a new domain concept |
| Round Robin / Class booking calendar presets | **Adapt** | Named in `docs/highlevel.md` as the two most useful additions, buildable as presets on the existing Appointments primitives - not a rewrite; not proposed as new implementation here |
| Real scheduled reminders (cron-backed) | **Adapt, deferred** | Blocked on the same, already-twice-disclosed `infra.jobs`/`core.tenancy` gaps (no deferred-execution parameter, no tenant-enumeration primitive) - a genuine SaaS-OS capability request, never a product-side workaround, per this product's standing "never modify SaaS-OS" rule |
| Multi-channel (SMS/WhatsApp) reminders | **Defer** | Blocked on Phase 15/26-adjacent vendor decisions (SMS vendor not chosen); not this section's concern |
| Visual node-graph workflow builder + prompt-to-workflow | **Later-optional** | Real UX gap for self-service, but the underlying dispatcher/durable engine already matches HighLevel's engine shape - a builder UI is additive, not a prerequisite for anything else in this loop |
| Account Snapshots (agency template bundles) | **Already adopted** | Matches Phase 21's own `snapshot_id`/`apply_snapshot()` provisioning, implemented |
| Voice AI / Conversation AI agents, per-agent templates | **Later-optional, explicitly not a silo** | Real future capability (Phase 26/27), but must land as "AI operating on the business system" per this section's own Product architecture conclusion, never a separately-branded "AI Studio" |
| Reselling/Affiliate/App Marketplace monetization surface | **Not-copy** | Agency monetization tooling, not a core lifecycle concern this product's roadmap is scoped to |
| Membership/course hosting, Media Storage | **Not-copy** | Outside this product's stated business-lifecycle scope; no existing phase claims this territory and none is opened here |

### Roadmap implications

- **Valid, unchanged**: every Layer-1/Layer-2 phase (0-20) and Phases
  21-23/26-27 - this section finds no defect in their scope, only in how
  they are surfaced to the user.
- **Resequence**: none forced - the existing "Recommended strategic
  sequencing" section above (Phase 28 first, if forced to choose) already
  matches this section's own conclusion that IA/composition work does not
  require Accounting or a live AI vendor to begin.
- **Merge**: none - no two existing phases are found to duplicate scope.
- **New prerequisites**: none newly introduced by this section. The three
  prerequisites this section was asked to re-confirm (Action Registry
  10.3A, Phase 9 production readiness 9.4, 10.4A itself) are addressed
  under "Prerequisite status" below rather than restated as new items,
  because restating them here as "not started" would contradict this
  roadmap's own already-corrected, commit-cited entries.
- **Deferred**: Accounting-shaped nav ("Accounting" top-level item above)
  remains fully deferred to Phase 24/25, unchanged; the AI top-level nav
  item remains empty/hidden pending Phase 26, unchanged; 10.4B stays
  independently deferred on Phase 15 + 10.3 only (see below), never made
  dependent on AI or the Action Registry.

### Prerequisite status - reported accurately, not restated as requested

This section's own source brief asked for the Action Registry (10.3A)
and the Phase 9 AI production-readiness follow-on (9.4) to be marked "not
started," and for 10.4A to state "not started - blocked on
prerequisites." **This section does not do that**, and states why
explicitly rather than silently complying or silently ignoring the
instruction:

- **10.3A (Action Registry)**: this roadmap's own entry already states
  "Outcome: implemented" (`a4112da`, "Status corrected 2026-09-22").
  Independently re-verified during this pass by reading
  `product/foundation/workflow_actions.py` and
  `product/action_registry_composition.py` directly: the registry is
  real, and `wire_production_automation_actions()` genuinely wires an AI
  action into `create_app()`. Reverting this to "not started" would
  introduce false documentation drift, which is the exact defect the
  2026-09-22 Full Product Capability Re-Audit exists to prevent.
- **9.4 (AI production readiness)**: this roadmap's own entry already
  states "Outcome: implemented (provider boundary + fail-closed gate)"
  (`6738b3c`). Independently re-verified: `product/ai/policy.py
  ::resolve_tenant_ai_policy()` reads a real, persisted
  `ai.tenant_policies` table, not a hardcoded `None`.
- **10.4A**: this roadmap's own entry already states "implemented, and
  reachable, but non-functional for every real tenant today" (`18906b2`)
  - which already achieves the real underlying concern this section's
  brief was protecting against (that 10.4A not be portrayed as usable or
  production-ready for a real tenant). It is left as-is rather than
  rewritten to "not started - blocked on prerequisites," because the
  prerequisites it names (10.3A, 9.4) are not actually blocking it - both
  are done - and describing a shipped, correctly-gated, honestly-disclosed
  integration as "not started" would be less accurate than what is
  already written, not more.
- **What is actually still true, and is the real prerequisite going
  forward**: no LLM vendor is configured anywhere in this product today,
  and no provider name is currently eligible to be both tenant-approved
  and production-real (`product.ai.policy.PLATFORM_PROVIDER_POLICY`
  hardcodes `eligible_providers={"fake"}`). That is Phase 26's own scope,
  unchanged and un-accelerated by this section. If the concern behind the
  original instruction was "do not let anyone believe AI automation is
  live for a real tenant" - that concern is valid and is already fully
  addressed by the existing text; this section adds no new claim that
  contradicts it.
- **10.4B**: unaffected by any of the above - remains blocked on Phase 15
  + 10.3 only, per `docs/ARCHITECTURE.md` §5.1 and this roadmap's own
  10.4B text, never made dependent on AI or the Action Registry by this
  section.

### Product Experience Principle

Extends, rather than duplicates, the existing "Core product principle"
recorded at the top of this document (2026-09-22, same audit): **users
should experience one connected business system, not a collection of
technical modules.** The existing principle's own corollary - avoid
exposing tenant/raw ids, technical enums, internal event-type strings, or
backend module names in user-facing surfaces - already covers the
terminology-leak instances this section would otherwise restate (see
"Technical / Documentation Debt" item 8 below, and Phase 28's own
translation-layer scope). This section adds no new corollary text; it
only confirms that the HighLevel-informed navigation and lifecycle
conclusions above are additional evidence for a principle this roadmap
already committed to, not a competing one.

- **Objective**: reconcile product composition, IA, and sequencing
  against the HighLevel benchmark survey; correct any roadmap/architecture
  text this reconciliation finds to be materially false (see
  `docs/ARCHITECTURE.md` §5.1, corrected in this pass); document, not
  implement.
- **Dependencies**: none - reads `docs/highlevel.md`, this roadmap, and
  `docs/ARCHITECTURE.md` only.
- **Scope**: documentation only, as stated throughout this section. No
  implementation phase number is claimed or opened by this section beyond
  itself.
- **Tests**: n/a - documentation change; validated by `git diff --check`,
  `git status --short`, and confirming no non-`docs/` path changed.
- **Security considerations**: none - no code, schema, or dependency
  change.
- **Acceptance criteria**: no phase status field was falsified in either
  direction; every claim above cites a real file, commit, or existing
  roadmap entry; the "no rebuild" conclusion is stated explicitly; 10.4B
  remains independently deferred.
- **Rollback**: revert this section and the `docs/ARCHITECTURE.md` §5.1
  edit; no other artifact is touched.
- **Outcome**: not started - this entry records the documentation
  conclusion itself; no follow-on implementation phase named above (the
  Customer-hub UI surface, the target-navigation frontend migration, the
  Accounting nav item, Round Robin/Class calendar presets, a real
  scheduler for reminders, a visual workflow builder) has been started by
  this section.
- **Checkpoint**: human review of this section before any implementation
  phase derived from it begins, per this task's own instruction to stop
  here.

### Definition of Done for future phases (21 onward)

Every phase from here forward must state, in addition to the original
template's Objective/Dependencies/Scope/Tests/Security/Acceptance
Criteria/Rollback/Outcome/Checkpoint fields:

- **Business outcome** — the plain-language business result, independent
  of which module implements it.
- **User-visible result** — what the user concretely sees or can now do.
- **Cross-domain integration** — named explicitly, even when "none."

And must satisfy, as hard acceptance-criteria requirements, not aspirations:

- **A. Business outcome stated plainly.** Every phase states a technical
  objective, a business outcome, a user-visible result, dependencies,
  security considerations, cross-domain integration, acceptance criteria,
  and rollback considerations — a phase missing any of these fields is not
  ready to start.
- **B. Cross-domain requirement.** A phase touching more than one business
  domain is **not** complete merely because each individual module passes
  its own unit tests. At least one integration test must demonstrate an
  event/action in Domain A producing an observable result in Domain B —
  the exact discipline already proven inside single modules (e.g. Phase
  10.2's "each trigger fires correctly from its source event") extended
  *across* module boundaries for the first time.
- **C. Smart-system requirement.** A phase introducing any AI or automation
  behavior must explicitly answer: what does the user want to accomplish;
  what does the system understand; what can it do automatically; what
  requires approval; what does the user see; what happens when the system
  is uncertain; what happens when an external provider fails.
- **D. UX requirement.** No phase may expose `tenant`, RBAC terminology,
  raw UUIDs, autonomy-tier numbers, internal event names, or backend
  module/router names as the primary way a non-admin business user
  interacts with a capability. Admin-only screens (e.g. agency access
  delegation) are explicitly exempted from *removing* this terminology,
  but not from eventually gaining a business-language label wrapping it.
- **E. No fake intelligence.** No dashboard, summary, or "AI" surface may
  show a fabricated or placeholder metric to appear more capable than it
  is — "smart" means real data, real reasoning, real actions, or it does
  not ship yet. (The existing dashboard's own restraint — "renders no
  fabricated metrics," `frontend/app/(app)/t/[tenantId]/dashboard/page.tsx`
  — is the right instinct, applied here as a documented rule rather than
  an unwritten one.)

## Phase 21 — Agency Provisioning Loop

- **Objective**: connect agency client provisioning to the existing
  snapshot/apply capability (Phase 14) and publish an event other modules
  can react to.
- **Business outcome**: an agency can create a new client and make it
  operational in minutes instead of manually rebuilding CRM configuration
  by hand.
- **User-visible result**: provisioning a client offers an optional
  "apply an existing setup" step; the new client's CRM pipeline
  configuration matches the chosen setup immediately, with no manual
  re-entry.
- **Dependencies**: Phase 3 (`product/agency/provisioning.py
  ::provision_client()` — confirmed today to do nothing beyond
  `create_tenant()` + `transition_tenant_status(ACTIVE)`, no event
  published, zero subscribers), Phase 14 (`apply_snapshot()`, real and
  tested, never called from provisioning today).
- **Scope**: `provision_client()` gains an optional `business_setup_id`
  (backend parameter name may still be `snapshot_id` — no backend rename
  is required by this documentation phase, see Phase 28's own note on
  user-facing terminology) that, when supplied, calls the existing
  `apply_snapshot()` inside the same provisioning flow; provisioning
  publishes one new event, `agency.client_provisioned`, via the existing
  plain `product/foundation/events.py::publish()` (not the durable path —
  no cross-restart/cross-process requirement exists for this event, per
  Phase 14's own event-mechanism precedent). Do **not** expand what a
  snapshot can contain in this phase — ADR-0013's current single-domain
  (`crm.pipelines`) scope stays exactly as documented; broadening it is a
  separate, later, explicitly-scoped decision.
- **Security considerations**: no new authorization path — `apply_snapshot()`
  already enforces target-tenant `accounting.snapshot.apply`-equivalent
  permission (`templates.snapshot` resource, `apply` action) exactly as it
  does when called directly; provisioning calling it internally must pass
  the same checks, never bypass them because the caller is "trusted"
  system code.
- **Cross-domain integration**: Agency → Templates (direct call) and
  Agency → any future subscriber of `agency.client_provisioned` (none
  exist yet; this event's entire purpose is to exist for Phase 22/23-era
  and later default-workflow provisioning to subscribe to).
- **Tests**: a cross-domain test — provisioning a client with a chosen
  setup produces a real, queryable `crm.pipelines` row in the *new*
  tenant, scoped correctly, with no cross-tenant leakage (mirrors Phase
  14.2's own adversarial isolation test, applied end-to-end from
  provisioning this time, not from a direct `apply_snapshot()` call).
- **Acceptance criteria**: matches the tests above; provisioning without a
  chosen setup behaves exactly as it does today (this is strictly
  additive).
- **Rollback**: the new parameter is optional; omitting it reproduces
  today's exact behavior. The published event has no consumer yet, so
  removing the `publish()` call is a no-op rollback.
- **Outcome**: implemented, corrected 2026-09-27 (this entry previously
  said "not started") — `b1f9f27` ("feat: add agency client
  provisioning"): `provision_client()` gains the optional snapshot
  parameter and publishes `agency.client_provisioned`;
  `CreateClientForm.tsx` exposes the optional setup-application step.
- **Checkpoint**: none beyond Phase 14.2's own standing ID-remapping
  review, re-confirmed against the provisioning call site specifically.

## Phase 22 — Lead Capture & Qualification Loop

- **Objective**: close the two concrete gaps the audit found in Vertical
  Slice A (Lead → Customer): Websites cannot capture a lead at all, and
  CRM has no ownership/assignment concept.
- **Business outcome**: a lead arriving through the website is captured,
  assigned to someone, and followed up — without the owner manually
  copying information between screens.
- **User-visible result**: a website page can include a lead-capture form;
  a submitted form becomes a real CRM contact with an owner assigned; an
  automation can act on it.
- **Dependencies**: Phase 4 (CRM — `Opportunity` confirmed today to have
  no `assigned_user_id`/owner field of any kind), Phase 6
  (`product/marketing/forms.py::submit_form()` — confirmed today to
  create a real CRM contact via `create_or_update_contact_from_trusted_source()`
  but publish no event), Phase 10.2 (Automation), Phase 11.1 (Websites —
  confirmed today to have no form/lead-capture entity or CRM/automation
  import anywhere in the module).
- **Scope**: (a) `product/websites/` gains a minimal form/submission
  entity reusing the same trusted-source CRM upsert Marketing already
  uses — never a second, divergent lead-capture mechanism; (b) Marketing's
  `submit_form()` gains one `publish()` call (e.g.
  `marketing.lead_captured`) on the existing plain event path; (c) CRM's
  `Opportunity` gains an `assigned_user_id` column and a minimal
  assignment service function, authorized exactly like every other
  CRM mutation; (d) Automation gains one new trigger (subscribing to the
  new lead-capture events) and, optionally, one new assignment action.
- **Security considerations**: assignment must respect existing RBAC —
  assigning an opportunity is a CRM mutation like any other, gated by
  `product.crm.permissions.require()`, never a new authorization path;
  the website form-submission endpoint remains the one legitimately
  anonymous write path in the product (mirrors
  `create_or_update_contact_from_trusted_source()`'s own documented
  "reserved, narrowly named" precedent) — extending it to Websites must
  not broaden who else may call it.
- **Cross-domain integration**: Websites → CRM (contact upsert, new),
  Marketing → Automation (event, new), CRM → Automation (assignment
  trigger, new).
- **Tests**: a cross-domain test — submitting a website form produces a
  real CRM contact AND a real, observable Automation trigger firing
  (per the Definition of Done's requirement B above) — not just a
  passing Websites unit test and a passing Marketing unit test in
  isolation.
- **Acceptance criteria**: matches the tests above; an unassigned lead is
  visibly distinguishable from an assigned one in the CRM API.
- **Rollback**: the new form/event/field are additive; disabling the new
  trigger returns Automation to its current (Phase 10.2) behavior exactly.
- **Outcome**: implemented, corrected 2026-09-27 (this entry previously
  said "not started") — `54ea565` ("feat: add lead capture and
  qualification loop"): Websites' form/submission entity, Marketing's
  `marketing.lead_captured` publish, `Opportunity.assigned_user_id`, and
  the new Automation trigger/assignment action are all real.
- **Checkpoint**: review the anonymous-write-path extension (Websites'
  new form endpoint) with the same scrutiny Phase 6.3's original public
  endpoint received — this is now the second legitimately-anonymous
  write path in the product, not the first, and must not become a
  precedent for a third without the same review each time.

**Explicitly not in scope for this phase**: AI-driven qualification.
`ai.crm.qualify_lead` (Phase 10.4A) remains wired-but-non-functional
until Phase 26 supplies a real LLM vendor and the step-output chaining
that would let its result actually drive the assignment action above —
do not claim qualification is "AI-powered" until Phase 26 lands; this
phase's assignment step may use simple deterministic rules (e.g.
round-robin, or "assign to whoever owns the pipeline") in the meantime.

## Phase 23 — Customer Lifecycle Loop

- **Objective**: make Appointments' own lifecycle transitions visible to
  the rest of the system, and close the loop into Reputation.
- **Business outcome**: once a customer books, attends, cancels, or
  no-shows an appointment, the rest of the business process reacts
  automatically — the owner does not manually transfer information
  between the calendar, CRM, automation, and reputation screens.
- **User-visible result**: a completed appointment automatically results
  in a review request being sent (where enabled); a cancelled/rescheduled
  appointment is visible to any automation watching for it; reminders
  actually fire without a human remembering to trigger them.
- **Dependencies**: Phase 7 (Appointments — confirmed today: booking
  publishes an event Automation consumes; `staff_cancel_appointment()`/
  `staff_reschedule_appointment()`/`reminders.py::send_due_reminders()`
  are real, tested functions that publish nothing and, for reminders,
  have no per-tenant scheduler calling them in production; no no-show
  state exists at all), Phase 10.2 (Automation), Phase 12.1/12.3
  (Reputation — confirmed today: request/response is real but only ever
  triggered by a direct, manual API call; ADR-0010 already, honestly,
  discloses this as deferred rather than hidden).
- **Scope**: Appointments publishes events for cancel, reschedule,
  reminder-sent, and a new "completed" transition; a new `no_show` status
  is added alongside the existing `confirmed`/`cancelled` set; something
  (an `infra.jobs` periodic job, the simplest option that reuses existing
  infrastructure rather than inventing a scheduler) calls
  `send_due_reminders()` per tenant on an actual cadence in production;
  Reputation gains one new subscriber reacting to the "appointment
  completed" event to create a review request automatically, reusing
  Reputation's own existing `review_requests.py` service function
  unchanged.
- **Security considerations**: none beyond each module's own existing
  discipline — this phase adds event-publish/subscribe wiring only, no
  new mutation path and no new permission.
- **Cross-domain integration**: Appointments → Automation (four new
  event types), Appointments → Reputation (new, closes a named gap from
  the audit).
- **Tests**: a cross-domain test — completing an appointment produces a
  real, observable review request in Reputation, not just a passing
  Appointments unit test asserting the status field changed.
- **Acceptance criteria**: matches the tests above; a cancelled/
  rescheduled/reminder-sent appointment is now independently observable
  by any Automation trigger, even though this phase itself only wires
  the completion→review-request path as its one concrete consumer.
- **Rollback**: each new event/subscriber is independently disableable;
  removing the periodic reminder job returns reminders to today's
  "callable but not automatic" state.
- **Outcome**: implemented, corrected 2026-09-29 (this entry previously
  said "not started," and the overview table above separately said "not
  committed" — both stale; reconciled to one factual status) —
  `75a6d88` ("feat: wire Appointments lifecycle events into Automation
  and Reputation (Phase 23)"): `product/appointments/booking.py`
  publishes the five new event types, `no_show`/`completed` statuses are
  real, and `tests/reputation/test_appointment_completed_integration.py`
  is the concrete cross-domain completed-appointment → review-request
  test this phase's own Tests line required. Independently re-verified
  2026-09-29 as part of this correction: the full integration gate
  (`scripts/check-integration.sh`, real disposable Postgres/Redis) passed
  with 0 failures, including this file.
- **Checkpoint**: none beyond Phase 12's own standing review, re-confirmed
  against the new automatic-trigger path specifically (a review request
  firing automatically is a different trust boundary than one triggered
  by an explicit human API call).

## Phase 24 — Mini Accounting Foundation

*(This phase, together with Phase 25, replaces the original Phase 15.1
exactly — no new scope beyond what `docs/ACCOUNTING-SCOPE.md` and
`docs/ROADMAP.md`'s original Phase 15.1 already specified. Renumbered,
not rewritten.)*

- **Objective**: chart of accounts, accounting periods, journal entries,
  double-entry immutability, and period locking — described as a business
  engine whose purpose is letting the owner trust their financial data
  without needing ledger mechanics, not as CRUD over four tables.
- **Business outcome**: the owner's business has a correct, tamper-evident
  financial record from day one, even before any invoice/bill exists.
- **User-visible result**: none directly yet (this phase is foundation,
  matching every other Layer-2 engine's own first subphase) — Phase 25
  is where the owner sees anything.
- **Dependencies**: Phase 2 (`Money` value object, `product/foundation/values.py`
  — already exists, correctly reused, not rebuilt).
- **Scope**: exactly `docs/ROADMAP.md`'s original Phase 15.1 scope —
  chart of accounts, accounting periods, journal entries, and the
  double-entry immutability/period-locking discipline around them. It
  does **not** include customers, invoices, suppliers, tax codes, or
  payments — that is Phase 25's own scope (see that phase's own Scope
  line); this phase touches no contact, no tax code, and no invoice/bill/
  payment row. A design document exists covering the *broader* accounting
  architecture (`docs/ADR/0014-mini-accounting-foundation.md`, currently
  **PROPOSED** — written outside the approved workflow during this
  audit's own research phase, never committed, and not yet formally
  reviewed/approved; see that document's own Status section) —
  independently found to be a well-reasoned, internally consistent
  design. Of its eleven decisions, only Decisions 1–5 (plus the
  journal/ledger-only portion of 9–11) are *this phase's* own scope:
  correct immutability lifecycle `DRAFT→POSTED`/`DRAFT→VOIDED`/
  `POSTED→REVERSED`; correct unsigned dual-column debit/credit
  representation; correct `NUMERIC(18,2)`, never floating-point; correct
  advisory-lock-based period-locking concurrency control; correct "posted
  journal entries are the sole source of truth" rule. **Decisions 6–8**
  (CRM-contact-role-tag customer/supplier relationship, the
  no-hardcoded-VAT-rate tax-code foundation, and payments/allocations)
  are correct designs but are **Phase 25's** scope, not this phase's —
  see the ADR's own "Phase 24 / Phase 25 scope boundary" section.
  Whoever implements this phase should read Decisions 1–5 as a starting
  point, not scope creep, and should formalize the ADR itself as a real,
  reviewed, approved decision record before or alongside this phase's
  first commit. **Correction (2026-09-27, Phase 24 readiness audit)**:
  this bullet previously stated that `core.crypto` is not present in the
  pinned SaaS-OS commit and that this phase may not assume it. That
  claim was checked against a stale commit reference — see "Technical /
  Documentation Debt" item 3, below, for the full correction. The actual
  pinned commit does provide `core.crypto`; in any case this phase's own
  scope (accounts/periods/journals) stores no tax identifier or bank
  account number, so it needs no field-level encryption regardless of
  that question.
- **Security considerations**: unchanged from the original Phase 15.1 —
  this is the financial system of record; immutability is the single
  most important property of this subphase, verified at the data-access
  layer, not by convention.
- **Cross-domain integration**: none required in this phase — Accounting
  remains a standalone Layer-2 engine until Phase 25.
- **Tests**: unchanged from the original — double-entry correctness;
  posted entries are provably immutable at the data-access layer (an
  attempted UPDATE/DELETE on a posted entry is rejected, not just
  discouraged by convention).
- **Acceptance criteria**: matches the tests above.
- **Rollback**: unchanged from the original — foundational; rollback
  after any real posted data exists requires a data-migration-aware plan.
- **Outcome**: implemented, corrected 2026-09-29 (this entry previously
  said "not started," which was stale) — `180efca` ("feat: complete
  phase 24 accounting foundation"): `product/accounting/{accounts,
  journal,periods,models,event_handlers,permissions,purge,errors}.py`,
  migrations 0052-0055. Chart of accounts, non-overlapping/lockable
  periods, and immutable double-entry journals (`DRAFT→POSTED`/
  `DRAFT→VOIDED`/`POSTED→REVERSED`) are real, RLS-isolated, RBAC-gated,
  audit-logged, and wired into the real application composition root,
  scoped exactly to this phase's own Decisions 1-5 boundary (no customer/
  invoice/tax-code/payment row, per this entry's own Scope). The
  immutability test this phase's own Checkpoint names is real:
  `tests/accounting/test_journal_integration.py` proves an attempted
  UPDATE/DELETE on a posted entry is rejected at the data-access layer.
  Independently re-verified 2026-09-29 as part of this correction: the
  full integration gate (`scripts/check-integration.sh`, real disposable
  Postgres/Redis) passed with 0 failures across all 118
  `tests/accounting/` tests. `docs/ADR/0014-mini-accounting-foundation.md`
  remains PROPOSED, not formally approved — unchanged by this correction.
- **Checkpoint**: unchanged from the original — dedicated
  security/correctness review; do not proceed to Phase 25 until the
  immutability test is proven, not merely written. **Update 2026-09-29**:
  proven, per the Outcome above.

## Phase 25 — Revenue & Money Workflow

*(Replaces the original Phase 15.2/15.4's scope, with one new,
non-negotiable requirement this audit adds — see "CRITICAL" below. Credit
notes (original 15.3) and banking (15.5) were not part of this phase's own
implementation — they remained separately sequenced, exactly as the
original roadmap already specified, and were subsequently implemented
under their own sequencing once this phase's invoice/journal foundation
existed to reference; see those subphases' own corrected Outcome fields
for the implementation commits. **Correction, 2026-09-30**: this note
previously described 15.3/15.5 as still "deferred" alongside 15.6/15.7 —
stale as of their own implementation checkpoints below. The full report
suite (15.6) and full retention/anonymization policy (15.7) remain
separately sequenced, deferred, and gated behind accountant/legal review
exactly as the original roadmap already specified — still not pulled
forward by this phase.)*

- **Objective**: invoices, supplier bills, payments, and allocations —
  described from the business owner's perspective, never as CRUD.
- **Business outcome**: the owner can see what's owed, what's been paid,
  and what needs attention, without thinking in ledger mechanics.
  Concretely, two lifecycles:
  - **Customer invoice**: sale happens (an opportunity reaches a
    won-equivalent stage — see Phase 22's still-missing "conversion"
    concept, a real dependency this phase should name explicitly if it
    isn't closed yet) → invoice prepared (manual entry for this phase;
    auto-drafting from an opportunity is a later Layer-3 addition, not
    promised here) → sent → payment detected (manual reconciliation for
    this phase; bank feeds are explicitly out of scope, per
    `docs/ACCOUNTING-SCOPE.md`) → matched → settled → reflected in
    accounting, using posted journal entries as the sole source of truth
    for every report (never `Invoice.status` alone).
  - **Supplier bill**: received (manual entry) → supplier identified →
    duplicate checked → booking suggested (deterministic/manual for this
    phase — OCR/pattern-based auto-booking is a named future Layer-3
    capability, not this phase's job) → approval when required (reuses
    Phase 29's approval infrastructure once it exists, or a simple
    RBAC-gated confirm step if built before Phase 29) → posted → payment
    tracked → exceptions surfaced.
- **User-visible result**: an invoice/bill list with real outstanding
  balances; a "money" view an owner can actually read.
- **Dependencies** (split 2026-09-29, architecture/roadmap reconciliation
  — see "Cross-domain integration" below for why a single "Dependencies"
  line was ambiguous):
  - **Implementation dependency**: Phase 24 only. Every `Invoice`/`Bill`/
    `Payment`/`PaymentAllocation` table, service function, and test in
    this phase's own scope can be built and fully tested against Phase
    24's existing `accounts`/`periods`/`journal_entries`/`journal_lines`
    foundation alone — nothing in Phase 28 is needed to implement or test
    the accounting domain itself.
  - **Completion dependency**: one small, already-anticipated addition to
    Phase 28's existing Command Center (see "Cross-domain integration"
    below) — not a redesign, not a new phase, and not blocked on any
    Phase 28 work that doesn't already exist today.
- **Scope**: `Invoice`, `Bill`, `Payment`, `PaymentAllocation`, gapless
  per-tenant sequential invoice numbering (a legal requirement, per
  `docs/ACCOUNTING-SCOPE.md`'s Dutch-market considerations — numbers
  assigned at commit time from a per-tenant sequence, never
  pre-allocated and potentially discarded), `core.idempotency` applied
  to invoice/bill/payment creation and to journal posting (reusing the
  existing `run_idempotent()` atomic primitive — `core.usage.service
  .consume_quota_idempotent()` is the exact pattern to follow, confirmed
  by direct inspection; no product code calls this primitive today, so
  Accounting would be its first real product-side consumer).
- **Security considerations**: reuses Phase 24's immutability discipline
  for the ledger side; payment-webhook processing (once any payment
  provider exists — none does yet, per `docs/ACCOUNTING-SCOPE.md`'s own
  deferred bank/payment-provider integration) must use
  `core.idempotency` to prevent a retried webhook from double-posting.
- **Cross-domain integration — CRITICAL, non-negotiable**: this phase is
  **not** done merely because CRUD endpoints and database tables exist.
  Definition of Done requires: (1) at least one meaningful domain event
  is published (`accounting.invoice.posted`, `accounting.payment
  .allocated` — both named in ADR-0014's own Decision 10); (2) at least
  one real consumer exists for at least one such event.
  **Sequencing (resolved 2026-09-29, architecture/roadmap reconciliation
  — see the Phase 25 pre-implementation audit for the full contradiction
  this closes)**: this is **not** "Phase 25 depends on Phase 28," and
  Phase 28 needs no advancement of its own — Phase 28 is already
  "substantially implemented" (see that phase's own corrected Outcome)
  and its Command Center requirements already explicitly reserve an
  empty slot for this: "financial items needing attention (once Phase 25
  exists)," and its own Dependencies line already states "a 'Geld'
  [Money] section is empty/hidden until Phase 25 exists, but the phase
  itself is not blocked on them." The already-existing, already-generic
  `AttentionSection` in `frontend/lib/dashboard/commandCenter.ts` is the
  consumer — satisfying option 4 of the audit's own enumerated
  resolutions ("the requirement should instead be satisfied by an
  already-existing generic consumer"), not options 1-3 (no phase-level
  dependency in either direction, no Phase 28 redesign). Concretely,
  Phase 25's own Definition of Done includes: wiring one new query
  (overdue/unpaid invoices) into that existing `AttentionSection`, and
  un-hiding the already-built "Geld"/"Money" nav entry
  (`frontend/lib/nav/config.ts`) now that it has real data — a narrow,
  additive follow-up against Phase 28's existing surface, performed as
  part of *this* phase's own closing work, never a separate blocking
  phase and never a reason to reopen Phase 28's own scope (no Command
  Center redesign, no reporting, no navigation restructuring). Do not
  defer this the way Websites' lead-capture wiring, Appointments' event
  coverage, and Templates' provisioning wiring were each deferred and
  then left disconnected for months — that pattern is the single most
  common root cause this audit found, named explicitly so Accounting
  does not repeat it.
- **Tests**: unchanged from the original Phase 15.2/15.4 (invoice
  numbering has no gaps under concurrent creation — a race-condition
  test; VAT calculation correctness per configured rate; expense
  categorization and ledger-posting correctness), plus the new
  cross-domain test required above.
- **Acceptance criteria**: matches the tests above; a hand-written sample
  invoice validates correctly end-to-end (create → send → mark paid →
  balance reflects correctly), exactly as the original roadmap required.
- **Rollback**: standard, subject to Phase 24's data-migration caveat
  once real invoices exist.
- **Outcome**: implemented, corrected 2026-09-29 (this entry previously
  said "not started," which was stale) — `eb54f8a` ("feat: complete
  phase 25 revenue and money workflow"): `product/accounting/{invoices,
  bills,payments,contacts,tax_codes}.py`, migrations 0056-0063.
  `Invoice`/`Bill`/`Payment`/`PaymentAllocation` are real, with gapless
  per-tenant sequential invoice numbering. The CRITICAL, non-negotiable
  cross-domain requirement above is satisfied, not merely CRUD: this
  commit also touched `frontend/components/today/AttentionSection.tsx`
  and `frontend/lib/api/accounting.ts` (`listOverdueInvoices()`), which
  is the exact "wiring one new query into that existing `AttentionSection`"
  Definition of Done named above. The invoice-numbering concurrency test
  this phase's own Checkpoint names is real:
  `tests/accounting/test_invoices_integration.py::
  test_concurrent_post_never_assigns_duplicate_numbers` (and its gapless/
  sequential counterpart in the same file). **Not yet done, and not
  claimed here**: the "Geld" nav entry (`frontend/lib/nav/config.ts`)
  is still `status: "planned"`, un-hidden per this phase's own closing
  work is described as required — its own code comment still says
  "Accounting (Phase 24/25) has not started," which this correction does
  not touch (out of this reconciliation's scope; noted for a future,
  separately-scoped frontend correction, and matches this roadmap's own
  UI-15 — Accounting & Financial Workspace, itself still correctly
  `not started`, since no accounting UI route exists). Independently
  re-verified 2026-09-29: the full integration gate
  (`scripts/check-integration.sh`, real disposable Postgres/Redis) passed
  with 0 failures across all 118 `tests/accounting/` tests, including
  both invoice-numbering tests above.
- **Checkpoint**: the invoice-numbering concurrency test specifically —
  a legal requirement, not a nice-to-have, unchanged from the original.
  **Update 2026-09-29**: proven, per the Outcome above.

## Phase 26 — AI Vendor + AI Write-Back

- **Objective**: make the already-built AI substrate (Phase 9)
  operational, and close the one structural gap preventing any AI result
  from ever driving a real action: durable Automation has no
  step-output-chaining mechanism today.
- **Business outcome**: the AI qualification/suggestion tools that
  already exist stop being dead code and start doing real, approved work.
- **User-visible result**: a lead is actually AI-qualified (not just
  eligible to be, per Phase 22); a suggested reply is actually AI-drafted
  from real conversation content.
- **Dependencies**: Phase 9.4 (production gate, built and correctly
  fail-closed today), Phase 10.3 (durable engine), 10.3A (action registry,
  implemented — `a4112da`), 10.4A (AI automation action, implemented and
  wired but non-functional pending this phase — `18906b2`). All four are
  done; this phase's own remaining gap is the vendor decision itself, not
  any of these prerequisites.
- **Scope, mapped to the AI Business Agent model this audit established**:
  - **Observe**: unchanged — existing tools' `required_resource`/
    `required_action` grants, RBAC + Data-Authorization gated, as today.
  - **Understand**: register one real `LLMProvider` adapter behind
    `product/ai/production.py::register_production_llm_provider()` — a
    vendor decision (`docs/RISKS-AND-OPEN-QUESTIONS.md` item 6 does not
    even list an LLM vendor as a named open question; this phase is where
    that decision must finally be made explicit).
  - **Decide**: extend at least one existing tool (start with
    `qualify_lead`, already production-approved in
    `PRODUCTION_CAPABILITIES`) to return a structured decision object,
    not only a text string.
  - **Execute**: low-risk, reversible results (e.g. "create a follow-up
    task") may execute at `autonomy_tier=0`, unchanged from today's tier
    assignment.
  - **Approve**: higher-risk results (e.g. "send this drafted reply to
    the customer") must go through the **existing, already-built,
    currently-unused** `control_plane.approvals` workflow —
    `propose_action()` → `approve()`/`reject()` → `execute_approved()` —
    by declaring `autonomy_tier >= 1` on that specific action. **Do not
    invent a new approval architecture.** Requires Phase 29 (or at least
    its backing service layer) to exist for a human to actually see and
    act on the resulting `ApprovalRequest`.
  - **Explain**: `execute_approved()` already audit-logs the proposer's
    identity; this phase's job is surfacing that trail in a form a
    non-technical user can read (see Phase 29).
  - **Execution substrate**: `product/foundation/workflow_actions.py`'s
    registry (Phase 10.3A) gains the minimal step-output-chaining
    mechanism needed for a later durable-workflow step to consume an
    earlier AI step's structured decision — the one piece of genuinely
    new infrastructure this phase requires, scoped narrowly to
    "pass one step's typed output into the next step's typed input,"
    never a general-purpose data-flow language.
- **Security considerations**: unchanged posture from Phase 9.4/10.4A —
  Automation still never becomes a second AI authorization system; the
  vendor adapter is the only genuinely new trust boundary, gated by
  `infra.secrets` for its credential exactly like every other Category-D
  provider in this product.
- **Cross-domain integration**: AI → Automation (already wired, Phase
  10.4A) → whichever domain the now-executable action targets (e.g. CRM,
  for a qualification write-back).
- **Tests**: a real tenant executes one approved capability end-to-end
  through the production path (RBAC, autonomy tier, Data Authorization,
  audit all exercised for real, not via a test-constructed permissive
  registry) — unchanged from Phase 9.4's own acceptance bar, now finally
  exercised against a real vendor; plus a new test proving a tier-1
  proposal correctly blocks execution until `approve()` is called, and
  never executes after `reject()`.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: unregister the vendor adapter — Phase 9.4's fail-closed
  default-deny posture is always available as a safe resting state.
- **Outcome**: implemented, corrected 2026-09-29 (this entry previously
  said "not started," which was stale) — `c6212b6` ("feat: complete
  phase 26 openai production provider"): `product/ai/{openai_provider,
  openai_config,production}.py` register a real `LLMProvider` vendor
  (OpenAI) behind `register_production_llm_provider()`, resolving the
  vendor decision this phase's own Scope named. `fed8ce2` ("feat:
  complete phase 26 ai automation"): `qualify_lead` returns a structured
  decision object, `product/foundation/workflow_actions.py` gains the
  step-output-chaining mechanism, and the tier-1 approval path is real
  and tested — `tests/ai/test_invocation_approval_integration.py::
  test_tier1_tool_creates_a_proposal_and_never_executes` and
  `::test_rejected_approval_never_executes_and_tool_is_never_called`
  are the concrete tests this phase's own Tests line required (a tier-1
  proposal blocks until `approve()`, never executes after `reject()`).
  Independently re-verified 2026-09-29: the full integration gate
  (`scripts/check-integration.sh`, real disposable Postgres/Redis)
  passed with 0 failures across all `tests/ai/` integration tests,
  including `test_tools_integration.py` and
  `test_invocation_approval_integration.py`. **Not claimed here**: this
  entry does not extend to Phase 27 (Inbound AI Call), which remains
  separately gated and not implementation-ready — see that phase's own
  Outcome, unchanged by this correction except where 27.1/27.2 are
  addressed individually below.
- **Checkpoint**: dedicated security review before any real tenant data
  reaches a real external provider — unchanged from Phase 9.4's own
  standing requirement, now actually exercised rather than perpetually
  deferred.

## Phase 27 — Inbound AI Call

The Phase 27 implementation-readiness audit found this phase **not
implementation-ready**: beyond the STT/TTS vendor decision the original
entry already named, several architectural foundations this phase depends
on do not exist yet (a live call-session/turn model, an AI actor identity
distinct from the caller, call-originated-action safety, and a real human
handoff primitive — Phase 8.4 was explicitly deferred, not built). The
phase is decomposed below into four explicit prerequisite subphases
(27.0–27.3) plus the integration phase itself, following this roadmap's
own numbered-subphase convention (mirrors Phase 9's 9.1–9.4 and Phase 10's
10.1–10.4B) rather than introducing a new top-level phase number.

```text
Phase 26 (AI Automation, done)
        |
        v
27.0 Voice Transport Foundation
        |
        v
27.1 Call Session & Actor Foundation
        |
        +----------------+
        v                v
27.2 Call-Initiated     27.3 Human Handoff
     Action Safety             Foundation
        |                |
        +--------+-------+
                 v
         Phase 27 Inbound AI Call
                 |
                 v
         Dedicated Security + UX Review
                 |
                 v
         Real tenant phone number
```

### 27.0 Voice Transport Foundation
- **Objective**: establish one real, selected PBX/SIP/media transport and
  one real, selected STT/TTS integration behind the existing abstractions —
  the vendor/transport prerequisite only, no conversational logic. No
  vendor is named or implied here; `docs/RISKS-AND-OPEN-QUESTIONS.md` item 6
  and `docs/INTEGRATIONS.md`'s own vendor-neutral Category D listing still
  own that open decision.
- **Dependencies**: Phase 8 (Telephony foundation), Phase 26 (done).
- **Scope**: a real `TelephonyProvider` implementation (`product/telephony
  /provider.py`'s own Protocol — only `FakeTelephonyProvider` exists today);
  real provider-specific webhook-signature verification; wiring the
  existing inbound webhook receiver (`product/telephony/calls.py
  ::receive_inbound_call_event()`) to a real route; real PBX/SIP/media
  transport; streaming-capable STT; streaming/low-latency TTS (the existing
  `product/ai/voice_provider.py::SpeechProvider` Protocol is whole-buffer
  only today and must be extended, never replaced); barge-in/interruption
  support; provider credentials through the existing `infra.secrets`
  boundary, mirroring `product/ai/openai_provider.py`'s own pattern;
  failure/timeout behavior at the transport layer.
- **Existing abstractions to reuse**: `product/telephony/provider.py`,
  `product/telephony/calls.py`, `product/ai/voice_provider.py`,
  `infra.secrets`.
- **Explicit non-goals**: no conversational state; no AI receptionist; no
  business actions; no confidence logic; no human handoff; no new tool
  system.
- **Outcome**: not started.

### 27.1 Call Session & Actor Foundation
- **Objective**: define the bounded live-call session/turn architecture and
  the authorized AI execution identity required to invoke Phase 26 from a
  live inbound call.
- **Dependencies**: 27.0.
- **Scope**: bounded, ephemeral conversational session/turn state, kept
  explicitly separate from `product/telephony/models.py::Call`/`CallEvent`
  (which stay payload-free by design); turn ordering; interruption/media
  state; explicit separation of call transport state, conversational state,
  AI invocation state, and durable business-action state; an explicit
  live-call AI actor identity, tenant-scoped, invoking
  `product/ai/invocation.py::invoke_product_ai_tool()` unchanged; per-turn
  authorization using the existing Phase 26 authorization path unchanged; a
  deterministic, closed-vocabulary call-decision contract distinguishing
  attempt / clarify / escalate / decline (built the same way as Phase 26A's
  own `qualify_lead` structured decision — a tool-local closed `Literal`,
  never an invented numeric confidence score).
- **Architectural constraints**: caller identity is not the AI actor
  identity; caller ID is not authentication; the actor must be an approved,
  tenant-scoped identity, never a synthetic identity that bypasses
  authorization; existing RBAC/Data Authorization remain authoritative,
  unchanged; conversational state is bounded and ephemeral; this is not a
  Temporal workflow, and no general-purpose conversational workflow engine
  is introduced.
- **Outcome**: implemented, corrected 2026-09-29 (this entry previously
  said "not started," which was stale) — `c57321d` ("feat: complete
  phase 27.1 call session foundation"): `product/telephony/
  call_session.py` (bounded session/turn state, kept separate from
  `Call`/`CallEvent`), `product/telephony/receptionist.py` (the
  attempt/clarify/escalate/decline closed-vocabulary decision contract
  this entry's own Scope named). Tests:
  `tests/telephony/test_call_session_unit.py` (unit),
  `tests/telephony/test_receptionist_integration.py` (integration).
  Independently re-verified 2026-09-29: the full integration gate
  (`scripts/check-integration.sh`, real disposable Postgres/Redis)
  passed with 0 failures, including
  `test_receptionist_integration.py`; the unit test was separately
  confirmed passing (no database dependency). **Not claimed here**:
  27.0 (Voice Transport Foundation) remains not started — no real
  `TelephonyProvider`/STT/TTS is registered (confirmed by inspection:
  only `FakeTelephonyProvider` exists) — so this entry's own live-call
  usage has nothing real to run against yet; that gap is 27.0's, not
  27.1's own scope, and is unchanged by this correction.

### 27.2 Call-Initiated Action Safety
- **Objective**: make existing Phase 26 business capabilities safe to
  invoke from a live call without a second authorization, tool, or approval
  system.
- **Dependencies**: 27.1.
- **Scope**: call/session/turn correlation; idempotency for call-originated
  business actions using the existing `core.idempotency` infrastructure
  (mirrors Automation's own `f"{run_id}.{step_key}"` keying, applied per
  turn); duplicate-speech/retry protection; existing Phase 26 RBAC/Data
  Authorization/autonomy-tier enforcement, unmodified; non-blocking
  handling of tier-1 approval-required actions — escalation (27.3), never a
  synchronous wait and never treating caller intent as approval;
  **read-only appointment availability** (`product/appointments
  /availability.py::compute_available_slots()`), gated by the receptionist
  actor's own ordinary RBAC/Data Authorization grant, with `tenant_id`
  resolved exclusively from the trusted inbound DID, never from caller
  input. **Contact-bound appointment booking is explicitly out of scope for
  this phase** — see Caller/contact trust boundary below; this supersedes
  this section's own earlier framing (now corrected) that booking was
  blocked only by `book_appointment()` lacking a `require()` call and by
  "no phone-based contact lookup/dedup" — `docs/ADR/0018-inbound-phone-caller
  -contact-trust-boundary.md` establishes that the real blocker is a
  trust-boundary decision, not a missing lookup/deduplication feature, and
  that decision does not resolve to "safe to book" for this phase.
- **Caller/contact trust boundary** (`docs/ADR/0018-inbound-phone-caller
  -contact-trust-boundary.md`): an inbound phone caller is unauthenticated;
  caller ID, and any caller-supplied email/phone/name, are claims, never
  credentials, and must never be treated as identity proof. Concretely for
  this phase: **contact attachment is blocked** — a call must never be
  attached to an existing CRM contact on the strength of caller-supplied
  identity attributes; **existing-contact mutation is blocked** — a
  phone-originated flow must never call `product/crm/contacts.py
  ::create_or_update_contact_from_trusted_source()` in a way that could
  match and update an existing contact (that function's own existing,
  unchanged sanctioned callers — `product/marketing/forms.py::submit_form()`,
  `product/websites/leads.py::capture_lead()`, and `product/appointments
  /booking.py::book_appointment()`'s existing public web path,
  `docs/ADR/0005-...` — are unaffected by this restriction, which applies
  only to the phone/voice channel); **anonymous phone-originated contact
  creation is deferred**, not in this phase's implementation scope — any
  future version requires its own separate bounded design and must be
  create-only, explicitly labeled unverified, and never auto-merged with an
  existing contact; **contact-bound booking is blocked** pending either
  that separately-approved anonymous/unverified booking architecture (with
  its own new, safe booking entry point) or a separately designed and
  approved caller-identity-verification mechanism — no such verification
  foundation exists in this repository today, and designing one is outside
  this phase's scope.
- **Explicit constraints**: no second tool registry; no second approval
  system; no autonomy-tier weakening; no caller-originated authorization
  bypass; no existing-contact match/update from caller-supplied identity
  attributes; no reuse of `create_or_update_contact_from_trusted_source()`
  by a phone-originated flow in a way that could resolve to an existing
  contact; no anonymous contact creation or booking entry point added in
  this phase; existing CRM/appointment business semantics remain
  authoritative and unchanged for every already-sanctioned caller.
- **Outcome**: implemented, corrected 2026-09-29 (this entry previously
  said "not started," which was stale) — `226e4b2` ("feat: complete
  phase 27.2 call action safety"): `product/call_action_safety.py`
  (call/session/turn correlation, `core.idempotency`-based
  duplicate-action protection, read-only appointment-availability
  access gated by the receptionist actor's own RBAC/Data Authorization,
  the caller/contact trust-boundary blocks this entry's own "Explicit
  constraints" list requires), with 24 tests in
  `tests/test_call_action_safety_integration.py`. Independently
  re-verified 2026-09-29: the full integration gate
  (`scripts/check-integration.sh`, real disposable Postgres/Redis)
  passed with 0 failures, including this file. **Caveat**: the
  `docs/ADR/0018-inbound-phone-caller-contact-trust-boundary.md` this
  entry's own text cites is itself not yet committed to this repository
  (working-tree only) — the code and its tests are real and committed;
  the formal ADR record is not, and this correction does not commit it.
  **Not claimed here**: 27.3 (Human Handoff Foundation) remains not
  started — no live mid-call transfer primitive exists yet (confirmed
  by inspection) — so escalation from this phase's own non-blocking
  tier-1 handling has nowhere real to escalate *to* yet; that gap is
  27.3's, not 27.2's own scope, and is unchanged by this correction.

### 27.3 Human Handoff Foundation
- **Objective**: provide a real live-call handoff primitive that transfers
  an in-progress AI call to a tenant-authorized human while preserving
  bounded context — closing Phase 8.4's own previously-deferred scope.
- **Dependencies**: 27.1.
- **Scope**: live transfer of an in-progress call (`product/telephony
  /models.py::Call`'s own status, transitioned mid-call — new, since
  today's `route_inbound_call()` only assigns before the call is answered);
  tenant-scoped human destination selection reusing the existing
  `PhoneNumberRoutingTarget` pool unchanged; a bounded escalation-context
  payload (escalation reason, relevant contact/call/session identifiers, a
  bounded summary — ids and small scalars only, mirroring `CallEvent`'s own
  and Phase 26C's `Run.context`'s own "never a full record" discipline); an
  audit event; a deterministic fallback to ordinary Phase 8.2 routing if the
  selected destination is unavailable.
- **Security constraints**: destination is never caller-controlled and
  always tenant-scoped; no raw transcript is placed into the handoff
  payload; context must be bounded; a cold transfer does not satisfy the
  handoff requirement; ordinary Phase 8.2 routing remains the fallback.
- **Outcome**: not started.

### Phase 27 integration (after 27.0–27.3 are complete)
- **Objective**: a customer can call the business and the system can
  understand, respond, and perform permitted business actions — this is
  intentionally the last AI/Telephony phase, not "connect an LLM to
  FreeSWITCH." Compose the completed 27.0–27.3 foundations into the live
  inbound AI receptionist and prove the complete end-to-end behavior — this
  phase is integration and verification, not where the hardest unknowns are
  discovered.
- **Business outcome**: routine inbound calls (availability questions,
  simple booking requests) are handled without a human answering, with a
  clean, context-preserving handoff for everything else.
- **User-visible result**: a live phone number where a customer's call is
  answered, understood, and — for permitted actions — resolved.
- **Dependencies**: Phase 8 (Telephony foundation, done), Phase 26 (AI
  Automation, done), 27.0 Voice Transport Foundation (not started), 27.1
  Call Session & Actor Foundation (implemented, corrected 2026-09-29 —
  see that subphase's own Outcome), 27.2 Call-Initiated Action Safety
  (implemented, corrected 2026-09-29 — see that subphase's own Outcome),
  27.3 Human Handoff Foundation (not started). Direct
  chain: `27.0 -> 27.1 -> {27.2, 27.3} -> Phase 27`; Phase 8/Phase 26 are
  the transitive foundations 27.0/27.1 already build on, not a second,
  independent dependency of this phase. **This phase itself remains
  blocked**: 27.0 and 27.3 are still not started, and the chain above
  requires all four — 27.1/27.2 being done does not change this phase's
  own "not started" Outcome below.
- **Scope**: mount the existing inbound-webhook receiver to a real route
  (27.0); a live call-session loop (PBX/SIP session → STT → LLM turn, using
  Phase 26's now-real vendor and tool-calling path → TTS → response,
  27.0–27.1); authorized business tools (the same Phase 9/26 tool registry,
  no second tool system, 27.2); human handoff (27.3, preserving AI-gathered
  context, not a cold transfer); call logging into Phase 8.3's existing
  data model; CRM/appointment actions reusing existing service functions
  unchanged.
- **Security considerations**: this is the **single highest-blast-radius
  capability in the entire roadmap** (`docs/RISKS-AND-OPEN-QUESTIONS.md`
  names it explicitly) — real customers interacting with an autonomous
  agent on a live phone line. Every AI action taken during the call must
  be audit-logged with full completeness; the agent must escalate outside
  a defined confidence/scope boundary, never guess past it; approval
  boundaries from Phase 26 apply identically to any tier-1-equivalent
  action a call might trigger (e.g. committing to a specific customer
  promise), never a phone-specific approval bypass; failure/fallback
  behavior (STT/TTS/LLM/PBX provider outage) must degrade to ordinary human
  call routing, never to a silently broken call.
- **Cross-domain integration**: Telephony → AI (live, new) → CRM/
  Appointments (action execution) → Reputation/Automation (post-call, via
  existing event paths).
- **Tests**: a simulated call is correctly handled or correctly escalated
  per a defined confidence/scope boundary; a provider outage mid-call
  degrades to human routing without data loss; every AI action during a
  simulated call is fully audit-logged; escalation preserves handoff
  context (27.3); tier-1-equivalent actions still require approval, never a
  phone-specific bypass (27.2); tenant isolation holds across call,
  session, and tool calls.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: disable the AI receptionist capability and return inbound
  calls to ordinary Phase 8.2 human routing — unchanged from the original
  Phase 9.2's own rollback plan, and must not require a second routing
  system to fall back onto.
- **Outcome**: not started — blocked on prerequisites, corrected
  2026-09-29 (27.1 and 27.2 are now implemented, per their own Outcome
  fields; 27.0 and 27.3 remain not started; see the dependency graph
  above). Not implementation-ready.
- **Checkpoint**: **dedicated security + UX review, performed after this
  phase's own implementation and end-to-end testing are complete and
  strictly before any real tenant's live phone number is enabled** — not a
  standing review folded into a later phase, and not satisfied implicitly
  by any prerequisite subphase's own testing. Must cover, at minimum:
  caller prompt injection, caller spoofing/identity boundary, tenant
  isolation, AI tool authorization, business-action confirmation, duplicate
  actions, transcript/recording PII, external-provider data boundary,
  escalation behavior, human handoff, provider failure, audit completeness,
  and caller UX.

## Phase 28 — Command Center & Navigation Redesign

- **Objective**: the first Layer-3 phase implemented — not cosmetic
  frontend work. Replace the current flat, 15-item technical-module
  navigation and module-launcher dashboard (confirmed today:
  `frontend/lib/nav/config.ts` mirrors the backend router list by its own
  stated design intent; the dashboard shows static filler copy and zero
  real attention-needed items, by its own "renders no fabricated metrics"
  restraint) with an information architecture organized around business
  questions.
- **Business outcome**: when the owner opens the application, they
  immediately understand what matters and what to do next — the "if I
  only have five minutes" test this phase exists to pass.
- **User-visible result**: a Today/Command Center as the landing screen,
  and a grouped navigation replacing the flat module list. Proposed
  top-level concepts (naming subject to UX validation; the underlying
  principle — business jobs, not backend router names — is not): Vandaag
  (Today), Inbox, Klanten (Customers), Agenda, Verkoop (Sales), Marketing,
  Geld (Money, once Phase 25 exists), Instellingen (Settings). Automation,
  AI, Reputation, Templates/Snapshots, Telephony, and Billing do **not**
  automatically become top-level items — each surfaces inside the
  business context where it's relevant (e.g. Automation folds into
  Vandaag as "what the system did for you," plus an advanced "Rules"
  sub-page for power users; Templates/Snapshots becomes "Business Setup,"
  agency-only, never shown to a client tenant — see Phase 21's own note
  on user-facing terminology).
- **Dependencies**: none required to *begin* — this is the phase's own
  key property. Explicitly does not require Phase 24-27 (Accounting, AI
  vendor, live telephony) to exist first; it composes read-only views
  over CRM, Appointments, and Automation run history, all already real,
  today. Its richness grows as Phases 21-27 land (e.g. a "Geld" section
  is empty/hidden until Phase 25 exists), but the phase itself is not
  blocked on them.
- **Scope**: a new Command Center read-model (see "Command Center
  requirements" below); a grouped-navigation frontend restructure; a
  business-language translation layer at the UI edge, extending the
  precedent that already exists and works
  (`frontend/lib/automation/actions.ts`'s `TRIGGER_LABELS`/
  `ACTION_LABELS` maps `crm.contact.created` → "A contact is created,"
  etc.) to every screen currently showing a raw technical label — the one
  confirmed instance to fix first: `send_webhook` → "Send a webhook" has
  no translation today, and the Automation page's own copy ("Automatically
  act when something happens in your tenant") leaks "tenant" directly
  into user-facing text.
- **Command Center requirements**: every item shown must be real,
  queryable data — no fabricated metric, ever (Definition of Done
  requirement E). Minimum composition, each backed by a capability that
  already exists at the data layer today: items requiring approval (once
  Phase 29 exists; empty/hidden until then, never faked); leads awaiting
  first contact (CRM, needs Phase 22's assignment field to be meaningful);
  upcoming appointments (Appointments, real today); customers who haven't
  replied (Conversations thread age, a new query, no new schema);
  automation activity ("what the system handled automatically," reading
  existing `WorkflowRun` history, real today, currently unsurfaced
  anywhere); financial items needing attention (once Phase 25 exists).
- **Security considerations**: a read-only aggregation layer over
  existing, already-authorized data — must query through each domain's
  own existing authorization (no new "read everything" bypass permission;
  the Command Center is not a new privileged read path).
- **Cross-domain integration**: this phase's entire purpose — it is the
  first UI surface that reads across CRM, Appointments, Automation, and
  (later) Approvals/Accounting in one place.
- **Tests**: the Command Center shows zero items when the underlying data
  is genuinely empty (proves no fabrication); shows a real item that
  disappears once its underlying condition is resolved (e.g. an
  appointment moves off "upcoming" once it passes).
- **Acceptance criteria**: matches the tests above; a first-time user's
  landing screen contains zero backend module names.
- **Rollback**: standard — a frontend-only phase; the old navigation can
  be restored without any backend change.
- **Outcome**: substantially implemented, corrected 2026-09-22 (this
  entry previously said "not started," which is no longer true).
  **Implemented and verified in the repository**: `c58edb2` ("feat: add
  command center and business navigation") built the Command Center
  read-model (`frontend/lib/dashboard/commandCenter.ts`,
  `frontend/components/today/{AttentionSection,RecentActivitySection,
  UpcomingAppointmentsSection}.tsx`), the grouped, business-labeled
  navigation this entry's own "User-visible result" describes
  (`frontend/lib/nav/config.ts`: Vandaag/Inbox/Klanten/Agenda/Verkoop/
  Marketing/Geld/Instellingen, with Automation/Reputation/Templates kept
  out of the top level exactly as scoped), and both named
  translation-layer fixes (`send_webhook` → "Notify a connected app" in
  `frontend/lib/automation/actions.ts`; the automation page's "tenant"
  copy → "your business"). `4cc23d8`/`3000591`/`77e35fe` later added a
  real Reputation nav entry under Klanten, and `7cce234` added the
  Goedkeuringen/Approvals group this entry anticipated for Phase 29.
  **Not yet done, and not claimed here**: Templates/Snapshots does not yet
  have its own "Business Setup" nav placement this entry's own Objective
  names (`frontend/lib/nav/config.ts` has no `templates`/`snapshots` key
  today — Phase 21's snapshot feature is reachable only through
  `CreateClientForm`, not through navigation).
  **Update, corrected 2026-09-27**: the English/HighLevel target-navigation
  migration named below as future work has since shipped — `8d60528`
  ("feat: align navigation with dashboard IA") gave every nav item a
  `labelEn` alongside its Dutch `label` (`frontend/lib/nav/config.ts`),
  live-toggled by the NL/EN control in the shell (`Navigation.tsx`), and
  the English set matches the Product Reset section's target concept list
  exactly: Dashboard/Inbox/Customers/Sales/Calendar/Growth/Automations/
  Accounting/Reputation/AI/Manage. This is a bilingual toggle, not a
  wholesale replacement of the Dutch labels — both are live today. The
  Templates/Snapshots "Business Setup" nav placement remains the one
  item from this phase's own Objective not yet done.
- **Checkpoint**: the UX-validation checkpoint below is superseded by
  what actually shipped — real Dutch business labels are live in
  production today, not merely proposed, so "before committing to final
  naming" has already happened in effect. What remains open is only the
  Templates/Snapshots "Business Setup" nav placement — the English-
  navigation item once listed here as open is done, per the update above.
  Original text, kept for history: "UX validation of the proposed
  navigation labels with real users before committing to final naming —
  the principle (business jobs, not module names) is mandatory; the exact
  Dutch/English labels are not."

## Phase 29 — Approval Inbox

- **Objective**: surface the existing, complete, currently-unused SaaS-OS
  approval workflow — `control_plane.approvals.propose_action()` →
  `approve()`/`reject()` → `execute_approved()`, gated by `autonomy_tier`
  in `control_plane.orchestration` — so AI and Automation can propose
  risky actions without silently performing them.
- **Business outcome**: the owner reviews and approves what the system
  wants to do before anything financial, customer-facing, or irreversible
  happens — trust without needing to supervise everything.
- **User-visible result**: one screen listing pending proposals, each
  showing the affected business object, the proposed action, the reason/
  context, and approve/reject buttons; a resolved proposal shows its
  execution result.
- **Dependencies**: none at the infrastructure level — `control_plane
  .approvals` is already fully built and audited by SaaS-OS. The
  practical dependency is Phase 26 (the first real tier-1-worthy AI
  action) or Phase 25 (the first real tier-1-worthy financial action) —
  whichever lands first supplies this phase's first real example.
- **Scope**: **do not build a new approval system.** A read/act UI and
  thin API surface over `list_approvals()`/`get_approval()`/`approve()`/
  `reject()` exactly as SaaS-OS already implements them; the first useful
  tier-1 example is expected to be "AI-drafted customer reply → human
  approval → send" (Phase 26) or "post this financial entry" (Phase 25) —
  either is an acceptable first example, not both required simultaneously.
- **Security considerations**: none new — `execute_approved()` already
  enforces proposer ≠ approver (`SelfApprovalNotAllowedError`) and
  audit-logs under the proposer's own identity, never the approver's.
  This phase's own job is not weakening any of that in the UI translation
  layer (e.g. never letting a UI "quick approve" bypass the real
  `approve()` call).
- **Cross-domain integration**: this phase is itself the integration —
  whatever domain proposed the action (AI, Automation, later Accounting)
  is unaffected by how the approval is presented.
- **Tests**: a proposed action does not execute until approved; a
  rejected action never executes; the approver's identity is never
  recorded as the actor of the executed action.
- **Acceptance criteria**: matches the tests above; at least one real
  tier-1 action exists and has been approved end-to-end by a real user
  in a test environment.
- **Rollback**: standard — a UI/thin-API phase; SaaS-OS's own
  infrastructure is unaffected by removing this surface.
- **Outcome**: implemented, corrected 2026-09-27 (this entry previously
  said "not started") — `7cce234` ("feat: add approval inbox"):
  `product/approvals/routes.py` (thin API over `list_approvals()`/
  `get_approval()`/`approve()`/`reject()`) and
  `frontend/app/(app)/t/[tenantId]/approvals/{page.tsx,[approvalId]/page.tsx}`
  are both real; the Goedkeuringen/Approvals nav group Phase 28's own
  entry anticipated is live.
- **Checkpoint**: none beyond confirming no product-side authorization
  shortcut was introduced around the existing SaaS-OS mechanism.

## Phase 30 — Unified Inbox

- **Objective**: one thread model across every communication channel,
  closing Conversations' two confirmed gaps: identity resolution is
  email-keyed only today (no phone-based match for SMS/call), and
  `create_thread()` requires an already-existing `contact_id` rather than
  resolving one from an inbound message the way Marketing/Appointments
  already do.
- **Business outcome**: the owner has one place to see and respond to
  every conversation, regardless of channel, with the right customer
  context already attached.
- **User-visible result**: an inbound SMS or call from an unknown number
  creates a real, matched (or newly created) CRM contact and a real
  thread — the same way an inbound email or web form already does.
- **Dependencies**: Phase 5 (Conversations), Phase 26 (AI summaries/
  suggested replies — tools already exist, `conversation_summarization`/
  `suggested_reply`, unwired to any UI and non-functional pending a
  vendor), Phase 29 (sending an AI-drafted reply is a tier-1 action).
- **Scope**: a tenant-scoped inbound-identifier **correlation** mechanism
  (reusing `product/foundation/values.py::PhoneNumber`, already exists,
  correctly reused, not rebuilt) — **not** a variant of
  `create_or_update_contact_from_trusted_source()`, and not a lookup that
  resolves, attaches to, or updates an existing contact's trusted fields
  from a caller-supplied identifier; see `docs/ADR/0018-...`'s own point 8
  clarification for the exact, narrow boundary this must satisfy
  (correlation for conversation/thread continuity only, never identity
  verification, ownership proof, or authorization). `create_thread()`
  gains an auto-resolve-or-create path for inbound messages with no
  pre-existing contact, built on that same correlation mechanism, with any
  newly-associated contact remaining explicitly unverified (ADR-0018 point
  8); AI summaries/suggested replies surfaced in the Conversations UI as
  tier-0 read-only suggestions (unchanged tier) with sending itself gated
  at tier-1 via Phase 29 once a vendor exists; **explicitly do not claim
  any provider is already available** — SMS/WhatsApp remain Protocol-only
  (`FakeSmsProvider`, no real vendor) exactly as confirmed today; this
  phase's channel-agnostic thread model must not silently assume a
  provider exists.
- **Security considerations**: governed by `docs/ADR/0018-inbound-phone-
  caller-contact-trust-boundary.md` (its Decision point 8 specifically) —
  a carrier-supplied inbound identifier is tenant-scoped correlation data
  only, never authentication, identity proof, ownership proof, or an
  authorization signal; also mirrors Phase 22's own anonymous-write-path
  review for the same "narrow, documented, never broadened casually"
  discipline.
- **Cross-domain integration**: Conversations → CRM (tenant-scoped
  inbound-identifier correlation, new — see ADR-0018 point 8), Conversations
  → AI (summaries/drafts, new), Conversations → Approvals (send-gating,
  new, via Phase 29).
- **Tests**: an inbound SMS from an unknown number correctly resolves to
  an existing contact by phone, or creates a new one, exactly once
  (idempotent under retry); a drafted AI reply never sends without
  passing through Phase 29's approval path.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: each new resolution path/UI surface is independently
  disableable; falls back to today's exact behavior (manual thread
  creation against a known contact).
- **Outcome**: backend foundation implemented, per this phase's own Scope
  note above (correlation mechanism + auto-created threads only) — not
  this phase's full scope. `product/crm/contacts.py
  ::create_or_reuse_contact_from_trusted_source_by_phone()` (tenant-scoped
  phone correlation via the existing `PhoneNumber`/`normalize_phone_number()`,
  create-or-reuse, never mutates a matched contact's trusted fields —
  ADR-0018 point 8) and `product/conversations/threads.py
  ::create_thread_from_trusted_inbound()` (sms/whatsapp/call channels,
  thread reuse per `(tenant_id, contact_id, channel)`; existing
  `create_thread()` unchanged). Both concurrency-safe under duplicate
  inbound delivery via `infra.db.acquire_tenant_advisory_lock()` (neither
  lookup is backed by a unique constraint; no migration added). New edge
  `product.conversations -> product.crm`, narrowly scoped and import-linter
  enforced (`docs/ADR/0019-conversations-depends-on-crm.md`; `lint-imports`
  24 contracts kept, 0 broken). 17 integration tests added
  (`tests/crm/test_trusted_inbound_phone_integration.py`,
  `tests/conversations/test_trusted_inbound_integration.py`) — not yet run
  against a real database in this environment (no `DATABASE_URL`
  configured); `ruff`/`pyright`/`lint-imports` all pass. **Not built**:
  frontend Unified Inbox UI, AI summary/suggested-reply wiring into
  Conversations, Phase 29 approval-gated sending, and no SMS/WhatsApp/call
  provider, webhook, or vendor selection (unchanged from before this
  phase).
- **Checkpoint**: none beyond Phase 22's own standing anonymous-write-path
  review, re-applied here.

## Phase 31 — Platform Ownership Foundation

*(Added 2026-09-30, following a dedicated read-only architecture audit of
the Owner → Agency → Client model. This phase is an architectural
**prerequisite** — it decides and documents a boundary; it does not itself
ship platform-owner functionality. It must not be read as adding scope to
Phase 3, which remains complete and unchanged.)*

- **Objective**: define and establish the architectural boundary for a
  SaaS platform owner above agency tenants, while preserving the existing
  Agency → Client tenant hierarchy and tenant isolation exactly as Phase 3
  already implemented them.
- **Existing foundation (verified by audit, unchanged by this phase)**:
  - Tenant hierarchy already exists and supports arbitrary structural
    depth: `core.tenants.parent_id` (nullable, self-referential) plus the
    precomputed `core.tenant_ancestry` closure table
    (`docs/ARCHITECTURE.md` §3).
  - Agency → Client is already fully implemented: `provision_agency()`
    creates a root tenant (`parent_id IS NULL`); `provision_client()`
    creates a child tenant (`parent_id = agency_tenant_id`). This is real,
    tested, working product capability today — not a future phase.
  - `SUBTREE` role scope (`core/rbac/scope.py`) already lets an agency
    owner administer every descendant client automatically, re-evaluated
    live against the current hierarchy on every authorization check. This
    mechanism is general-purpose (confirmed by direct inspection of
    `core/rbac/authorization.py::can()`) — it is not billing-specific,
    even though Phase 13 is one of its consumers.
  - Client isolation is already enforced and tested: a client tenant is
    isolated from sibling clients exactly as any two unrelated tenants
    would be; hierarchy grants no ambient access by itself.
  - No platform-owner layer currently exists in any form: every agency is
    an independent root tenant with no common ancestor; SaaS-OS's own
    `core/rbac/principal.py` explicitly records `PLATFORM_OPERATOR` as
    considered and rejected ("still out of scope, architecture
    research"); the frontend has only a flat per-tenant context
    (`frontend/lib/tenant/tenant-context.tsx`), no platform context.
- **Required decision (this phase's actual deliverable)**: choose between
  two architectures for platform-level authority. **Neither is selected
  by this roadmap entry** — the decision is this phase's own scoped work,
  informed by the considerations below, not pre-judged here:
  - **Option A — Platform tenant + existing hierarchy.** Introduce a
    platform root tenant that every agency becomes a descendant of,
    reusing the existing `SUBTREE` mechanism unchanged. Must investigate:
    platform tenant representation; platform owner membership; agency
    reparenting (`core.tenancy.move_tenant()`) and its safety against
    every existing agency/client tenant; authorization consequences of a
    3rd hierarchy level; auditability; support-access interaction; tenant
    context implications for the frontend.
  - **Option B — Dedicated platform principal/authorization.** Introduce
    a platform-wide principal/authorization concept (e.g. a
    `PLATFORM_OPERATOR` principal type) without requiring agencies to
    become descendants of a platform tenant. Must investigate: principal
    model; authorization semantics; resource boundaries; auditability;
    interaction with existing tenant authorization; support access;
    whether a platform principal is actually justified over Option A.
  - Or another architecture, only if repository evidence gathered during
    this phase establishes it is genuinely better than both.
- **Decision recorded, 2026-09-30 — Option A selected**, `product/platform
  /provisioning.py`'s own module docstring carries the full evidence-based
  record; summarized here: Option B is rejected because
  `core/rbac/principal.py::PrincipalType` is a closed three-member
  `StrEnum` (`USER`/`SYSTEM`/`SERVICE_ACCOUNT`) that `core/rbac
  /authorization.py::can()` dispatches on directly — a genuine
  platform-wide principal would require a fourth enum member and a new
  `can()` branch, a SaaS-OS change this phase's own hard scope forbids
  ("If Option B would require changes to SaaS-OS authorization
  primitives, STOP and report"). Option A needs none of that: a platform
  tenant is created through the exact same already-public
  `core.tenancy.create_tenant()`/`core.rbac.create_role()`/
  `assign_first_role_for_new_tenant()` calls `product/agency
  /provisioning.py::provision_agency()` already uses for an agency
  tenant — zero new SaaS-OS surface, zero new table, zero new migration.
- **Required properties**: whichever architecture is selected must
  preserve — existing Agency → Client hierarchy; existing client
  isolation; existing `SELF`/`SUBTREE` semantics unless deliberately and
  explicitly changed; fail-closed authorization; explicit (never implicit
  or inherited-by-accident) platform-level authorization; tenant
  isolation; auditability; no client-controlled authorization; no
  accidental platform access to sensitive tenant resources; no broad
  bypass of existing RBAC; compatibility with every existing agency and
  client tenant; deterministic provisioning; a safe, reviewed migration
  path for existing tenants if Option A is chosen.
- **Explicit non-goals of this phase**: no Platform Owner UI; no `/owner`
  frontend route; no billing UI; no Phase 13 API wiring; no UI-14
  implementation; no Agency/Client redesign (Phase 3 is unchanged); no new
  billing functionality; no invoices/payment history; no Stripe checkout
  work; no SaaS-OS implementation (this is a roadmap/decision phase, not
  an implementation phase); no migration implementation; no frontend
  implementation.
- **Dependencies**: Phase 3 (Agency / Client Management — the foundation
  this phase builds a layer above, unchanged and not reopened).
- **Relationship to Phase 13 / UI-14**: none, deliberately. Phase 13
  (SaaS Resale / Billing) and UI-14 (its UI) concern agency-level billing
  ownership (`core.billing.resolve_billing_owner()`), a separate concern
  from platform-level administrative authority. **Updated 2026-09-30**:
  UI-14 is no longer blocked — Phase 13's router is wired (13.4) and
  UI-14 itself is now implemented (see that phase's own Outcome) — but
  this was never this phase's own dependency either way: this phase is
  not a new dependency of UI-14, and UI-14 is not a new dependency of
  this phase.
- **Downstream, not scoped here**: a future platform-owner UI/
  administration phase, once this phase's decision lands, may eventually
  provide things such as agency administration, platform-level
  subscription visibility, platform plans, platform usage, support
  administration, platform configuration — named here only so the
  direction is visible; no screens or implementation requirements are
  defined by this entry.
- **Security considerations**: this phase decides an authorization
  boundary that, if built incorrectly, could grant one platform-wide
  identity implicit access to every tenant's data — the decision itself
  (not merely its eventual implementation) is the security-relevant
  artifact and should be reviewed as such before either option is built.
- **Tests**: `tests/platform/test_provisioning_integration.py` (bootstrap/
  resolve round-trip, one-time-bootstrap refusal, and — the single most
  important safety property — a direct assertion that an existing agency's
  own `core.tenant_ancestry` is completely unchanged after the platform
  tenant is bootstrapped) and `tests/platform/test_authorization_
  integration.py` (platform-owner authorization works and is
  deterministic; an agency owner gains no platform authority and a
  platform owner gains no reach into a pre-existing agency; sibling
  agencies remain isolated; explicit deny still overrides an otherwise-
  valid platform-owner role; a plain tenant placed under the platform
  tenant is reached by the existing `SUBTREE` role with zero further code
  change). 12 integration tests, all passing against a real disposable
  PostgreSQL/Redis. Regression: `tests/agency` (40 tests) and
  `tests/billing` (35 tests) re-run unmodified and unaffected — 75 passed.
- **Acceptance criteria**: matches the Tests above.
- **Rollback**: not applicable at the mechanism level (no schema/migration
  exists to roll back — `product/platform/` adds zero tables); operationally,
  unsetting `PLATFORM_TENANT_ID` and leaving the bootstrapped tenant in
  place returns every `has_platform_authority()` caller to `False`
  (module docstring), with no effect on any agency or client tenant.
- **Outcome**: implemented — foundation only, per this phase's own scope.
  `product/platform/{__init__,errors,roles,provisioning,authorization}.py`:
  `bootstrap_platform_tenant()` (one-time, not self-service, not wired to
  any route), `get_platform_tenant()` (resolves via the `PLATFORM_TENANT_ID`
  env var, never a name lookup — `core.tenants.name` has no uniqueness
  constraint and an ordinary agency signup could otherwise collide with a
  reserved name), `has_platform_authority()`/`require_platform_authority()`
  (delegate entirely to the existing `core.rbac.can()`, no second
  authorization engine). Zero existing agencies reparented — the
  bootstrapped platform tenant's own subtree contains nothing but itself
  until a future, separately-scoped phase deliberately places a tenant
  under it. Zero migrations. `pyproject.toml`'s import-linter contracts
  extended with `product.platform` as a fully independent module (0
  product-module dependencies, mirrors `product.billing`) —
  `lint-imports` passes, 22 contracts kept. **Not built, by this phase's
  own explicit non-goals**: a second platform owner (deliberately
  documented as a provisioning gap in `bootstrap_platform_tenant()`'s own
  docstring — needs the ordinary `assign_role()` path exercised by an
  existing platform owner, not a bootstrap-only shortcut), any HTTP route,
  any UI, any Core-owned capability (invitation/delegation/deny/support
  access) granted to the `platform_owner` role.
- **Completion audit and correction, 2026-09-30**: the Outcome above left
  a real gap this audit found and closed. A platform tenant and a
  platform owner existing as a *sibling* root of every agency does not,
  by itself, let the platform owner administer any agency:
  `core/rbac/authorization.py::can()`'s `SUBTREE` walk is evaluated from
  the *target* tenant upward through its own live `core.tenant_ancestry`
  chain, so the platform owner's `SUBTREE` role only ever reaches a tenant
  that is a genuine descendant of the platform tenant — which, per the
  Outcome above, no agency was. `has_platform_authority()` compounded
  this: it only ever evaluated `can()` against the platform tenant itself,
  so it could not even *ask* the question against another tenant, even
  after one was made a descendant.
  - **Core question answered**: yes — under Option A, an Agency must be a
    genuine descendant of the platform tenant in `core.tenant_ancestry`
    for the platform owner's existing `SUBTREE` role to reach it through
    the unmodified `can()` chokepoint. No lesser mechanism (a helper that
    only checks authority at the platform tenant itself, as the original
    `has_platform_authority()` did) provides an equivalent relationship.
  - **Fix, both additive, no new authorization engine**:
    `has_platform_authority()`/`require_platform_authority()` gained an
    optional `tenant_id` parameter (default: the platform tenant itself —
    every prior call site and test unchanged) so a caller can ask whether
    the platform owner's authority reaches a *named* tenant, not only the
    platform tenant. `product/platform/provisioning.py::
    attach_agency_to_platform()` is the new function that actually
    establishes the edge: gated (`(platform.administration, administer)`
    required — the ordinary anti-amplification discipline
    `provision_client()` already uses), refuses to move anything but an
    Agency root (`PlatformSelfAttachError`,
    `PlatformAttachTargetNotRootTenantError`), idempotent, and delegates
    the move itself entirely to the unchanged, already-public
    `core.tenancy.move_tenant()` — which preserves the Agency's tenant id,
    memberships, roles, and every Client already beneath it exactly
    (`move_tenant()`'s own docstring: hierarchy-only, never tenant-owned
    data; ancestry rows internal to the moved subtree are untouched).
    Audited by this function itself (`core.audit_log.record()`), since
    `move_tenant()` writes no audit record of its own.
  - **Existing agencies**: NOT bulk-reparented. Neither `core.tenancy` nor
    `product.agency` publishes a listing of every root tenant in the
    system (an agency has no owning row of its own to enumerate —
    `product/agency/provisioning.py`'s own module docstring: "Neither
    concept has its own database table"), and adding one would itself be
    a SaaS-OS change this phase's hard scope forbids. `attach_agency_to_
    platform()` instead takes one explicitly-named Agency `tenant_id` at a
    time — an operator (an existing platform owner) supplies it, exactly
    as they already must know it to perform any other one-off operational
    action against that agency. This is the smallest safe migration
    mechanism, not a blocker: every existing agency is attachable, one
    call each, whenever an operator chooses to.
  - **New agency provisioning**: deliberately left unchanged.
    `product/agency/provisioning.py::provision_agency()` still creates a
    root tenant with no parent. Wiring it to auto-attach under the
    platform tenant would require `product.agency` to import
    `product.platform` — forbidden by this repository's own enforced
    import-linter contract ("Agency does not depend on any product module
    except Templates", confirmed by reading `pyproject.toml` and
    `lint-imports`'s own passing output directly), and would also entangle
    ordinary self-service agency signup with platform-tenant availability,
    which this phase's own scope ("not every future platform operation")
    does not authorize. New agencies remain independent roots by default,
    exactly like existing ones, and become attachable through the
    identical `attach_agency_to_platform()` call whenever an operator
    chooses to — attachment is deliberate, never automatic, for both.
  - **Security checks performed**: an attached Agency's own owner gains no
    reach toward the platform tenant or any sibling Agency (`can()` only
    walks a target's ancestors upward; the platform tenant is now the
    Agency's ancestor, never the reverse) — verified directly. A deny
    grant registered by the Agency's own owner, at the Agency tenant,
    still overrides the platform owner's inherited `SUBTREE` allow at that
    one Agency, and only that one — verified directly. Sibling Agencies,
    attached or not, remain mutually isolated — verified directly.
  - **Files changed**: `product/platform/{provisioning,authorization,
    errors}.py` (additive changes only — no removed behavior);
    `tests/platform/{test_provisioning_integration,
    test_authorization_integration}.py` (new tests; no existing test
    modified). No SaaS-OS file changed. No migration added.
  - **Tests**: the 12 pre-existing integration tests plus the new ones
    above, all passing against a real disposable PostgreSQL/Redis
    (`pytest tests/platform tests/agency -m "integration and not
    temporal"`) — see this phase's own git history for the exact count;
    `tests/agency` re-run unmodified and unaffected (regression check).
    `ruff check`/`ruff format --check`/`pyright`/`lint-imports` all pass
    (22 import-linter contracts kept, unchanged).
- **Checkpoint**: dedicated architectural review of this corrected
  Option A relationship, before any future phase (a second platform
  owner, an HTTP route, a bulk/automatic attachment mechanism) builds on
  top of this foundation.

## Vertical slices (tracked independently of module phases)

The audit found these five slices to be the right lens for measuring real
progress — a phase-by-phase reading of this roadmap can look complete
while none of these actually close end-to-end. Tracked here so that
doesn't happen silently again.

| Slice | Path | Closed by |
|---|---|---|
| **A — Lead → Customer** | Capture → identify → qualify → assign → follow up → appointment → customer → onboarding | Capture/identify: done (Phase 4/6/7). Assign: Phase 22. Qualify (real AI): Phase 26. Follow-up/appointment: done (Phase 7/10.2). Onboarding: not yet scoped — needs a "conversion" concept this roadmap does not yet name as its own phase; flag before Phase 25 assumes it exists. |
| **B — Inbound AI Call** | Call → identify → understand → respond → perform permitted action → update CRM → follow up | Entirely Phase 27, depends on Phase 26. Not started; correctly last. |
| **C — Customer Lifecycle** | Appointment → reminder → attendance → completion/no-show → review → follow-up | Phase 23 closes this almost entirely. |
| **D — Revenue** | Sale → invoice → payment → allocation → accounting → reporting → exception | Phase 24 (ledger) → Phase 25 (documents, with its mandatory event/consumer requirement) → Phase 16 (reporting, not started, unchanged). |
| **E — Agency Provisioning** | Create client → apply Business Setup → configure defaults → activate → client ready to operate | Phase 21 closes "apply Business Setup" and "activate." "Configure defaults" beyond CRM pipelines (website, automation templates) is explicitly deferred — Phase 21's own scope note. |

## Product maturity model

Added so the product's current state is described honestly rather than
claimed. Do not mark Level 4/5 achieved anywhere in this document until
the evidence exists — the same discipline this reconciliation just
applied to Phases 8–14's stale status fields.

1. **Records** — the system stores business information. *(Achieved,
   every Layer-2 engine.)*
2. **Workflows** — the system moves information between processes
   automatically. *(Partially achieved — real inside Automation's own
   trigger reach (CRM/Appointments/Telephony); Phases 21-23 extend it to
   Marketing/Websites/Reputation.)*
3. **Assistance** — the system recommends what should happen next.
   *(Substrate exists — Phase 9's tools — but produces no live output
   anywhere yet; Phase 26 is what actually achieves this level.)*
4. **Controlled autonomy** — the system performs low-risk work
   automatically and asks approval for risky work. *(Not achieved —
   `autonomy_tier` infrastructure exists and is fully unused; Phases 26
   and 29 together are what would first achieve this level.)*
5. **Intelligent business operations** — the system continuously
   coordinates customer, communication, appointments, sales, money, and
   administration with humans remaining in control. *(Not achieved; the
   long-run target this entire Smart Business Experience direction is
   sequenced toward, not a near-term claim.)*

**Current honest assessment: solidly Level 1, partially into Level 2.**

## Technical / Documentation Debt

Tracked separately from phase status so a debt item is never mistaken for
an implementation gap, and vice versa.

1. This document's own "Outcome" status was stale for Phases 8–14 (and,
   less severely, never individually filled in for Phases 1–7) until the
   2026-09-22 reconciliation above. Re-check this document against
   `git log` at every future phase checkpoint, not just when an audit
   forces it.
2. `docs/ARCHITECTURE.md` §5.1 previously stated 10.3A/10.4A were "not
   started"/"no such registry exists" — both are built (`a4112da`,
   `18906b2`). **Corrected** in the 2026-09-22 Product Reset documentation
   pass: §5.1 now states the registry, the 9.4 gate, and the 10.4A action
   all exist, and that the one remaining gap is a real LLM vendor (Phase
   26), not the registry or the wiring. Resolved, kept here only as a
   record of the correction.
3. **RESOLVED / STALE (corrected 2026-09-27, Phase 24 readiness audit).**
   This item previously claimed `core.crypto` is assumed available
   ("Category A, fully implemented") in `docs/ACCOUNTING-SCOPE.md`,
   `docs/RESPONSIBILITY-MATRIX.md`, `docs/SECURITY-PRIVACY.md`, and
   `docs/INTEGRATIONS.md`, but **does not exist in the pinned SaaS-OS
   commit** (`1d6fd07a0c3ce2dd8a12c09dac86b019781ee6c6`) — that citation
   was a commit this repository was never actually pinned to.
   `pyproject.toml`/`uv.lock` pin `78f03b33cab90d0b5d0a06606288f861c5cf46f7`,
   confirmed by direct inspection. The Phase 24 audit fetched that actual
   pinned commit directly from the SaaS-OS repository (outside this
   working tree) and confirmed **`core/crypto/` exists there in full** —
   a real `EncryptionService`/`KeyProvider`, with its own test suite, per
   SaaS-OS's own ADR-0019. `docs/ACCOUNTING-SCOPE.md`,
   `docs/RESPONSIBILITY-MATRIX.md`, `docs/SECURITY-PRIVACY.md`, and
   `docs/INTEGRATIONS.md` were correct to assume it available; this
   item's own original "correction" was the stale one. Kept here,
   corrected in place, as a record — never silently deleted, per this
   section's own "a debt item is never mistaken for an implementation
   gap" discipline. Phase 24's own scope (accounts/periods/journals)
   needs no field-level encryption regardless — no tax identifier or bank
   account number exists in that scope; `core.crypto`'s availability
   matters for Phase 25's customer/supplier records instead.
   **Separately, an environment-sync gap, not an architecture blocker**:
   the locally installed `.venv` at audit time referenced yet a third
   commit (`8b7ebc0d825b3b17b949ade14f8ef8ad75af14a9`) — matching neither
   the real pin nor this item's original stale citation, and not itself
   evidence about what the pinned commit contains. Re-sync the local
   environment against the real pin (e.g. `uv sync`) before any Phase 24
   code is written, as an implementation-preparation step, not a roadmap
   dependency.
4. Durable events (`publish_durable()`/`subscribe_durable()`,
   `product/foundation/events.py`) exist with **zero real callers**
   anywhere in the product today — every real domain event uses the
   plain, synchronous path. Not a defect; worth knowing before reaching
   for the durable path out of habit rather than a demonstrated
   cross-restart/cross-process need.
5. No step-output-chaining exists in durable Automation runs — the
   structural blocker Phase 26 exists to close.
6. **Resolved.** `Opportunity` previously had no owner/assignment field;
   Phase 22 closed this (`product/crm/models.py::Opportunity
   .assigned_user_id`, migration 0049). Kept here only as a record.
7. **Resolved.** `frontend/lib/nav/config.ts` previously mirrored the
   backend router list by its own stated design intent; Phase 28
   (`c58edb2`) superseded this with the grouped, business-labeled
   navigation described in that phase's own corrected Outcome field
   above. Kept here only as a record.
8. One raw backend validation string
   (`"trigger_type must be one of the supported event types."`) surfaces
   verbatim in the Automation UI (`CreateWorkflowForm.test.tsx:80`) — a
   small, concrete instance of the terminology-leak pattern Phase 28's
   translation-layer work should also sweep for and fix, beyond the two
   items already named in Phase 28's own scope.

## Recommended strategic sequencing

Two groups, deliberately allowed to overlap where dependencies permit —
the objective is not "finish every backend module first," it is
progressively closing complete end-to-end business journeys:

- **Business-engine completion** (21–27): closes named gaps in engines
  that already exist.
- **Smart Business Experience proper** (28–30): the first genuinely new
  Layer-3 work.

**Phase 28 may be implemented before 24–27** if the product strategy
prioritizes visible user experience over backend completeness — it
requires none of Accounting, a live AI vendor, or a live telephony
provider to begin, only composition over CRM/Appointments/Automation data
that is real today. This is not a silent reordering: every dependency
Phase 28 actually has is stated in its own Dependencies field above (in
short: none, to begin). Phase 29 similarly requires no new infrastructure,
only a first real tier-1 action from either Phase 25 or Phase 26 to have
something concrete to approve. Recommended if forced to choose one first:
**Phase 28**, on the reasoning stated in its own Business outcome field —
it is the single highest-leverage change against the product's own
stated quality bar ("can a normal SME owner open this and get work done
without understanding the architecture"), at the lowest implementation
risk of any phase in this section.

**Update, 2026-09-22 (post Product Reset).** The recommendation above has
already been acted on: Phase 21 and Phase 22 are implemented and
committed, and Phase 28 is now substantially implemented (see Phase 28's
own corrected Outcome field above — `c58edb2` and follow-on commits). With
that leverage taken, the next recommended direction is **Phase 23
(Customer Lifecycle Loop)** — it closes the one remaining named gap in
the already-shipped Appointments/Reputation engines (lifecycle events,
`no_show` status, the completion → review-request subscriber), requires
none of Accounting, a live AI vendor, or live telephony, and is the
natural continuation of the Product Reset's own Core business loop
(Appointment → Customer → Review/Referral). This is a sequencing note
only — Phase 23's own scope above is unchanged, and this section does not
implement or redesign it.

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

There is **one** product frontend application, and the audiences this
track's phase titles name (Agency, Client, and the Platform Owner and
Direct Platform Client contexts not yet given their own phases) are
different authenticated user/tenant contexts inside it — not separate
frontend applications. A future UI phase does not open a second frontend
because its feature targets a different audience; it determines which
contexts, permissions, tenant scope and entitlements apply, and the same
application renders accordingly. See
`docs/ADR/0011-one-frontend-multiple-user-contexts.md`.

**Correction, 2026-09-30, updated 2026-09-30**: at the time the paragraph
above was written, "the Platform Owner... context" was described as
symmetrical with the Agency/Client contexts, only "not yet given their
own phase." A dedicated architecture audit found this was not accurate at
the time: every agency was an independent root tenant with no common
ancestor, and SaaS-OS explicitly records a platform-operator principal
type as out of scope. Phase 31 (Platform Ownership Foundation) has since
established the missing tenancy/authorization mechanism itself (a
platform tenant, reusing `SUBTREE`, `product/platform/`) — but strictly as
a foundation: no existing agency is reparented under it, and no frontend
context, route, or UI reaches it yet. "The Platform Owner... context" this
paragraph names is therefore still not a real frontend context today —
only its backend prerequisite now exists. See Phase 31's own Outcome for
the exact boundary.

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
- **Outcome**: implemented, corrected 2026-09-27 (this entry, and every
  other UI-1–UI-9 entry below, previously said "not started" despite the
  UI Track overview table above already marking all nine ✓ — never
  individually verified until now, the same staleness pattern already
  corrected for Phase 8-14 and Phase 21/22/29 above). `frontend/app/
  layout.tsx`, `frontend/lib/nav/config.ts`, and
  `frontend/components/shell/Navigation.tsx` are the real, in-use shell/
  navigation this entry describes.
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
- **Outcome**: implemented, corrected 2026-09-27 (see UI-1's own note on
  this staleness pattern). `frontend/app/dashboard/page.tsx`,
  `components/agency/{CreateClientForm,ClientsList,InviteMemberPanel}.tsx`
  are real. Self-service agency/tenant creation is also real — the
  tenant-less `/dashboard` entry point itself (`app/dashboard/page.tsx`)
  calls `createAgency()` (`lib/api/agency.ts:121` → `POST /v1/agency/
  agencies`) for a user with no tenant yet — but it is a distinct
  lifecycle from this phase's own client-dashboard scope (`CreateClientForm`
  is an existing agency creating a *client*, Phase 21's scope); tracked
  separately as UI-11 below, not duplicated here.
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
- **Outcome**: implemented, corrected 2026-09-27 (see UI-1's own note on
  this staleness pattern) — `frontend/app/(app)/t/[tenantId]/crm/
  {contacts,companies,opportunities,pipelines}` are real.
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
- **Outcome**: implemented, corrected 2026-09-27 (see UI-1's own note on
  this staleness pattern) — `frontend/app/(app)/t/[tenantId]/
  conversations/**` is real.
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
- **Outcome**: implemented, corrected 2026-09-27 (see UI-1's own note on
  this staleness pattern) — `frontend/app/(app)/t/[tenantId]/
  marketing/**` is real.
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
- **Outcome**: implemented, corrected 2026-09-27 (see UI-1's own note on
  this staleness pattern) — `frontend/app/(app)/t/[tenantId]/
  appointments/**` is real.
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
- **Outcome**: implemented, corrected 2026-09-27 (see UI-1's own note on
  this staleness pattern) — `frontend/app/(app)/t/[tenantId]/
  settings/{access,branding,profile,support-access}` are real.
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
- **Outcome**: implemented, completed 2026-10-01 (performance audit
  below; previously "substantially implemented", corrected 2026-09-29 —
  this entry before that said "partially implemented... no dedicated completion
  artifact... do not mark this 'implemented'"; the missing artifact now
  exists). A destructive-action-confirmation audit was run across every
  module: 25 of 28 destructive actions already routed through the shared
  `ConfirmDialog` (`components/ui/Dialog.tsx`); the one real gap found —
  `components/crm/ActivitiesPanel.tsx` task/note delete calling the API
  directly with no confirmation — is fixed (`86023b2`), with a test. The
  other two flagged items (`TagsPanel.tsx` tag-detach, `ContentBlocksEditor
  .tsx` remove-block) were deliberately left unconfirmed — both mutate
  trivially-reversible or unsaved-draft state, not the same severity class
  as "delete contact." `components/ui/Menu.tsx` gained Up/Down/Home/End
  roving focus and focus-on-open/return-on-close, closing its own gap
  against the ARIA menu authoring pattern (`b3c3323`). The CSRF posture
  named in this phase's own Security considerations was verified, not
  patched: `product/api/main.py`'s `CORSMiddleware` allows only the
  explicit `FRONTEND_ORIGINS` allowlist, never `*`, and
  `lib/api/client.ts`'s `request()` always sends `Content-Type:
  application/json` on writes, which forces a CORS preflight an
  attacker's origin fails before any cookie is sent — the actual defense
  here, not a missing double-submit token. A dedicated keyboard-navigation
  and screen-reader pass was then run for real across representative
  pages (Dashboard, CRM, Conversations, Marketing, Appointments, Settings/
  Agency) — every interactive element is a real `<button>`/`<Link>`, every
  input carries a label or `aria-label`, no `<div>`/`<span onClick>`
  without a role, no missing alt text (no images exist in these
  data-driven screens) — and found the codebase already compliant, with
  zero further fixes needed (706 tests, `tsc --noEmit` clean). **Updated
  2026-09-30**: a dedicated responsive audit was then run across the
  shell, design-system primitives, and every domain module (`AppShell`/
  `TopBar`/`Navigation`, `Dialog`/`ConfirmDialog`, `SidePanel`,
  `DataTable`, `Menu`, `FormRow`, sub-nav tab strips, calendar day/week/
  month/agenda views, `states.tsx`, the root layout's viewport meta, and
  the global `prefers-reduced-motion` rule) — almost all of it was already
  correctly responsive (mobile overlay sidebar with proper focus/tab-order
  handling, mobile bottom-sheet side panels, horizontally-scrollable
  tables, a single canonical breakpoint enforced by `app/design-system
  .test.ts`). One real, concrete defect was found and fixed (`a53574c`,
  "fix: harden responsive navigation shell"): `AppShell`'s `topnav` layout
  — an alternate, tested-but-not-production-selected shell arrangement —
  had a mobile nav toggle with a dangling `aria-controls` reference and no
  overlay for it to open at all, so a mobile user under that layout could
  not navigate; fixed by mounting the same scrim/`aside`/`Navigation`
  overlay pattern the `sidebar` layout already uses, with a regression
  test. **Updated 2026-10-01**: a read-only audit of `a53574c` then
  reviewed the responsive drawer in both layouts (the fix itself was
  correct) and found three further drawer defects, all now remediated in
  `AppShell.tsx` with tests in `AppShell.a11y.test.tsx`: (F1) the drawer
  stayed open after following a link, because the shell persists across
  route changes — it now closes on a pathname change and moves focus to
  the new page's `main`; (F2) open state survived widening past the
  breakpoint (a second, unclosable vertical nav in `topnav`; a drawer that
  reopened on the next shrink in `sidebar`) — it now closes when the
  `(min-width: 48rem)` media query starts matching; (F3) while open, Tab
  left the drawer for TopBar controls and page content hidden underneath
  it (WCAG 2.2 SC 2.4.11) — Tab/Shift+Tab now cycle between the toggle and
  the drawer's own items, reusing Dialog's focusable-element selector; the
  drawer stays a non-modal overlay (no `aria-modal`, no `inert`). Each
  fix's tests were mutation-checked (fail with the fix disabled). The
  responsive behavior was verified through code review and unit tests
  only — no real-browser verification exists for this frontend. Frontend
  suite 755/755 passing; ESLint and `tsc --noEmit` clean.
  **Performance audit (2026-10-01)**: the dedicated performance pass this
  phase's own Scope names has now been run — an audit only, no source
  change. A production `next build` reports ~102 kB compressed first-load
  JS shared by every route (almost entirely the Next.js/React framework
  chunks), ~124 kB for the tenant dashboard, and ~130 kB for the largest
  route (`/t/[tenantId]/appointments`, whose calendar code is already in
  its own route-only chunk). Next.js route-level code splitting is already
  appropriate: no Accounting, Telephony, or AI feature code (beyond
  navigation labels and the dashboard's overdue-invoices line) is in the
  initial bundle, and the frontend has only three runtime dependencies
  (`next`, `react`, `react-dom`) — no charting, editor, icon, SDK, or date
  library to defer or replace. Source inspection of `AppShell`,
  `Navigation`, `TopBar`, and the locale/session/tenant providers found no
  render path requiring optimization (drawer toggling does not re-render
  the page subtree; provider values are memoized; the F1–F3 listeners
  register once per open/mount and the media-query listener fires only on
  breakpoint crossings). The performance audit found no justified
  implementation work based on production build analysis and source
  inspection. No real-browser performance profiling was performed, so this
  conclusion rests on build output and code, not on runtime LCP/INP/TTI
  measurements.
- **Checkpoint**: review pattern consolidation against `UI-9` before that
  phase starts — `UI-8` is where duplication is found, `UI-9` is where it's
  resolved into reusable components. The responsive-navigation work above
  (`a53574c` plus the F1–F3 remediation) and the performance pass are both
  complete; this entry is now `✓`.

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
- **Outcome**: implemented, corrected 2026-09-27 (see UI-1's own note on
  this staleness pattern) — `frontend/components/ui/**` (`DataTable`,
  `Dialog`, `Badge`, `Card`, `FormRow`, `ApiErrorPanel`, `InlineNotice`,
  and others) are real, shared components in active use across UI-2
  through UI-7.
- **Checkpoint**: review that no component's authorization behavior
  diverges from what the backend already enforces.

## UI-10 — Automation, Websites & Reputation UI

*(Added 2026-09-27 — retroactive numbering for already-shipped work; not
a new plan.)*

- **Objective**: document three full UI surfaces that shipped ahead of
  this roadmap's own UI-1..UI-9 sequence and were never assigned a UI-#,
  leaving them invisible to this document's own tracking discipline.
- **Related backend phases**: Phase 10 (Automation), Phase 11 (Websites),
  Phase 12 (Reputation), Phase 22 (Lead Capture — the website form feeds
  the CRM contact this UI's Websites screens manage).
- **Scope**: workflow list/detail/run-history (Automation); website/page
  management (Websites); review management (Reputation). Documents
  shipped scope only — no AI-vendor, prospecting, or other not-yet-built
  backend capability is claimed here.
- **Evidence**: `frontend/app/(app)/t/[tenantId]/{automation,websites,
  reputation}/**`; git `532c376`, `a187c7d`, `3000591` (previously cited
  only in UI-9's own overview annotation).
- **Outcome**: implemented.
- **Checkpoint**: none — documentation-only correction; no new work is
  proposed by this entry.

## UI-11 — Self-Service Tenant Creation

*(Added 2026-09-27 — retroactive numbering for already-shipped work; not
a new plan.)*

- **Objective**: document the existing self-service agency/tenant creation
  capability distinctly from UI-2's client-dashboard scope and from the
  invitation-based membership flow (Phase 3.2) — the two are frequently
  conflated, and neither the roadmap nor UI-2's own text previously named
  this capability at all.
- **Related backend phase**: Phase 3.1 (`provision_agency()`).
- **Status**: partially implemented — distinguished explicitly below.
- **Implemented**: create a brand-new agency/tenant (`app/dashboard/
  page.tsx` → `createAgency()`, `lib/api/agency.ts:121` → `POST /v1/
  agency/agencies` → `provision_agency()`); the creating user is assigned
  as owner; successful creation redirects to the new tenant's dashboard.
- **Not implemented**: commercial plan selection, trial lifecycle, signup
  billing/checkout (Phase 13's resale billing is never invoked from this
  path), and any guided onboarding wizard beyond the one-field creation
  form. This entry must not be read as a complete commercial signup
  funnel — only the tenant/owner creation primitive is real today.
- **Outcome**: partially implemented.
- **Checkpoint**: if commercial plan/trial/billing-gated signup is ever
  wanted, it is new, separately-scoped future work layered on top of this
  already-real, ungated primitive — not a redesign of it.

## UI-12 — Command Center & Business Navigation

*(Added 2026-09-27 — retroactive numbering for already-shipped work; not
a new plan.)*

- **Objective**: give Backend Phase 28's own UI half (Command Center
  read-model, grouped business navigation) a UI-# so it is visible
  alongside UI-1..UI-9 rather than only inside the backend phase list.
- **Related backend phase**: Phase 28 (Command Center & Navigation
  Redesign — see that phase's own corrected Outcome for the full
  implemented/remaining breakdown, not restated here).
- **Evidence**: dashboard command-center sections
  (`frontend/lib/dashboard/commandCenter.ts`, `components/today/
  {AttentionSection,RecentActivitySection,UpcomingAppointmentsSection}.tsx`),
  `frontend/lib/nav/config.ts`'s grouped, bilingual (NL/EN) navigation.
- **Outcome**: implemented (matches Phase 28's own corrected Outcome).
- **Checkpoint**: none — documentation-only correction.

## UI-13 — Approval Inbox

*(Added 2026-09-27 — retroactive numbering for already-shipped work; not
a new plan.)*

- **Objective**: give Backend Phase 29's own UI half a UI-# for the same
  reason as UI-12.
- **Related backend phase**: Phase 29 (Approval Inbox).
- **Evidence**: `frontend/app/(app)/t/[tenantId]/approvals/{page.tsx,
  [approvalId]/page.tsx}`, `product/approvals/routes.py`.
- **Outcome**: implemented (matches Phase 29's own corrected Outcome). No
  additional approval functionality beyond what Phase 29 documents is
  claimed here.
- **Checkpoint**: none — documentation-only correction.

*(Added — UI Track completion, correcting the "not pre-allocated here" gap
below at "UI Track sequencing." UI-14–UI-21 give the remaining, real
backend capability its own UI-#, the same way UI-10–UI-13 retroactively did
for already-shipped work — at the time this note was added, none of
UI-14–UI-21 was shipped, matching this Track's own standing rule that
Outcome is `not started` until real frontend evidence exists, never
inferred from backend code alone. **Updated 2026-09-30**: UI-14 is now
implemented (see its own Outcome) — the standing rule this note states is
unchanged, only its "none of them yet" snapshot is stale for UI-14
specifically; UI-15–UI-21 remain genuinely not started. Three items
proposed during this correction were deliberately **not** given a new UI-# —
see "Proposed UI phases folded into existing coverage" immediately after
UI-21.)*

## UI-14 — Billing, Plans & Subscription Management

- **Objective**: the user-facing UI for the existing platform-subscription
  backend (Backend Phase 13.1) — plan selection, checkout/payment
  management, invoices, usage/limits, billing administration.
- **Dependencies**: UI-1, UI-7 (settings shell it mounts into); Backend
  Phase 13 (`product/billing/subscriptions.py`, `GET /v1/billing/plans`).
- **Scope**: subscription state display; the existing global-plan catalog
  (`GET /v1/billing/plans`, read-only); subscribe/upgrade/downgrade/cancel
  flows wrapping `core.billing`'s existing mechanism (Phase 13.1's own
  scope, unchanged); usage/entitlement display once Phase 16.3 exposes it.
  Any payment-provider UI beyond what `core.billing`'s Stripe adapter
  already renders stays explicitly out of scope — this UI must not
  reimplement payment-provider checkout, only wrap the existing
  subscription lifecycle calls. **Corrected 2026-09-30**: this entry
  previously excluded agency-defined resale plan *authoring* for clients
  as "a separate future UI" pending Backend Phase 13.2 — by
  implementation time Phase 13 (13.1-13.4, including the `/v1/billing`
  router mount) was fully shipped, and the resale-plan create/edit/
  deactivate routes were already live, so resale-plan authoring is
  implemented as part of this entry rather than deferred.
- **Tests**: subscribe/upgrade/downgrade/cancel through this UI produces
  the same `core.billing` state a direct API call would (no UI-side
  entitlement calculation diverging from the backend's own).
- **Security considerations**: none beyond §6.1's standing rule; payment-
  provider credentials remain `core.billing`'s own concern (Phase 13.1) —
  this UI never handles raw card/payment data itself.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: implemented, corrected 2026-09-30 (this entry previously
  said "not started," which was stale once Phase 13 shipped in full) —
  `frontend/app/(app)/t/[tenantId]/billing/page.tsx` mounts four
  sections: subscription (`components/billing/SubscriptionsPanel.tsx` —
  create/change-plan/cancel, all against a real `idempotency_key`-bearing
  or plan-scoped call), the read-only platform catalog
  (`PlansCatalog.tsx`, `GET /v1/billing/plans`), this tenant's own
  resale-plan catalog with create/edit/deactivate
  (`ResalePlansPanel.tsx`), and effective entitlements, informational
  only (`EntitlementsPanel.tsx`). `lib/api/billing.ts` is the typed
  client, modeled directly off `product/billing/routes.py`'s own request/
  response shapes. The existing, previously-`planned` "Facturatie" nav
  entry (`lib/nav/config.ts`) is now wired to this route. Every mutation
  (create/edit/deactivate/change-plan/cancel) refetches server state
  rather than mutating optimistically; cancellation and deactivation both
  require `ConfirmDialog` confirmation; a 403/tenant-scoped-404 renders
  the same non-enumerating `PermissionDeniedState` every other module
  uses. Tests: 32 focused (23 new Billing + 9 Navigation, one of which
  was updated for the now-real nav entry), full suite 740/740 passing;
  lint/typecheck/build all clean. **Not yet committed** — implemented and
  checkpoint-audited (a full API-contract, tenant-isolation, mutation,
  financial-safety, and accessibility pass, all clean) but left
  uncommitted pending human review, per this roadmap's own standing
  convention of not self-certifying a phase complete.
- **Checkpoint**: the financial-safety review this phase's own Security
  considerations implies — confirm no fake invoice/payment-method/
  Stripe-portal/refund/tax/payment-history surface was introduced (none
  was, confirmed by inspection) — is done; a human review/commit of the
  checkpointed diff is the one thing still pending.

## UI-15 — Accounting & Financial Workspace

- **Objective**: the user-facing accounting workspace for the existing
  Mini Accounting backend (Backend Phases 24–25) — an owner-readable
  "money" view, never a ledger-mechanics screen, per Phase 25's own
  Business outcome framing.
- **Dependencies**: UI-1, UI-7; Backend Phase 24 (chart of accounts,
  periods, journal entries — not started per that phase's own Outcome),
  Backend Phase 25 (invoices, bills, payments, allocations — not started
  per that phase's own Outcome).
- **Scope**: accounting dashboard (outstanding invoices/bills, matching
  Phase 25's own "money view an owner can actually read" acceptance bar);
  transaction/journal-entry read views (Phase 24); invoice/bill/payment
  list and detail views (Phase 25); accounting workflows exactly as Phase
  24/25 define them (draft → posted → voided/reversed journal entries;
  invoice/bill → sent → paid → allocated); no accounting integrations
  beyond what Phase 25 itself scopes (bank feeds and OCR auto-booking are
  explicitly deferred — this UI must not imply either exists). **Correction,
  2026-09-30**: credit notes were previously grouped in this same deferred
  list, citing "Phase 25's own text" — stale, since 15.3 (credit notes) has
  since been implemented under its own sequencing (see that subphase's own
  corrected Outcome). They remain outside this UI phase's own named scope
  above regardless, the same as any other accounting capability not
  explicitly listed — this correction removes the false "deferred" claim
  only, it does not add a credit-note view to this phase's scope.
  Accounting semantics (debit/credit, immutability, period locking,
  invoice numbering) remain owned
  entirely by the backend (Phases 24/25, `docs/ACCOUNTING-SCOPE.md`) — this
  UI renders them, never recomputes or duplicates them.
- **Tests**: displayed balances/statuses derive from posted journal
  entries as the sole source of truth (Phase 25's own non-negotiable
  rule) — never from a UI-side running total; the accounting section
  and UI-16's operational-reporting section remain visibly, structurally
  distinct (mirrors Phase 16.2's own "never conflated" requirement).
- **Security considerations**: none beyond §6.1's standing rule; this is
  financial system-of-record data — the UI must not offer any control
  (edit/delete a posted entry) the backend's own immutability guarantee
  would reject, per Phase 24's security considerations.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started. No `frontend/app/**/accounting/**` or
  equivalent exists today (confirmed by inspection); Backend Phases 24
  and 25 are themselves each `not started` per their own Outcome fields —
  this UI phase cannot begin before at least Phase 24 is stable.
- **Checkpoint**: none until Phase 24/25 are sufficiently stable to build
  against.

## UI-16 — Reporting & Business Analytics

- **Objective**: the user-facing UI for the existing (not yet built)
  Reporting backend (Backend Phase 16) — KPI dashboards and operational
  reporting over CRM/Conversations/Marketing/Appointments/Automation data.
- **Dependencies**: UI-1, UI-3–UI-6, UI-10; Backend Phase 16.1 (operational
  analytics), 16.2 (accounting reports surfacing), 16.3 (usage/entitlement
  reporting) — all three not started per that phase's own Outcome fields.
- **Scope**: KPI/operational dashboards (leads, conversion, pipeline,
  appointments, campaigns, communication — Phase 16.1's own list);
  CRM/Appointments/Marketing/Automation reporting drawn from those
  modules' existing data, never a parallel analytics model; a distinct,
  separately-labeled accounting-reports section wiring in Phase 16.2's
  output once it exists (UI/navigation wiring only, matching 16.2's own
  scope — no new report logic here); usage/entitlement reporting once
  Phase 16.3 exposes it (thin presentation layer, matching 16.3's own
  scope). No metric is invented beyond what Phase 16's three subphases
  themselves define.
- **Tests**: report figures shown match the backend's own report-service
  output against known sample data (Phase 16.1's own test); the
  accounting-reports section remains reachable from a clearly separate UI
  section from operational reporting, never merged into one view (Phase
  16.2's own acceptance criterion, restated here as this UI's own).
- **Security considerations**: none beyond §6.1's standing rule and
  Phase 16's own "standard inherited isolation."
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started. No `frontend/app/**/reporting/**` or
  equivalent exists today (confirmed by inspection); Backend Phase 16 is
  itself entirely `not started`.
- **Checkpoint**: none until Phase 16.1 is sufficiently stable to build
  against.

## UI-17 — Telephony & Call Center

- **Objective**: the user-facing UI for the existing Telephony backend
  (Backend Phase 8, foundation-only) — phone-number management, call
  history/activity, human-transfer/receptionist configuration, provider
  status. **This phase must not be represented as production-complete**:
  Backend Phase 8 itself carries no live call orchestration (8.2's own
  Outcome: "No live call orchestration exists"), and Backend Phase 27
  (Inbound AI Call) is explicitly "not implementation-ready," blocked on
  prerequisites 27.0–27.3, all `not started` per that phase's own Outcome
  fields — regardless of any in-progress implementation work toward those
  prerequisites, this document's own recorded Outcome is the status this
  UI phase defers to (per this Track's standing "do not infer completion
  from backend code alone" rule).
- **Dependencies**: UI-1, UI-3 (caller-ID/contact linkage); Backend Phase
  8.1–8.3 (numbers, routing, call records — foundation/data-model only);
  Backend Phase 27 (Inbound AI Call, live receptionist — not
  implementation-ready) for any AI-handled-call configuration surface.
- **Scope**: phone-number management (Phase 8.1); call history/activity
  views over existing call-record data (Phase 8.3, data-model only — no
  live call populates it today, so this UI phase has nothing real to
  render until at least Phase 8.2's live-orchestration gap closes);
  human-transfer/handoff destination configuration once Backend Phase
  27.3 (or 8.4) delivers a real handoff primitive — configuration UI only,
  never a second handoff mechanism; receptionist/AI-calling configuration
  once Backend Phase 27 is implementation-ready and implemented — this UI
  must render whatever confidence/escalation boundary the backend actually
  enforces, never a UI-invented one; telephony provider configuration
  status, surfaced honestly as provider-neutral until a real
  `TelephonyProvider` is registered (Phase 8.1's own "no real provider
  adapter is registered" caveat) — never dressed up as a working
  integration, mirroring UI-6's own calendar-provider-status discipline.
- **Tests**: this UI never implies a live call capability the backend does
  not actually have (e.g. must not show an "AI receptionist: active"
  state while Phase 27 remains not implementation-ready); provider status
  shown matches the backend's own real/fake provider distinction exactly.
- **Security considerations**: none beyond §6.1's standing rule. Call
  recordings/transcripts are the single highest-sensitivity data type in
  this roadmap (Phase 8.3, Phase 27's own security considerations) — any
  UI surfacing them requires the dedicated security review those phases
  already mandate before this UI phase may render real recording content,
  not merely before the backend stores it.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard; hides cleanly if the underlying capability is
  disabled, matching Phase 8/27's own rollback stance.
- **Outcome**: not started. No `frontend/app/**/telephony/**` (or call-
  center-equivalent) UI exists today (confirmed by inspection). Backend
  Phase 8 is foundation-only (no live orchestration) and Backend Phase 27
  is not implementation-ready — this UI phase has essentially nothing live
  to render yet, independent of this Track's own readiness.
- **Checkpoint**: do not begin building a "live receptionist" configuration
  surface before Backend Phase 27's own dedicated security + UX review
  (that phase's standing Checkpoint) has occurred — this UI phase does not
  get a separate exemption from that gate.

## UI-18 — AI Control Center

- **Objective**: the user-facing UI for the existing AI substrate (Backend
  Phase 9) and AI-vendor/write-back capability (Backend Phase 26) — AI
  capability visibility, tenant AI configuration/policy, usage, and
  activity/audit visibility. **Does not duplicate UI-13** (Approval Inbox,
  which already gives Backend Phase 29's approval surface its own UI-#) —
  this phase covers AI capability/configuration/usage visibility, not the
  approval action itself.
- **Dependencies**: UI-1, UI-13 (the approval surface this phase must not
  re-implement); Backend Phase 9.1–9.4 (tool registrations — 9.1–9.3
  implemented as definitions only, 9.4 the production gate, correctly
  fail-closed, zero live vendor); Backend Phase 26 (AI Vendor + AI
  Write-Back — not started per that phase's own Outcome).
- **Scope**: which AI tools/capabilities exist and their autonomy tier
  (read-only visibility into Phase 9's own tool registry — never a second
  tool-registration UI, per this Track's standing "no new authorization
  surface" rule); tenant AI configuration once a real vendor is registered
  (Phase 26) — vendor status shown honestly as "not configured" until then,
  never implied as active; AI usage visibility once real invocations exist;
  AI activity/audit visibility surfacing `execute_approved()`'s existing
  audit trail (Phase 26's own "Explain" step: "surfacing that trail in a
  form a non-technical user can read") in a form distinct from, and
  linked to, UI-13's own approval-request detail view, never duplicating
  it. Explicitly out of scope: any tier-2/3 autonomy control (Phase 9.1's
  own "never tier 2/3 without a separate, later, evidence-based decision"
  applies to this UI's own controls too, not only the backend's).
- **Tests**: this UI never implies a live AI vendor is active while Phase
  26 remains not started (must render "no vendor configured," never a
  fabricated model name); every AI action surfaced here traces to a real
  audit-logged invocation, never a UI-side approximation.
- **Security considerations**: none beyond §6.1's standing rule and this
  Track's own architecture diagram — this UI never becomes a second AI
  authorization system; every tool/capability shown, enabled, or disabled
  here reflects Data Authorization/RBAC/autonomy-tier state the backend
  already enforces, never a frontend-only toggle with no backend effect.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started. No `frontend/app/**/ai/**` (or AI-control-
  equivalent) UI exists today (confirmed by inspection); Backend Phase 26
  is itself `not started`.
- **Checkpoint**: dedicated security review before this UI ever surfaces
  real tenant data flowing to a real external AI vendor — mirrors Phase
  26's own standing checkpoint, not a separate or lesser bar.

## UI-19 — Integrations & Connected Services

- **Objective**: a consolidated, tenant-facing view of provider/connection
  status for adapters that already exist (or will exist) per their owning
  module's own phase — not a new integrations marketplace, and not a
  second place those adapters are configured.
- **Dependencies**: UI-5 (Marketing channel providers), UI-6 (Appointments
  calendar-provider status), UI-17 (Telephony provider status); Backend
  Phase 17 (Integrations Hardening — adapter-consistency audit, not
  started per that phase's own Outcome).
- **Scope**: read-mostly consolidation of provider/connection status each
  owning module's UI already surfaces or will surface (e.g. UI-6's
  calendar-provider status, UI-17's telephony-provider status) into one
  settings-adjacent view; a link out to each owning module's own
  provider-specific configuration screen, never a duplicate of it. No
  provider-specific integration is invented here — every provider this
  view can show is one an owning module's own phase has already named.
- **Tests**: status shown here matches the owning module's own real/fake
  provider distinction exactly (no separate "connected" state invented by
  this consolidation view).
- **Security considerations**: none beyond §6.1's standing rule; provider
  credentials remain each adapter's own `infra.secrets`-gated concern
  (Phase 17.1's own audit target) — this view never displays or collects
  a raw credential itself.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard; removing this consolidation view does not affect
  any owning module's own provider configuration.
- **Outcome**: not started. No `frontend/app/**/integrations/**` or
  equivalent exists today (confirmed by inspection); Backend Phase 17 is
  itself `not started`.
- **Checkpoint**: review Phase 17.1's own audit findings (its standing
  Checkpoint) before this view claims any adapter is consistently
  configured.

## UI-20 — Notifications & Activity Center

- **Objective**: a persistent, tenant-facing notifications/activity
  surface over `core.notifications` (SaaS-OS, Category A — consumed, never
  rebuilt), distinct from UI-12's Command Center (a landing-page "what
  needs my attention now" read-model) — this phase must not duplicate
  UI-12's `AttentionSection`/`RecentActivitySection`, only extend beyond
  what a single dashboard page can hold (a persisted, dismissible,
  cross-page notification feed and per-tenant notification preferences).
- **Dependencies**: UI-1, UI-12 (the existing read-model this phase
  extends rather than duplicates); `core.notifications`/`core.email`
  (SaaS-OS, already consumed by Backend Phase 5.3 and 7.3's reminder
  wiring — no new Layer-1 capability required).
- **Scope**: a notification/activity feed surfacing the same class of
  business events UI-12 already curates for the dashboard (appointment
  reminders per Phase 7.3, conversation events per Phase 5.3, once other
  modules publish comparable events); per-tenant notification preferences
  (channel/frequency) wrapping `core.notifications`' existing mechanism,
  never a second delivery system. Explicitly out of scope: any new
  delivery channel `core.notifications` does not already support, and any
  event type not already published by an owning module's own phase.
- **Tests**: a notification shown here traces to a real published domain
  event, never a UI-fabricated one; dismissing/marking-read here does not
  affect the underlying event or its owning module's own state.
- **Security considerations**: none beyond §6.1's standing rule; a
  notification never surfaces content the viewing user's own RBAC/Data
  Authorization grant would not otherwise let them see.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard; disabling this feed does not affect UI-12's own
  Command Center, which remains independently functional.
- **Outcome**: not started. No `frontend/app/**/notifications/**` or
  equivalent exists today (confirmed by inspection).
- **Checkpoint**: review against UI-12 specifically before starting, to
  confirm no duplication of its existing `AttentionSection`/
  `RecentActivitySection`.

## UI-21 — Prospecting / Lead Generation

- **Objective**: the user-facing UI for the existing (not yet built)
  Prospecting backend (Backend Phases 19–20, both status PROPOSED,
  roadmap/design only). **Does not create a second CRM**: Backend Phase
  19's own text is explicit that "the CRM (Phase 4) remains the one system
  of record for Company/Contact/Opportunity — Phase 19 never creates a
  second CRM," and this UI phase inherits that constraint unchanged.
- **Dependencies**: UI-1, UI-3 (CRM, the handoff target); Backend Phase
  18 (production/compliance gate Phase 19.1 itself depends on), Backend
  Phase 19 (Provider & Data-Licensing Spike, Prospecting domain model),
  Backend Phase 20 (Prospecting Automation & AI Agents) — all not started.
- **Scope**: prospect list/detail views over Phase 19's own
  provider-agnostic prospecting domain model (Category C) once it exists;
  prospect-to-CRM conversion UI wrapping Phase 4's existing
  Company/Contact/Opportunity creation, never a parallel creation path;
  prospect activity/status views; lead-acquisition-source visibility
  (which Category-D provider a prospect came from) surfaced honestly per
  whichever provider Phase 19.1's spike and a later vendor decision
  actually select — never a specific provider named or implied ahead of
  that decision. Explicitly out of scope: any provider-specific
  integration UI beyond what Phase 19/20 themselves scope, and any
  duplication of UI-3's own CRM screens for a converted prospect.
- **Tests**: a "convert to CRM" action produces exactly one
  Company/Contact/Opportunity through Phase 4's existing service layer, no
  UI-side duplicate-detection logic diverging from whatever Phase 19
  itself specifies.
- **Security considerations**: none beyond §6.1's standing rule and
  Phase 19's own data-governance/legal review gate (19.1) — this UI must
  not surface externally-sourced personal data ahead of that gate's own
  clearance.
- **Acceptance criteria**: matches the tests above.
- **Rollback**: standard.
- **Outcome**: not started. No `frontend/app/**/prospecting/**` (or
  lead-generation-equivalent) UI exists today (confirmed by inspection);
  Backend Phases 19 and 20 are both status PROPOSED, roadmap/design only.
- **Checkpoint**: none until Phase 19.1's own provider/data-licensing
  spike and its data-governance review are complete.

### Proposed UI phases folded into existing coverage

Three additional UI surfaces were considered while closing this Track's
gap and deliberately **not** given a new UI-#, to avoid duplicating a
phase that already exists or inventing a backend capability this roadmap
does not otherwise plan:

- **"Unified Customer Inbox / Multi-Channel Messaging"** — not added.
  Backend Phase 30 (Unified Inbox) is explicit that its AI summaries/
  suggested replies and phone-keyed contact resolution are "surfaced in
  the Conversations UI" itself, not a separate surface — i.e. this
  roadmap already treats `UI-4` (Conversations) as the unified
  communication surface. When Phase 30 is implemented, its UI half
  extends `UI-4`'s existing scope; it does not need or get its own UI-#.
- **"API, Webhooks & Developer Settings"** — not added. No backend phase,
  subphase, or capability anywhere in this document defines tenant-facing
  API credentials, an outbound-webhook system, or developer settings for
  external integrators (confirmed by inspection: no match for "API key,"
  "developer," "webhook delivery," "OAuth client," or similar across this
  document). Adding a UI phase here would invent a backend capability
  this roadmap does not plan, violating this Track's own "UI consumes
  existing backend contracts" architecture rule. If this capability is
  ever actually planned, it needs its own Backend Track phase first, the
  same way every other UI phase above waits on a real backend capability.
- **"Advanced Tenant / Team Administration"** — not added. `UI-7`'s own
  Outcome already lists `settings/{access,branding,profile,
  support-access}` as real (access delegation, support access), `UI-2`'s
  own Outcome already lists `InviteMemberPanel` (invitations) as real, and
  `UI-13` (Approval Inbox) already surfaces the administrative audit trail
  for approved actions (Phase 26's own "Explain" step, closed by Phase 29/
  `UI-13`). Users, teams, roles, permissions, invitations, delegation, and
  administrative audit visibility are therefore already covered across
  `UI-2`, `UI-7`, and `UI-13` — no meaningful advanced-administration gap
  beyond those three was found, per this Track's own instruction to retain
  a phase only when one exists.

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
Production/Compliance, Prospecting) continue on the Backend Track.
Automation, Websites, and Reputation already have their UI-# (`UI-10`,
retroactively). The remaining named capability now has its UI-# too
(`UI-14`–`UI-21`, added below UI-13) — each still only *begins* once its
own backend dependency is sufficiently stable, exactly like `UI-2`–`UI-9`
above; being scoped here is not being implemented here (the same
distinction Phase 19.1's provider spike draws for its own candidate list —
evaluated, not selected). At the time this section was written, none of
`UI-14`–`UI-21` had started; **updated 2026-09-30**: `UI-14` is now
implemented (see its own Outcome) — `UI-15`–`UI-21` remain not started.

```text
Phase 13 Billing ─────────────► UI-14 Billing/Subscriptions
Phase 24-25 Accounting ───────► UI-15 Accounting Workspace
Phase 16 Reporting ────────────► UI-16 Reporting & Analytics
Phase 8 / 27 Telephony ───────► UI-17 Telephony & Call Center
Phase 9 / 26 AI ───────────────► UI-18 AI Control Center
Phase 17 Integrations ─────────► UI-19 Integrations & Connected Services
core.notifications (SaaS-OS) ─► UI-20 Notifications & Activity Center
Phase 19-20 Prospecting ───────► UI-21 Prospecting / Lead Generation
```

Each arrow above is an individual dependency, not a chain — `UI-19` does
not wait on `UI-18`, `UI-18` does not wait on `UI-17`, and none of them
waits on `UI-1`–`UI-13` finishing anything beyond the specific prior UI-#
each phase's own Dependencies field names (e.g. `UI-18` names `UI-13`
because it must not duplicate the Approval Inbox, not because approvals
must precede AI generally).

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

The UI Track (`UI-1`–`UI-21`, above) is a third kind of flexibility,
distinct from both: it runs *alongside* Phases 8–20 rather than before or
after them, starting as soon as `UI-1` and each domain phase's own backend
dependency (Phase 3 for `UI-2`, Phase 4 for `UI-3`, and so on) is stable.
It does not renumber, gate, or reorder any Backend Track phase — a UI phase
missing its backend dependency simply doesn't start yet, the same way any
other listed dependency above works.
