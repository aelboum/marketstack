# ADR-0002: Agency Cross-Tenant Route Authorization

Status: ACCEPTED
Date: 2026-09-19

## Context

`docs/ROADMAP.md` Phase 3.3 describes delegated administration as
"agency-facing UI/API over `core.rbac`'s existing `SUBTREE`-scoped role
assignment," and `docs/ARCHITECTURE.md` §3 states that an agency's
`SUBTREE`-scoped role at its own (root) tenant automatically reaches every
current and future client tenant, per `core.rbac`'s own live-re-evaluation
semantics. Implementing Phase 3's API layer required choosing which
existing SaaS-OS FastAPI dependency gates a route where the acting agency
user has no direct `TenantMembership` at the specific client tenant being
acted on — only a `SUBTREE`-scoped role at an ancestor.

Direct inspection of the installed `saas-os` package at the pinned commit
(`2a299a3b5fa62e810d87e3ff2d8e844763e6a38b`) found that this case is not
supported by the platform's existing tenant-resolution dependency:

- `api.dependencies.get_tenant_context(tenant_id, actor_id)` calls
  `core.identity.service.get_membership(tenant_id, actor_id)` and raises a
  non-enumerating 404 if it returns `None`.
- `get_membership()` (`core/identity/service.py`) is a direct, exact-tenant
  lookup — `SELECT ... WHERE tenant_id = :tenant_id AND user_id =
  :user_id`. It does not walk `core.tenant_ancestry`, and does not consult
  `core.rbac`'s `SUBTREE`-scoped roles at all.
- No test or code path anywhere in `saas-os` (including its own
  `examples/reference-consumer/reference_consumer/scenarios.py` and
  `tests/test_reference_consumer_scenarios_integration.py`, which exercise
  `SUBTREE` reach extensively) ever calls `get_tenant_context()` with a
  `SUBTREE`-only actor. Every existing `SUBTREE` test calls
  `core.rbac.authorization.can()` directly, never through the HTTP ingress
  layer.

Consequence: an agency owner holding a `SUBTREE`-scoped role at the agency
tenant, but no direct membership at a specific client tenant, would get a
404 from `get_tenant_context()` on any route gated by it for that client
— even though `core.rbac.can()` would correctly authorize the same actor
for the same operation.

## Decision

For the specific set of Phase 3 routes where an agency actor operates on a
client tenant it may only reach via `SUBTREE` (not direct membership),
`product/agency/routes.py` uses `api.dependencies.get_current_actor`
(authentication only — resolves the session to a `user_id`, no
tenant-membership check) as the FastAPI dependency, and passes that
`actor_user_id` directly into the underlying `core.rbac`/`core.identity`/
`core.tenancy` service function (`create_invitation`, `assign_role`,
`create_delegation`, `create_deny`, `create_support_access_request`,
`approve_support_access`, etc., and this product's own
`provision_client()`/`list_clients()`). Every one of those functions
performs its own independent `core.rbac.can()` authorization check
internally (confirmed by reading each one directly) — so this is a choice
of ingress dependency for a cross-tenant operation, not a bypass of any
authorization boundary. The real authorization decision still flows
through `core.rbac.can()` in every case; only the ingress-level
"does this actor have any membership foothold at this exact tenant"
pre-check (which `get_tenant_context()` performs for the ordinary,
same-tenant case) is not applicable here and is not used.

`get_tenant_context()`/`require_permission()` remain the correct
dependency for the ordinary case — a direct member of a tenant acting on
that tenant's own data — and this decision does not touch, modify, or
propose changing either. Phase 4+ business-domain routes (CRM, etc.), where
the acting user is expected to be a direct member of the tenant whose data
they're touching, should continue to use `get_tenant_context()`/
`require_permission()` as `saas-os`'s own reference-consumer pattern
demonstrates, not the pattern this ADR describes.

## Addendum (found while writing the Phase 3.3 test suite): delegation's anti-amplification check has the identical, narrower gap

While testing `product/agency/delegation.py`, a second, related SaaS-OS
behavior was found empirically (a test failed, not assumed in advance):
`core.rbac.service._actor_reaches_tenant_at_scope()` — the anti-
amplification check `create_delegation()` runs before creating a grant —
checks ONLY a direct `TenantMembership` + role at its own `tenant_id`
argument for a `SELF`-scope check. Unlike `can()`, it does not fall back
to walking ancestors for a `SUBTREE`-scoped role reaching the target, even
though its own docstring calls the `SELF` case "equivalent to plain
can() at tenant_id" — that claim does not hold: `can()`'s own
target-tenant handling additionally checks delegation grants at the
target and then walks ancestors for a `SUBTREE` role reaching down;
`_actor_reaches_tenant_at_scope()`'s `SELF` branch does neither.

Consequence: an agency owner (who, by this product's own Phase 3.1
design, holds no direct membership at any client — only inherited
`SUBTREE` reach from the agency tenant) cannot create a `SELF`-scoped
delegation targeted directly at a specific client tenant, even for a
permission `can()` clearly already authorizes them for there. They CAN
create a `SUBTREE`-scoped delegation at the agency tenant itself (where
they hold a genuine direct membership + role), which then correctly
reaches every current and future client, same as an ordinary `SUBTREE`
role would.

**Decision**: `product/agency/delegation.py`'s API is unchanged (it
already accepts an arbitrary `tenant_id` + `scope_mode` and passes
authorization through to `core.rbac` unmodified, which is correct — it
must not silently work around this). The constraint is documented at the
one place a caller needs to know it:
`tests/agency/test_delegation_integration.py
::test_delegation_create_and_revoke_round_trip`'s own docstring, and
here. `create_deny()` has no equivalent constraint (it performs no
anti-amplification check at all — see its own docstring:
"a deny can only remove authority, never grant more") — an agency owner
CAN deny a specific principal at one specific client directly, via their
ordinary `SUBTREE` reach.

This is not fixed by, or fixable by, this product — it is `saas-os`'s
own function, and changing it is out of bounds for the same reason as
Finding #1 above. If Phase 4+ ever needs an agency owner to delegate a
narrow, single-client-scoped permission without first holding direct
membership there, that is a real, separate open question for `saas-os`'s
own maintainers (whether `_actor_reaches_tenant_at_scope()`'s `SELF`
branch should also consult ancestor `SUBTREE` roles, matching `can()`),
not something to work around product-side.

**Resolved 2026-09-19.** SaaS-OS commit
`1d6fd07a0c3ce2dd8a12c09dac86b019781ee6c6` ("fix: restore invitation
acceptance and delegation scope consistency") fixed exactly this: the
`SELF` branch of `_actor_reaches_tenant_at_scope()` now also walks
ancestors for a `SUBTREE`-scoped role reaching the target (via a shared
`_ancestor_grants_subtree_permission()` helper), matching `can()`'s own
behavior — an ancestor's `SELF`-only role still does not qualify for
either branch, unchanged and correct. **This required zero product-side
code changes to take effect** — `product/agency/delegation.py` already
passed `tenant_id`/`scope_mode`/`permission_id` straight through to
`core.rbac.create_delegation()` unmodified, exactly the "must not
silently work around this" decision recorded above. The moment the
upstream fix landed, the already-correct product code started working.
`tests/agency/test_delegation_integration.py` now includes a passing
test proving an agency owner with only ancestor `SUBTREE` reach (no
direct membership at the client) can create a `SELF`-scoped delegation
there directly; the constraint note in that test's docstring is marked
resolved, not deleted.

## Rejected Alternative

A product-side replacement dependency (e.g. a "SUBTREE-aware"
`get_tenant_context()` equivalent that falls back to a `core.rbac.can()`
check when direct membership is absent, constructing an equivalent
`RequestContext`). Rejected for now: every literal Phase 3 requirement is
satisfiable without it, and building it on spec, before a second concrete
need demonstrates the right shape for such a dependency (e.g. whether it
should also carry rate-limiting-by-tenant, `RequestContext.membership_id`
semantics, etc.), would be exactly the "infrastructure before evidence"
pattern this roadmap's own doctrine argues against elsewhere (see
`docs/ARCHITECTURE.md` §4 and §5's identical reasoning for deferring a
generic event bus and a workflow engine). If a second, equally-shaped need
for this pattern appears in a later phase, revisit building a shared
dependency then, informed by two real use cases instead of one guessed
one.

## Related, Separately-Tracked SaaS-OS Limitation

While implementing this phase, `core.identity.service.accept_invitation()`
was found to be non-functional at the pinned commit, by SaaS-OS's own
documented design trade-off (its own docstring: "Currently non-functional
end to end... this function always raises `InvitationInvalidError`, for
every token, valid or not" — `core.invitations` is fully RLS-protected and
the function's token-resolution step has no tenant context yet to scope
that read to). This is unrelated to the `get_tenant_context()` finding
above (a different function, a different mechanism), but is recorded here
because it was found during the same investigation. See
`product/agency/onboarding.py`'s own module docstring and the Phase 3
implementation report for how this product's own code handles it (builds
the wrapper, tests document the current failure explicitly, no interim
workaround was built without the user's sign-off).

**Resolved 2026-09-19.** The same SaaS-OS commit as the delegation fix
above, `1d6fd07a0c3ce2dd8a12c09dac86b019781ee6c6`, fixed this too:
`accept_invitation()` now takes a required `tenant_id` parameter and
resolves the token inside `infra.db.tenant_session_scope(tenant_id)` from
the start — no untenanted read, no RLS gap. `tenant_id` only ever scopes
the lookup; it is never a source of authority (a wrong `tenant_id` finds
no row and raises the identical `InvitationInvalidError` as any other
invalid token — the token itself remains the sole bearer credential,
unchanged). This product now consumes the fixed API directly
(`product/agency/onboarding.py::accept_client_invitation()` passes
`tenant_id` straight through, with zero product-side pre-validation of
the token/tenant pairing — `accept_invitation()`'s own RLS-scoped query
already is the complete, correct validation). No product-side workaround
was ever built while this was blocked, and none was needed once it was
fixed. `tests/agency/test_onboarding_integration.py` now proves the full
send → accept → assign-starting-role chain end-to-end against a real
disposable Postgres, plus wrong-tenant, expired, revoked, already-
accepted, and concurrent-acceptance cases, all failing closed as
expected.

## Addendum (Phase 4): CRM routes also require the `get_current_actor` pattern, not `get_tenant_context()`

The "Decision" section above states: "Phase 4+ business-domain routes
(CRM, etc.), where the acting user is expected to be a direct member of
the tenant whose data they're touching, should continue to use
`get_tenant_context()`/`require_permission()`... not the pattern this ADR
describes." **This is corrected here — it does not hold, and Phase 4's
implementation does not follow it.**

That line was written speculatively in Phase 3, before Phase 4 was
designed, on the unexamined assumption that CRM's own actors would always
be direct tenant members. `docs/ROADMAP.md` Phase 4's own isolation
requirement — "Parent agency access follows the existing approved
SUBTREE model where applicable" — means an agency owner, who by Phase
3.1's own design holds no direct `TenantMembership` at any client (only
inherited `SUBTREE` reach from the agency tenant), must be able to
read/manage a client's CRM data. `get_tenant_context()` would 404 that
agency owner on any CRM route gated by it, for the identical reason this
ADR's original "Decision" section already documented for the agency
module itself — this is not a new finding about SaaS-OS, it is a
correction of this document's own earlier, untested extrapolation.

**Corrected decision**: `product/crm/routes.py` uses
`api.dependencies.get_current_actor`, exactly like
`product/agency/routes.py`. Unlike the agency module's own operations
(which call self-authorizing `core.rbac`/`core.identity` functions
directly), CRM tables are entirely product-owned — Core has no built-in
authorization for `crm.*` at all — so **every CRM service function
performs its own `core.rbac.can()` check** with a product-defined
permission (`product/crm/permissions.py`) before touching any `crm.*`
row. This is not optional: without it, any authenticated user supplying
a real `tenant_id` in the URL could read or write any tenant's CRM data,
since nothing else would gate it (the same class of gap
`provision_client()`'s own `agency.client` permission check closes for
`core.tenancy.create_tenant()`, applied here to a product-owned table
instead of a Core-owned one).

**Generalized consequence, superseding the narrower claim above**: every
current and future product module where an agency needs `SUBTREE`-level
access to a client's own data — not just CRM, but Marketing,
Conversations, Appointments, Accounting, and any other Phase 5+ module
with the identical agency/client shape — needs this same pattern:
`get_current_actor` at the ingress layer, and the module's own service
functions performing their own `core.rbac.can()` checks against their
own product-defined permissions before touching their own tables.
`get_tenant_context()`/`require_permission()` remain correct only for a
route where direct tenant membership is actually guaranteed for every
legitimate caller — which, given this product's own agency/client model,
is a narrower case than "any business-domain route" the original
"Decision" section assumed. There is currently no route anywhere in this
product that actually uses `get_tenant_context()`/`require_permission()`
for product-owned data; that pattern remains available for a future case
that genuinely has no cross-tenant agency-access requirement, but none
has been built yet.

## Consequences

- Every current and future product route that operates on agency/client
  tenant data — not only the original Phase 3 agency-management routes,
  but also Phase 4's CRM routes and any later module with the same
  shape — must use `get_current_actor`, not `get_tenant_context()`/
  `require_permission()`. A future contributor reaching for
  `require_permission()` on such a route will find it 404s for a real,
  `SUBTREE`-authorized agency actor — this ADR is the record of why, and
  where the correct pattern lives.
- Every module built this way must perform its own `core.rbac.can()`
  authorization check(s) in its own service layer — there is no ingress-
  level substitute once `get_tenant_context()` is not used, and Core
  provides none for a product-owned table.
- This product has not asked `saas-os`'s maintainers to add SUBTREE-aware
  ingress resolution. If this pattern needs to generalize later (a second
  real use case, not just Phase 3's), that is the trigger to revisit this
  decision, not a schedule. Phase 4 is now that second real use case, and
  the decision was to repeat the proven pattern rather than build a
  shared dependency — see "Rejected Alternative" above, whose reasoning
  still applies: two real use cases now exist, but neither has yet needed
  anything `get_current_actor` + service-layer `can()` doesn't already
  provide (e.g. neither needs `RequestContext.membership_id` or
  tenant-scoped rate limiting), so building a shared abstraction remains
  premature, not overdue.
