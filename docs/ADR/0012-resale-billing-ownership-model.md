# ADR-0012: SaaS Resale/Billing Ownership Model (Plan/Subscription/Entitlement-Recipient)

Status: ACCEPTED
Date: 2026-09-21

## Context

`docs/ROADMAP.md` Phase 13's own three subphases (13.1 agency subscribes to
the platform; 13.2 agency defines resale plans for its clients; 13.3 a
client manages its own resale subscription) and `docs/RESPONSIBILITY-MATRIX.md`
line 44 ("Agency reselling plans to its own clients... is product-specific
business logic — `product/billing/`") together describe a real commercial
relationship this ADR must represent precisely, because three distinct
identities are easy to accidentally conflate: **who sells/administers**,
**who owns the subscription**, and **who receives the resulting product
capability**. This product has exactly one frontend application
(`docs/ARCHITECTURE.md` §6.1) serving every one of these identities
through the same authenticated-actor + tenant-context + RBAC surface — the
backend contracts below are deliberately identity-agnostic (no
`/agency-billing`, `/platform-billing`, or `/client-billing` routes) so
that one frontend can render different capabilities from the same API
based on what the authenticated actor's permissions/entitlements actually
allow, never from a hardcoded notion of "this route is for agencies."

`core.tenancy.Tenant` has no "agency" or "client" type field — every
tenant is structurally identical (an optional `parent_id`, an
`inherits_billing` flag, `docs/ROADMAP.md` Phase 3's own agency/client
provisioning is a *naming and workflow* convention over a flat tenant
model, not a schema distinction). This means "Direct Platform Client" and
"Agency" are the **same structural case** from `core.billing`'s point of
view: a tenant subscribing directly to a global `core.billing.Plan`. The
only real difference is behavioral — whether that tenant later also
defines its own resale catalog for descendants. This ADR generalizes
13.1's wrapper accordingly rather than naming it "agency subscription."

## Decision

### Three identities, kept structurally distinct

1. **Administrator/seller** — the authenticated actor performing a billing
   operation (`api.dependencies.get_current_actor`). Never assumed to be
   the same as the entitlement recipient.
2. **Subscription owner** — the tenant whose `core.billing.Subscription`
   row is created/mutated. This is always the literal `tenant_id` a
   product route/service call names — `product/billing/subscriptions.py`
   never redirects to a different tenant the way `core.billing
   .resolve_billing_owner()` can for *inherited* billing (that mechanism
   is orthogonal to resale — see "Relationship to `inherits_billing`"
   below).
3. **Entitlement recipient** — the tenant whose product capabilities are
   gated by `core.billing.get_entitlements(tenant_id)`. Always identical
   to the subscription owner in this phase's model (a tenant's own
   `Subscription` entitles that same tenant) — there is no "subscribe
   tenant A, entitle tenant B" case in Phase 13's scope. The recipient is
   named `tenant_id` everywhere in `product/billing/`, deliberately never
   called "the agency" or "the client," so the same code path serves a
   direct platform customer, an agency, or an agency's client identically.

### Two subscription sources, one mechanism

- **Platform subscription** — `tenant_id` subscribes directly to a
  *global* `core.billing.Plan` (`GET /v1/billing/plans`, product-agnostic,
  platform-operator-managed catalog). Used identically by a root tenant
  with no resale ambitions ("Direct Platform Client") and by a tenant that
  will *itself* become a reseller ("Agency") — 13.1's own objective,
  generalized: nothing in `core.billing.subscribe()` distinguishes the two,
  so `product/billing/subscriptions.py::create_platform_subscription()`
  doesn't either.
- **Resale subscription** — `tenant_id` subscribes to an *ancestor's*
  product-owned `ResalePlan` (`product/billing/models.py`, 13.2's own
  reseller catalog). `product/billing/subscriptions.py
  ::create_resale_subscription()` validates the `ResalePlan.tenant_id` is
  a genuine ancestor of `tenant_id` (`core.tenancy.get_ancestor_chain()`,
  never assumed to be the *direct* parent only — a multi-level resale
  chain is not precluded, though the roadmap only exercises one level),
  then resolves the plan's own `underlying_plan_key` and delegates to the
  exact same `core.billing.subscribe()` call the platform path uses.

Both paths converge on the identical `core.billing.Subscription` row
shape and the identical `get_entitlements()` read — `product/billing/`
never introduces a second subscription table or a second entitlement
representation (§7/§9 of this phase's own brief).

### Plan ownership

- The **global `core.billing.Plan` catalog** (platform-level pricing
  tiers) is owned and administered by the platform operator, outside this
  product's tenant-authenticated API surface — `core.billing.create_plan()`
  carries no built-in authorization of its own (confirmed by reading
  `core/billing/service.py` directly: no `core.rbac` call anywhere in
  that function), the same "no tenant to attribute a change to" shape
  `core/feature_flags`' own global flag catalog already has. Exposing plan
  *creation* through an authenticated-tenant route would let any tenant
  owner mint arbitrary global pricing tiers — this ADR does not do that.
  `GET /v1/billing/plans` (read-only, any authenticated actor) is the only
  product route touching the global catalog; write access remains an
  ops/seeding concern, documented as deferred, not silently built.
- **`ResalePlan`** (product-owned, `billing.resale_plans`, RLS-scoped) is
  owned by the reseller tenant (`ResalePlan.tenant_id`) — an agency, or
  any tenant that chooses to resell downward. Gated by this product's own
  `billing.resale_plan` permission resource, checked against
  `ResalePlan.tenant_id` (so an agency's `SUBTREE`-scoped `owner` role,
  already granted at provisioning per `product/agency/provisioning.py
  ::provision_agency()`, reaches this exactly the way it reaches every
  other module's tenant-owned resource — no new authorization mechanism).

### Resale-tier ceiling check (13.2's own named security consideration)

`create_resale_plan()`/`update_resale_plan()` read
`core.billing.get_entitlements(reseller_tenant_id)` (already
hierarchy-aware via `resolve_billing_owner()` — if the reseller itself
inherits billing, the ceiling is correctly computed against *its* resolved
owner's plan, not a stale or absent value) and reject any proposed
`ResalePlan.entitlements` key whose value would exceed the reseller's own:
a boolean key may only be `True` in the resale plan if it is `True` for
the reseller; a numeric key's resale value must be `<=` the reseller's own
numeric value; a key entirely absent from the reseller's own entitlements
has an implicit ceiling of "nothing" (any truthy/positive resale value for
it is rejected). This is the one place, per the roadmap's own words, "a
bug becomes a revenue-integrity problem" — enforced synchronously at
write time, in `product/billing/resale_plans.py`, never left to be
discovered later at entitlement-check time.

### Relationship to `core.billing.Tenant.inherits_billing`

`inherits_billing` is a *different* feature this ADR does not use or
extend: it lets one tenant's entitlement reads transparently redirect to
an ancestor's own subscription (no separate subscription for the child at
all). Phase 13's resale model is the opposite shape — each client tenant
gets its **own** `core.billing.Subscription` row (potentially a different
resale tier than a sibling client under the same agency), so
`inherits_billing` stays `False` (its default) for every tenant
`product/billing/` subscribes. The two mechanisms are not in conflict and
are never both exercised for the same tenant by this phase's own code.

### Idempotency

Subscription **creation** (platform or resale) financially matters most
under client retry (a timed-out request, a double-click) — 13's own brief
names this explicitly. `product/billing/subscriptions.py` therefore
requires a caller-supplied `idempotency_key` on both
`create_platform_subscription()` and `create_resale_subscription()` and
calls `core.billing.subscribe_idempotent()` (P1.11, already implemented)
rather than the plain `subscribe()` — reusing SaaS-OS's own two-step
`core.idempotency` primitive unchanged, never a second idempotency
mechanism. Plan-change and cancellation are not given the same treatment:
both are naturally idempotent at the business-outcome level already
(`upgrade_subscription()`/`cancel_subscription()` — a repeated call
against a subscription already on the target plan, or already canceled,
produces the same end state, not a duplicated side effect the way a
second `create_subscription()` provider call would).

### Provider webhooks (deferred)

No Stripe (or other provider) webhook ingress route exists anywhere in
this repository yet — `core/billing/__init__.py`'s own Non-Goals list
states this plainly ("no HTTP route receives a Stripe webhook yet").
Building one now, with no real Stripe product/price configured
(`ResalePlan`'s auto-created `core.billing.Plan` rows carry no
`provider_price_id` in this phase — see "Provider status" below), would
be new infrastructure with nothing real to verify against. Deferred,
documented, not built — mirrors `docs/ADR/0010-...`'s identical treatment
of Reputation's own deferred provider integration.

### Provider status

Every `product/billing/subscriptions.py` mutation accepts an optional
`provider: BillingProvider | None` parameter, passed straight through to
`core.billing.subscribe_idempotent()`/`upgrade_subscription()`/
`cancel_subscription()` unchanged — when omitted, `core.billing`'s own
default (`StripeBillingProvider`, requiring `STRIPE_API_KEY`) applies,
exactly SaaS-OS's existing behavior, never overridden or special-cased by
this product. No `STRIPE_API_KEY` is configured in this repository's
`.env` today, and no `ResalePlan`'s underlying `Plan` carries a real
`provider_price_id` — so a production call with no explicit `provider`
override fails closed with `BillingProviderError`/a secrets-configuration
error, exactly as it should until a real Stripe product/price is actually
provisioned for a given resale tier (an ops action, out of this phase's
scope, the same "no live payment processing" boundary
`docs/ADR/0010-...` already drew for Reputation's own provider). Tests
inject `core.billing.provider.FakeBillingProvider()` directly.

## Non-Vacuousness / Consequences

- `product/billing/` never imports `stripe`, `core.billing.stripe_provider`,
  or any Stripe-specific type — verified by grep across the new module;
  the only Stripe-shaped value it ever sees is the opaque
  `provider_subscription_id` string `core.billing.Subscription` already
  stores.
- `product.billing` is NOT added to any import-linter CRM-style dependency
  contract in this phase — it needs no other product module's service
  functions; its only cross-module coupling is the standard
  `agency.role_provisioned` event subscription every module already uses
  for permission provisioning.
- Purge: only `billing.resale_plans` (product-owned) is purged when its
  owning tenant is purged (`product/billing/purge.py`) — `core
  .billing_subscriptions` is `FINANCIAL_RETAIN` and `core.billing_plans`
  is `GLOBAL_IDENTITY` in SaaS-OS's own `core/tenancy/retention.py`
  classification (read directly, not assumed): neither is touched by this
  product's own purge participant, and this product does not attempt to
  duplicate or override that decision. A purged reseller tenant's
  `ResalePlan` rows are deleted; the `core.billing.Plan` rows they
  auto-created become orphaned (no `key` collision risk, since each is
  generated from the now-deleted `ResalePlan.id`) — accepted, since
  `core.billing` exposes no `delete_plan()` for any caller to use anyway,
  and an orphaned global Plan carries no tenant data of its own.
