# ADR-0011: One Frontend Application, Multiple Authenticated User/Tenant Contexts

Status: ACCEPTED
Date: 2026-09-21

(Note on numbering: this is *this repository's* ADR-0011. `saas-os`'s own
`docs/ADR/0011-...` — referenced from `docs/ARCHITECTURE.md` §6 as the
TypeScript/Next.js platform default — is a different document in a
different repository.)

## Context

`docs/ARCHITECTURE.md` §6 already establishes that this product's frontend
is entirely product-owned (Next.js, `frontend/`), and §6.1 already fixes
the non-negotiable frontend/backend layering. `docs/ROADMAP.md`'s UI Track
(`UI-1`–`UI-9`) already assumes **one** "Product Frontend" in both of its
own diagrams, and `UI-1`'s replaceable-shell architecture already routes
every domain page through one `AppShell`/`Navigation`/`TopBar`/
`MainContent`.

What none of those documents state explicitly is the question that keeps
resurfacing whenever a new user-facing audience is named: *does a new
audience get a new frontend application?* The UI Track's phase titles
(`UI-2 — Agency / Dashboard`) and Phase 13's own wording ("Agency
subscription," "Agency-defined resale plans," "Client-facing billing")
are written entirely in agency/client vocabulary, which reads as though
the product has exactly one kind of customer (an agency) and, by
extension, that a platform-level or direct-client audience would need
somewhere else to live.

Two things are therefore undecided in writing today, and this ADR decides
both:

1. Whether Platform Owner, Agency, Agency Client and Direct Platform
   Client are separate frontend applications or separate authenticated
   contexts inside one application.
2. Whether the commercial/domain architecture is permitted to assume every
   customer reaches the platform through an agency.

`docs/ADR/0003-agency-client-tenancy-mapping.md` already decided the
tenancy half of this for the agency/client case: agency = root tenant,
client = child tenant, derived at read time from `core.tenancy`, with no
product-owned duplication. `docs/ADR/0002-agency-cross-tenant-route-
authorization.md` already decided how a cross-tenant actor is authorized
at the API ingress layer. This ADR adds no tenancy or authorization
mechanism of its own — it is the frontend/application-architecture
consequence of those two, stated once so future UI phases do not each
re-litigate it.

## Decision

**The product has one frontend application. Platform Owner, Agency,
Agency Client and Direct Platform Client are different authenticated
user/tenant contexts within that same application — not separate frontend
applications, not separate frontend codebases, not separate deployments.**

```text
                         ONE PRODUCT FRONTEND
                                  │
                           authenticated user
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
              Platform Owner    Agency        Client
                                                │
                                      ┌─────────┴─────────┐
                                      │                   │
                               Agency Client       Direct Client
```

The frontend adapts its navigation, its views and its available actions
according to the authenticated context. It does not fork into a second
application to do so.

## Detailed Architecture

### Context determination

What the frontend renders may depend on:

- authenticated identity
- current tenant
- tenant relationship/hierarchy (the `core.tenancy` position — root,
  child, or a deeper relationship a later phase introduces)
- roles
- permissions
- delegated administration (`core.rbac.create_delegation()`)
- explicit denies (`core.rbac.create_deny()`)
- support/operator access context where applicable
  (`core.rbac.create_support_access_request()` /
  `approve_support_access()` — a time-boxed, audited grant, per
  `docs/ARCHITECTURE.md` §3)
- entitlements (`core.billing`/`core.usage`)
- product capabilities (which modules are built, enabled and reachable)
- tenant/account lifecycle and product state (trial, active,
  suspended, ...)

The frontend consumes an authoritative, backend-provided
context/capability description and renders from it. It does **not**
independently reconstruct authorization rules from raw role names, tenant
`parent_id` values, plan identifiers, or any other fragment it could use
to guess at a decision the backend already makes. This is
`docs/ARCHITECTURE.md` §6.1's existing "treats the backend as the sole
source of truth for tenant/agency context, entitlements, and data — no
independent frontend-side domain model that diverges from what the API
returns," restated for the specific case of multi-context rendering.

Where the API does not yet expose enough context for a UI phase to render
correctly, `docs/ROADMAP.md`'s existing "UI/backend contract policy"
applies unchanged: document the mismatch, prefer consuming the existing
shape, and if a backend adjustment is genuinely required, scope it as a
narrow correction against the owning Backend Track phase — never as
frontend-side reconstruction of the missing rule.

### Identity, tenant and relationship are three different things

```text
User identity
    ≠
Tenant
    ≠
Tenant relationship
```

One person may act in several authorized contexts (an agency operator
acting in the agency tenant, then in one of its client tenants via
`SUBTREE` reach; a platform operator acting under a time-boxed support
grant). "Who you are" is not "where you are acting," and neither is "how
that tenant relates to the party that sells to it."

The frontend therefore must not treat a coarse persona label as the
fundamental model:

```text
user_type == "agency"
user_type == "agency_client"
user_type == "direct_client"
```

Branching on a label like that hardcodes, client-side, a conclusion that
is actually the composition of identity + current tenant + hierarchy
position + roles + delegation + deny + entitlements — each of which the
backend already evaluates, and any of which can change without the label
changing. It consumes the actual authenticated context and capabilities
the backend exposes instead.

Nor does this ADR introduce a new global `tenant_type` column/field for
frontend convenience. `docs/ADR/0003-agency-client-tenancy-mapping.md`
already rejected product-owned duplication of facts `core.tenancy` owns,
for reasons that apply unchanged here: a second, independently-writable
copy of "what kind of tenant is this" drifts. A relationship-dependent
distinction that a later phase genuinely needs is decided by that phase,
against a real need (that ADR names a future reseller-configuration phase
as exactly such a trigger), not introduced now to make a frontend
`switch` statement easier to write.

### Tenant relationships

The system may contain relationships such as:

```text
Platform Owner
      │
      ├──────────────► Direct Client
      │
      └──────────────► Agency
                           │
                           ├──► Agency Client A
                           └──► Agency Client B
```

The architecture must not assume that every customer is an Agency. At
minimum, the commercial/domain architecture must be capable of
distinguishing:

- Platform Owner
- Agency
- Agency Client
- Direct Platform Client

**without requiring separate frontend applications.**

This does not, by itself, add any table, column or tenancy concept.
`docs/ADR/0003-...`'s decision stands: these facts are derived from
`core.tenancy` at read time, and a marker table is added only when a real
need appears (that ADR names a future reseller-configuration phase as
exactly such a candidate trigger). What this ADR adds is the requirement
that whichever mechanism a later phase chooses must be *capable* of the
distinction above — an architecture that can only express "every tenant
under the platform is an agency, every agency has clients" is out of
bounds.

### The four contexts, stated individually

- **Platform Owner** — an operator/control-plane identity, **not simply
  another product tenant**. Platform-level work (looking across agencies
  and direct clients, platform plans, entitlements, usage, support
  access, audit) is not "a tenant's own data seen from a bigger tenant,"
  and must not be modelled as though a Platform Owner were just a tenant
  higher up the tree. The one frontend may expose operator functionality
  when the authenticated context permits it.
- **Agency** — a tenant (a root tenant, per
  `docs/ADR/0003-agency-client-tenancy-mapping.md`). The frontend may
  expose agency administration, client management and the product
  modules, according to backend-provided permissions and entitlements.
- **Agency Client** — a tenant below an Agency in the `core.tenancy`
  hierarchy. It uses the same frontend application, and the same
  client-oriented UI, as any other client tenant.
- **Direct Platform Client** — also a tenant, with no Agency parent. It
  must be able to use the same client UI as an Agency Client.

A different commercial relationship is not, by itself, a reason for a
different frontend application.

### Client UI reuse

```text
Agency Client ─────┐
                   ├──> shared Client UI
Direct Client ─────┘
```

**Agency Client and Direct Platform Client may use the same Client UI
experience**, and the implementation prefers reusable client-facing
components and pages over duplicated applications. Their differences are
determined by:

- tenant context
- permissions
- entitlements
- commercial relationship
- available capabilities

A separate frontend codebase is not created merely because the tenant
relationship differs. Whether a client's parent is an agency or the
platform itself is a fact about who sells to them and who administers
them — not a reason for a second copy of the same contact list, inbox,
calendar and settings screens.

### Agency context

The Agency context may expose capabilities such as: client management,
CRM, conversations, appointments, marketing, automation, websites,
reputation, SaaS/resale management where authorized, and settings.

This list is descriptive, not an authorization model. Actual visibility is
determined by permissions and available capabilities, resolved per the
"Context determination" rules above. Nothing in the frontend may hardcode
this list as *the* definition of what an agency may do.

### Platform Owner context

The same frontend application may expose additional platform-level
capabilities to authorized Platform Owner users, such as: agencies, direct
clients, platform plans, subscriptions, billing, entitlements, usage,
support, platform administration, and audit.

Again: a contextual UI model inside the one application, not a separate
frontend application, and not a hardcoded authorization model.

### Relationship to SaaS-OS

This decision sits on top of the existing platform model, unchanged:

```text
Frontend
    ↓
Product API / Domain
    ↓
SaaS-OS
    ↓
Infrastructure
```

SaaS-OS provides the underlying security/platform primitives: identity
and authentication integration (OIDC), tenant hierarchy, RBAC,
scope-aware authorization (`SELF`/`SUBTREE`), delegation, explicit deny,
support access, entitlement/billing primitives, and audit/security
primitives (`docs/ARCHITECTURE.md` §3,
`docs/RESPONSIBILITY-MATRIX.md`). They remain authoritative wherever they
apply.

The product frontend consumes the **Product API's** context — it never
imports `saas-os` code (`docs/ARCHITECTURE.md` §6.1) and never becomes an
alternative implementation of SaaS-OS's authorization model. It must not
implement its own tenant hierarchy or its own authorization framework.
This ADR introduces no second tenancy concept and no second authorization
mechanism, exactly as `docs/ADR/0003-...` did not.

## Security Boundary

**The frontend is not a security boundary.**

```text
Frontend
    ↓
UX / navigation / visibility
    ↓
Backend API
    ↓
Authorization
    ↓
SaaS-OS / product authorization model
```

| | Responsible for |
|---|---|
| **Frontend** | navigation; UX; hiding unavailable features; contextual dashboards; contextual actions; displaying available capabilities |
| **Backend** | authentication; authorization; tenant isolation; RLS; role enforcement; delegation; explicit deny; entitlement enforcement; lifecycle enforcement; resource access |

A hidden button or menu item does not constitute authorization. Hiding is
a UX affordance only — the same operation reached by any other means (a
typed URL, a stale tab, a direct API call, a modified client bundle) must
still be refused server-side. Stated item by item, because each of these
has at some point been mistaken for a control:

- hidden UI is not authorization;
- disabled UI is not authorization;
- route guards are not authorization;
- frontend capability checks are not authorization;
- a tenant id supplied by the browser (a URL segment, a switcher
  selection, a stored preference) is not trusted merely because the UI
  chose it — the backend authorizes the actor against that tenant on
  every request, per `docs/ADR/0002-...`.

Every protected operation is enforced server-side, per
`docs/ADR/0002-...`'s already-established pattern: `get_current_actor` at
the ingress layer, and the owning module's own service functions
performing their own `core.rbac.can()` checks against their own
product-defined permissions before touching their own tables. A 403 from
the backend remains authoritative even if a hidden control was somehow
reached (`docs/ARCHITECTURE.md` §6.1).

The specific risk this multi-context architecture introduces, named
explicitly so it is tested rather than assumed: **one context must never
be able to make itself look like another.** Context selection (which
tenant am I acting in, which capabilities do I see) is a request the
backend authorizes, never a client-side assertion the backend trusts.
`docs/ROADMAP.md` `UI-2`'s existing test already states this for tenant
switching — "a UI-level switch attempt the backend would reject is itself
rejected, not silently allowed client-side" — and that rule generalizes to
every context distinction this ADR names.

### Security considerations, stated explicitly

- **Frontend state is untrusted.** Anything the client holds (context,
  capability lists, feature flags, the selected tenant) is a rendering
  input, never an authorization input for the backend.
- **Authorization decisions belong to the backend.** `core.rbac.can()`
  in the owning module's service layer is the chokepoint
  (`docs/ADR/0002-...`); the frontend has no equivalent and must not
  grow one.
- **Tenant isolation belongs to the backend** — RLS plus API-layer
  authorization (`docs/ARCHITECTURE.md` §3's client-isolation rule), not
  to per-page frontend filtering.
- **The frontend must not infer authorization from URL structure.** That
  a route exists under `/t/<tenantId>/...`, or that a page renders, says
  nothing about what the actor may do there; the API call still decides.
- **The frontend must not assume hidden UI prevents API access.** Every
  operation behind a hidden control is independently reachable, and must
  independently fail closed.
- **Delegated access is represented by real backend
  authorization/context**, never by a frontend-side "acting as"
  simulation — a delegation the backend did not grant does not exist,
  and an explicit deny the backend applies is not something the frontend
  may render around.
- **Support/operator contexts must not inherit tenant-client
  assumptions.** A Platform Owner or support actor viewing a tenant's
  data is operating under a time-boxed, audited grant, not as that
  tenant; UI built for the tenant's own user must not silently become
  the operator's view of it, and an operator's elevated context must not
  leak into components that assume "the current tenant is mine."

## Consequences

### Benefits

- one frontend codebase
- one deployment
- shared design system
- shared components
- less duplicated UI logic
- consistent UX
- one shared client UI for Agency Client and Direct Platform Client
- easier feature development
- easier white-labeling — one place where branding resolves
  (`product/white_label/`'s existing fallback chain), not one per
  application
- one consistent authorization model, because there is only one client
  of the Product API's context contract
- new tenant relationships can be supported without multiplying
  applications
- capabilities can evolve independently of the organizational relationship
  between the parties

### Trade-offs

- frontend context handling becomes more sophisticated than a
  single-audience application would need
- navigation must be capability-aware, not statically enumerated
- API contracts must expose sufficient context for the frontend to render
  correctly without guessing
- the UI must handle more states (context loading, context unavailable,
  capability absent, permission denied, entitlement exhausted, lifecycle
  suspended) than a single-audience application would
- UI testing must cover multiple authorization contexts, not just one
  happy-path role
- careless frontend assumptions could accidentally make one context look
  like another — the reason the Security Boundary section above names that
  risk explicitly rather than leaving it implicit

## Roadmap Implications

### For every future frontend phase

Future frontend phases follow this architecture. Do **not** create a
separate frontend application simply because a feature is intended for
Platform Owner, Agency, Agency Client, or Direct Platform Client.

Instead, each such feature determines:

1. which user contexts can access the capability;
2. which permissions are required;
3. which tenant scope applies;
4. which entitlements apply;
5. what UI should be visible in each context.

The same frontend application then renders different navigation, views and
actions accordingly. This is an addition to, not a replacement for, the UI
Track's existing standing constraints (`docs/ARCHITECTURE.md` §6.1, the
replaceable-shell architecture, the mock-data policy, and the UI/backend
contract policy) — a UI phase is reviewed against all of them.

`UI-1`'s replaceable application shell is where context-aware navigation
belongs architecturally: the shell resolves the authenticated context and
the capabilities available in it; domain pages consume the shell's
primitives rather than each re-deciding what the current audience is.

### Routing and navigation

Routing represents **product capabilities/pages**, not personas — one
route tree, conceptually:

```text
/app
  /dashboard
  /crm
  /conversations
  /appointments
  /reputation
  /settings
```

with which entries are reachable and visible determined by the
authenticated context and its capabilities. There is no per-persona
duplicate of the tree (no `/agency/crm` beside `/client/crm`).

This is a principle, not a prescription: the existing frontend already
implements it in its own way, and that mechanism — not this ADR — is
authoritative on the details. Today the shell routes capabilities under a
tenant-scoped segment (`frontend/app/(app)/t/[tenantId]/<capability>`), and
navigation is defined once in `frontend/lib/nav/config.ts`, rendered by
`components/shell/Navigation.tsx` and `TopBar.tsx`, never re-declared per
page — exactly the single, centralized place a capability-aware
navigation decision belongs when the phase that needs it arrives. (That
list is currently keyed to which backend routers exist, `available` vs.
`planned`, not yet to the authenticated actor's permissions/entitlements;
turning it capability-aware is the work a later UI phase does *there*,
which is the point of it being one list.) This ADR deliberately does not
specify React-level structure, hook names, or a provider shape.

### UI-11 — Reputation UI

(`docs/ROADMAP.md`'s UI Track enumerates `UI-1`–`UI-9` and states that
each later backend module "gets its own UI phase, numbered and scoped
when that backend capability is sufficiently stable." `UI-11` is the
Reputation UI phase built under that rule, against the Phase 12
Reputation backend. This ADR does not number, scope, or change the status
of any UI phase, `UI-11` included.)

`UI-11` — and every UI phase after it — must:

- remain part of the single frontend application, in the same shell and
  route tree as every other module;
- work for whichever tenant contexts are authorized for it, rather than
  being written for one audience;
- use the actual Reputation API (`product/reputation/routes.py`, via
  `frontend/lib/api/reputation.ts` on `UI-1`'s existing `request()`
  client — no second HTTP client, no invented endpoint, and no mock left
  as a completed phase's permanent data source, per the UI Track's own
  mock-data policy);
- derive UX visibility from backend-provided authorization/context —
  Reputation's own permissions (`product/reputation/permissions.py`) as
  the backend reports them, not a frontend-side guess at who is an
  agency;
- not introduce separate Agency Client and Direct Platform Client
  applications;
- not duplicate the Reputation UI by tenant relationship — one set of
  review-request/review screens, rendered in whichever context is
  authorized;
- treat backend authorization as authoritative: a 403 from a Reputation
  route is the answer, even where the UI had already hidden the control.

### Phase 13 — SaaS Resale / Billing

`docs/ROADMAP.md` Phase 13 is currently written entirely in agency
vocabulary. **Phase 13 must not assume an Agency-only customer model.**
The commercial model must distinguish, where applicable:

```text
Platform → Direct Client
Platform → Agency → Agency Client
```

and must separately establish:

- plan ownership
- subscription ownership
- reseller/seller relationship
- entitlement recipient

(which are four distinct questions — "the agency owns the plan, the client
holds the subscription, the agency is the seller, the client is the
entitlement recipient" is one valid arrangement among several, and Phase
13.2's existing resale-tier ceiling check is a constraint *between* them,
not a substitute for naming them).

**This ADR does not implement Phase 13, does not change its scope, and
does not change its status (`not started`).** It establishes only the
frontend/application architecture Phase 13 must respect when it is
actually scoped: whatever commercial model Phase 13 lands on, it is
rendered through the one frontend application this ADR decides, in
whichever contexts it applies to.

## Rejected Alternative

Separate frontend applications per audience (e.g. a platform-admin app, an
agency app, a client portal), each with its own deployment and its own
copy of the shell, design tokens and API client.

Rejected: the four audiences share the overwhelming majority of their
screens (a contact, a conversation, an appointment, a settings page is the
same artifact regardless of who is looking at it), so this buys duplication
in exchange for no isolation the backend does not already provide — the
security boundary is `core.rbac` and RLS in the Product API, and it is
identical whichever bundle the request came from. It would also
re-introduce, at the application level, precisely the fragmentation
`docs/ARCHITECTURE.md` §6.1 and the UI Track's own replaceable-shell
architecture are built to avoid, and would make `UI-9`'s "mature the
patterns real screens have proven" step a three- or four-way merge instead
of a consolidation.

Not rejected, and explicitly out of scope here: route-level or
bundle-level code splitting *within* the one application (e.g.
lazy-loading platform-administration screens for the users who can reach
them). That is a build/performance decision for the phase that needs it,
not a second application.

## Related ADRs and Documents

- `docs/ADR/0002-agency-cross-tenant-route-authorization.md` — how a
  cross-tenant actor is authorized at ingress and in each module's own
  service layer; the server-side enforcement this ADR's security boundary
  depends on.
- `docs/ADR/0003-agency-client-tenancy-mapping.md` — agency = root tenant,
  client = child tenant, derived from `core.tenancy` with no product-owned
  duplication; the tenancy model the contexts above are read from.
- `docs/ARCHITECTURE.md` §3 (agency/client tenancy model), §6 (frontend is
  product-owned), §6.1 (frontend/backend layering, non-negotiable).
- `docs/ROADMAP.md` UI Track (`UI-1`–`UI-9`), and Phase 13 — SaaS Resale /
  Billing.
- `docs/RESPONSIBILITY-MATRIX.md` §Frontend (Category C: product-owned UI
  consuming Category A mechanisms it does not reimplement) and §Billing,
  Entitlements, Subscriptions.
