# Product Architecture

Status: PROPOSED — awaiting your review. Nothing in this document has been
implemented.

This document defines the product-layer architecture for the platform planned
in this repository, built on top of `saas-os` (`C:\Users\imran\Documents\saas-os`).
It follows the same discipline `saas-os`'s own `docs/ARCHITECTURE.md` uses:
binding layer rules, an explicit dependency rule, and module ownership —
applied one level down, inside the Product layer SaaS-OS's own architecture
already reserves for exactly this.

## 1. Where This Product Sits

SaaS-OS's own architecture (`saas-os` `docs/ARCHITECTURE.md` §1) defines four
layers: SaaS Core, Infrastructure, AI Control Plane, Product. This repository
**is** an instance of the fourth layer. It never becomes a fifth layer, and it
never reaches into SaaS-OS's internals:

```
Product (this repository)
     │  depends on, via the installed `saas-os` package only
     ▼
SaaS Core (core.*)  +  AI Control Plane (control_plane.*)
     │
     ▼
Infrastructure (infra.*)
```

Binding rules inherited unchanged from `saas-os` `docs/ARCHITECTURE.md` §2:

- This product depends on SaaS Core and the AI Control Plane through their
  published Python interfaces only (`import core.rbac`, `import
  control_plane.orchestration`, ...) — never through direct database access,
  never through a `sys.path` hack into `saas-os`'s source tree, never through
  a fork.
- This product never imports SQLAlchemy or psycopg directly for anything
  SaaS-OS already owns (tenancy, identity, billing, audit, etc.) — those
  reads/writes go through Core's interface. This product's **own** tables
  (CRM, marketing, accounting, ...) are this product's own SQLAlchemy models,
  built on `infra.db`'s session/engine primitives exactly as
  `examples/reference-consumer` in `saas-os` demonstrates.
- This product never modifies `saas-os` source. A capability genuinely
  missing from SaaS-OS is either built inside this repository (if
  product-specific) or written up as a proposal for the SaaS-OS maintainers
  to evaluate on their own roadmap (if genuinely generic) — see
  `docs/RESPONSIBILITY-MATRIX.md`.
- AI Control Plane capability is consumed the same way `saas-os`'s own
  `docs/architecture/SAAS-OS-DISTRIBUTION-ARCHITECTURE.md` §11 concludes every
  consuming project should: an in-process `ToolRegistry` instance, running in
  this product's own process, with this product registering its own tools
  against its own RBAC permissions. No centralized AI service.

## 2. The Product Layer's Own Internal Structure

Unlike SaaS-OS (which enforces its four layers with `import-linter`), this
product layer is itself composed of many business-domain modules (CRM,
marketing, accounting, ...). Left unchecked, a codebase this size becomes a
ball of mud in exactly the way SaaS-OS's own `docs/ARCHITECTURE-DISCOVERY.md`
warns against for the platform itself. This document extends the same
"modules must never depend on each other directly" discipline SaaS-OS already
applies at the Product boundary (`saas-os` `docs/ARCHITECTURE.md` §2, "Product
modules must never depend on each other directly") **inside** this repository,
between its own modules.

### 2.1 Proposed module boundary

```
product/
├── foundation/      # shared product-level abstractions every module may use
│                     #   - BrandingProvider (white-label context)
│                     #   - the product event dispatcher (see §4)
│                     #   - tenant-scoped settings helpers
│                     #   - shared value objects (Money, PhoneNumber, ...)
│                     # foundation/ never imports any other product/ module.
│
├── agency/           # agency/client tenant management, delegated admin UI-facing
│                     # service layer, client onboarding, support-access workflows
│
├── crm/               # contacts, companies, leads, opportunities, pipelines
├── marketing/          # campaigns, forms, landing pages, segmentation
├── conversations/       # unified inbox: email/SMS/WhatsApp/chat threads
├── telephony/            # calls, recordings, routing, provider adapters
├── ai/                     # product's own AI Control Plane tool registrations
├── appointments/            # calendars, booking, availability
├── automation/               # trigger/condition/action workflow engine
├── reputation/                 # review requests, tracking, responses
├── websites/                    # website/funnel builder, published pages
├── billing/                       # agency-sells-to-client entitlement mapping
│                                   #   over core.billing (see RESPONSIBILITY-MATRIX)
├── accounting/                      # mini bookkeeping module (see ACCOUNTING-SCOPE.md)
├── reporting/                         # cross-module analytics and accounting reports
├── white_label/                        # branding data model + resolution
├── templates/                            # snapshot/template export-import
├── integrations/                          # external-provider adapters (see INTEGRATIONS.md)
│
├── api/                                    # FastAPI app composition root: mounts
│                                            #   saas-os's reusable routers (api.platform)
│                                            #   plus every module's own routers
└── frontend/                                # Next.js app (separate toolchain, own package.json)
```

### 2.2 Internal dependency rule

```
Every product/<module> depends on:
    - product/foundation           (always allowed)
    - saas-os (core.*, control_plane.*, infra.*)   (always allowed, per §1)

Every product/<module> MUST NOT depend on:
    - any other product/<module> directly (e.g. crm/ importing accounting/
      internals, or automation/ importing crm/'s service functions directly)
```

A module needing another module's capability has exactly two sanctioned
paths, mirroring the two patterns SaaS-OS itself already uses at its own
Product boundary (`saas-os` `docs/ARCHITECTURE.md` §7, "the module that owns
the underlying state owns the event schema... consumers subscribe"):

1. **The capability is generic enough to belong in `product/foundation`.**
   Example: a `Money` value object, a phone-number normalizer, the
   `BrandingProvider` interface. Promote it, don't duplicate it.
2. **The capability is a reaction to another module's state change.** Example:
   Automation reacting to "opportunity moved to Won," Accounting reacting to
   "invoice marked paid," Reporting reading CRM/Marketing/Accounting data for
   a dashboard. This goes through the **product event dispatcher** (§4) — a
   module publishes a domain event describing what happened; interested
   modules subscribe. A module never calls another module's internal service
   functions or reads another module's tables directly, even for read-only
   purposes — this is the same rule `saas-os`'s own
   `docs/DATA-ARCHITECTURE.md` §3 applies between SaaS-OS's own Core modules,
   applied here between this product's own modules for the same reason: it
   is what lets a module's internal implementation change without a
   cross-module regression, and what keeps `accounting/` genuinely small and
   removable rather than becoming load-bearing plumbing for the rest of the
   product.

This boundary is enforced the same way SaaS-OS enforces its own (`saas-os`
`docs/ARCHITECTURE.md` §8): an `import-linter` contract in this repository's
own `pyproject.toml`, checked in this repository's own CI, from Phase 1
onward — not left to code-review discipline alone.

### 2.3 Database ownership

Each module owns its own Postgres schema (`crm.*`, `marketing.*`,
`accounting.*`, ...), inside the **one** physical database this project owns
(alongside `saas-os`'s own `core.*`/`control_plane.*` schemas in that same
database — per `saas-os` `docs/ADR/0016-independent-database-migration-histories.md`
and `docs/REPOSITORY-STRATEGY.md` in this repository). Exactly one module
writes to its own schema; another module reads it only through that module's
published interface, never direct SQL. A schema may hold a foreign key into
`core.*` (e.g. `crm.contacts.tenant_id → core.tenants.id`) for referential
integrity, exactly as `saas-os` `docs/DATA-ARCHITECTURE.md` §1 already
permits for any Product schema.

### 2.4 API ownership

This product owns one FastAPI application (`product/api/`), composed with
`api.platform.build_platform_app()` from `saas-os` (ADR-0017 there) so every
route — Core-owned or product-owned — passes through the same enforced
auth/tenant-resolution/RBAC middleware chain SaaS-OS already provides. Each
module contributes its own router (`product/crm/routes.py`, etc.), mounted
under a per-module path prefix (`/v1/crm/...`, `/v1/accounting/...`), per
`saas-os` `docs/API-ARCHITECTURE.md` §2 and §4 (versioned from the first
route, `/v1/...`).

## 3. Agency / Client Tenancy Model

This is the single most consequential mapping in this architecture, and it
maps almost entirely onto capability SaaS-OS already provides (see
`docs/RESPONSIBILITY-MATRIX.md` for the full accounting):

```
Agency (root tenant, core.tenants.parent_id IS NULL)
   │
   ├── Client A (core.tenants.parent_id = Agency.id)
   ├── Client B
   └── Client C
```

- **Agency = a root tenant. Client = a child tenant.** No second tenancy
  concept is introduced. `core.tenancy`'s existing `parent_id` /
  `core.tenant_ancestry` hierarchy (`saas-os` `docs/MULTI-TENANCY.md` §8) *is*
  the agency/client relationship.
- **Delegated administration** ("an agency user can manage every client
  underneath them") is `core.rbac`'s existing `SUBTREE`-scoped
  `MembershipRole` (`saas-os` `docs/MULTI-TENANCY.md` §9) — an agency-level
  role assigned with `scope=SUBTREE` reaches every current descendant client
  automatically, re-evaluated against the live hierarchy on every check.
- **Explicit deny** ("this specific client should not be reachable by this
  agency user, even though their subtree role would otherwise allow it") is
  `core.rbac.create_deny()` / `revoke_deny()` (already implemented — see
  `core/rbac/service.py` in `saas-os`, exercised end-to-end by
  `examples/reference-consumer/reference_consumer/scenarios.py`).
- **Delegation** ("an agency user grants a narrower slice of their own access
  to another user or a service account, with anti-redelegation and
  revocation") is `core.rbac.create_delegation()` /
  `create_delegation_to_service_account()` / `revoke_delegation()` — already
  implemented, not a future capability.
- **Service accounts / machine credentials** for client-side automation
  (e.g. a client's own integration calling this product's API) are
  `core.identity.create_service_account()` + `core.api_keys` — already
  implemented.
- **Support access** ("platform/agency staff need time-boxed, audited access
  into a client's data for troubleshooting") is
  `core.rbac.create_support_access_request()` /
  `approve_support_access()` / `deny_support_access()` /
  `revoke_support_access()` / `revoke_tenant_support_access()` — already
  implemented.
- **Client isolation** is the ordinary tenant-isolation guarantee
  (`saas-os` `docs/MULTI-TENANCY.md` §2–§3) — a client tenant is isolated from
  its sibling clients exactly as any two unrelated tenants would be; hierarchy
  grants no ambient access by itself (`saas-os` `docs/MULTI-TENANCY.md` §8,
  stated explicitly: "hierarchy is structural data only and grants no
  authorization by itself").
- **Billing-owner resolution across the hierarchy** ("does the agency or the
  individual client pay?") is `core.billing.resolve_billing_owner()` —
  already implemented, exercised by the reference consumer's own scenarios.
- **Usage aggregation across the hierarchy** ("total usage across an agency's
  entire client roster, for a rolled-up plan") is
  `core.usage.aggregate_usage_including_descendants()` — already implemented.

`product/agency/` is therefore a comparatively thin service+UI layer over
already-built SaaS-OS primitives: client-onboarding workflows, an
agency-facing client-management UI, and product-specific glue (e.g.
provisioning this product's own per-client default data — a starter
pipeline, default automation templates) — not a second authorization or
tenancy system. See `docs/RESPONSIBILITY-MATRIX.md` §"Agency / Client
Management" for the itemized breakdown.

## 4. The Product Event Dispatcher (New, Product-Owned)

SaaS-OS's own `docs/DATA-ARCHITECTURE.md` §4 documents an *event ownership*
rule (the module that owns state owns its events) but explicitly leaves the
*event transport mechanism* an open decision, and no in-process pub/sub
implementation exists anywhere in `saas-os` today — `core/webhooks` is
outbound HTTP delivery to *external* subscribers, not an internal bus. Since
this product's Automation, Reporting, and Reputation modules all need to
react to state changes in CRM, Marketing, Conversations, Appointments, and
Accounting, this product needs a generic internal event mechanism, and
SaaS-OS does not yet provide one.

**Decision**: build a minimal product-owned event dispatcher
(`product/foundation/events.py`) rather than wait for or unilaterally add one
to `saas-os`. Two reasons:

1. SaaS-OS's own stated doctrine, followed consistently across its ADRs
   (deferred Kubernetes, deferred Vault, deferred a distributed workflow
   engine, deferred a private package index) is to add infrastructure on
   demonstrated need, not speculatively. One consuming product needing an
   event bus is not yet evidence that the *specific shape* SaaS-OS should
   standardize on is already known.
2. Building it inside SaaS-OS now would require modifying `saas-os` — out of
   scope for this product's own roadmap by the governing principle in
   `README.md`.

**Shape**: an in-process synchronous publish/subscribe registry for
same-request reactions (e.g. "recompute pipeline stage counts"), plus an
`infra.jobs`-backed durable variant for reactions that must survive a
process restart or that trigger Automation (which may itself take
multi-step, longer-running action). Every event carries `tenant_id`
(`saas-os` `docs/MULTI-TENANCY.md` §4's job-payload convention, reused
directly). Event schemas are versioned per `saas-os`
`docs/DATA-ARCHITECTURE.md` §4's discipline, applied to this product's own
events.

**Explicit future path**: if a second product is ever built on SaaS-OS with
the same need (plausible — this is a generic, domain-agnostic capability,
not CRM-specific), this dispatcher's design should be proposed to the
SaaS-OS maintainers as a `core/events` addition (Category B in
`docs/RESPONSIBILITY-MATRIX.md`), at which point this product migrates to
it. Building it here first, cleanly, is what makes that migration possible
without a rewrite — the interface is intentionally kept narrow
(`publish(event)` / `subscribe(event_type, handler)`) so it could be
re-pointed at a SaaS-OS-provided implementation later with no call-site
changes.

## 5. Workflow/Automation Execution Substrate

SaaS-OS's own `docs/AI-CONTROL-PLANE.md` §7 states the binding rule directly:
multi-step, stateful, or compensating workflows "must not be built on top of
the Redis-backed `infra/jobs` queue by hand-rolling state tracking... the
trigger to introduce a durable workflow engine... [is] when that capability
is actually built — not before." This product's Automation/Workflow Builder
(Phase 10, `docs/ROADMAP.md`) is exactly that trigger.

This is flagged now, in Phase 0, so the decision is not discovered mid-Phase-10:

- Simple, single-step automations (the large majority: "send an email,"
  "create a task," "update a field") run fine on `infra.jobs` exactly as
  every other background job in this product does.
- Multi-step automations with branching, delays ("wait 3 days"), or
  wait-for-external-event semantics need a durable workflow engine (e.g.
  Temporal). This is evaluated as its own spike at the start of Phase 10,
  not assumed here, and is treated as an **external integration** this
  product depends on directly (`saas-os` `docs/ARCHITECTURE.md` §2 already
  permits Product → Infrastructure-equivalent dependencies for
  cross-cutting concerns) — never something retrofitted into SaaS-OS's own
  `infra/jobs`, and never hand-rolled as ad hoc state tracking on top of it.
- If this proves broadly useful and durable-workflow needs recur outside
  this product, it becomes a Category B candidate for a future SaaS-OS
  `infra/workflows` addition (ADR-0007 in `saas-os` already reserves
  conceptual room for exactly this: "no distributed workflow engine yet;
  interfaces reserved for one later").

## 6. Frontend

SaaS-OS's own `frontend/` (`saas-os` repository) is a placeholder Next.js
page with an i18n scaffold and no distribution mechanism for any consuming
project (`docs/architecture/SAAS-OS-DISTRIBUTION-ARCHITECTURE.md` in
`saas-os` addresses only the Python backend package; frontend consumption is
an open question it never answers). This product's frontend is therefore
**entirely product-owned**, TypeScript + Next.js per `saas-os`
`docs/ADR/0011-...` (the platform default; this product has no reason to
deviate), with no attempted code-sharing with `saas-os/frontend` beyond
optionally eyeballing its i18n pattern once. See
`docs/RISKS-AND-OPEN-QUESTIONS.md` for this flagged as an open question
rather than assumed.

## 7. What This Document Deliberately Does Not Decide

Per the task scope: no database schema, no API endpoint shapes, no frontend
component structure, and no code. `docs/ROADMAP.md` decomposes each module
above into phases; each phase's own implementation work decides these
details when it actually starts, not here.
