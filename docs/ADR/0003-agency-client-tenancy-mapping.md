# ADR-0003: Agency/Client Tenancy Mapping

Status: ACCEPTED
Date: 2026-09-19

## Context

`docs/ARCHITECTURE.md` §3 already established, at Phase 0, that an agency
maps onto `core.tenancy`'s existing hierarchy as a root tenant and a
client as a child tenant, and that no second tenancy/authorization system
is introduced. What remained undecided at implementation time was whether
this product needs any **product-owned data** to operate that mapping — a
table recording which tenants are "agencies," which are "clients," and
how they relate — or whether the mapping is fully derivable from
`core.tenancy` alone at read time, with zero product-owned duplication.

## Decision

**No new database table for "agency" or "client."**

- **Agency** = a root `core.tenants` row (`parent_id IS NULL`) provisioned
  through `product/agency/provisioning.py::provision_agency()`.
- **Client** = a `core.tenants` row whose `parent_id` is an agency tenant
  (a flat, 2-level model — matches `docs/ARCHITECTURE.md` §3's own
  diagram: Agency → Client A/B/C, no deeper nesting assumed by this
  phase).

Both facts are derived entirely at read time from `core.tenancy`'s
published interface (`core.tenancy.get_tenant()`, `get_descendant_ids()`,
`get_ancestor_chain()`) — this product stores no copy of `tenant_id`,
`name`, `parent_id`, or `status` anywhere of its own. Consequently, **Phase
3 adds zero new product-owned tables and zero new Alembic migrations**
(verified: `product/migrations/versions/` is unchanged by this phase).

This directly satisfies two things asked for explicitly at Phase 3's
start: "do not duplicate generic tenant fields unnecessarily," and "choose
the smallest architecture consistent with existing SaaS-OS contracts."

## Rejected Alternative

A thin `agency.agencies` marker table (`tenant_id` primary key/foreign key
into `core.tenants.id`, plus maybe `created_at`) recording which root
tenants are "real" product agencies, as distinct from any other root
tenant that might exist in the same database for an unrelated reason.

Rejected for now, not permanently:

- No Phase 3 requirement needs to distinguish "a genuine product agency"
  from "any other root tenant" beyond its structural position in the
  hierarchy. In this product's own database, every root tenant is, in
  practice, created through `provision_agency()` — there is no other
  tenant-creation path in this codebase today that would produce an
  ambiguous root tenant.
- A marker table is trivial to add later, non-breaking, the moment a real
  need appears — e.g. a future reseller-configuration phase
  (`docs/ROADMAP.md` Phase 13) that needs to attach agency-specific
  columns nothing in `core.tenants` has room for. Building it now, before
  that need is concrete, would be exactly the kind of speculative
  structure `docs/RESPONSIBILITY-MATRIX.md`'s own Category-B discipline
  (interim, on-demand, not upfront) argues against.
- Similarly rejected: storing a redundant `agency_tenant_id` column on a
  hypothetical `agency.clients` table. In Phase 3's flat 2-level model this
  would always equal `core.tenants.parent_id` for that tenant — a second,
  independently-writable copy of a fact `core.tenancy` already owns and
  maintains transactionally (`create_tenant()`, `move_tenant()`), with a
  real risk of drifting out of sync if a future operation ever changes a
  client's parent without this product remembering to update its own copy
  too. `docs.tenancy.get_tenant(client_tenant_id).parent_id` (or
  `get_ancestor_chain()` for a deeper future hierarchy) is the single
  source of truth this product reads instead.

## Consequences

- `product/agency/provisioning.py::list_clients()` treats every descendant
  `core.tenancy.get_descendant_ids()` returns for an agency as a direct
  client. If a deeper hierarchy is ever introduced (e.g. sub-agencies),
  this function must be revisited — it is not written to distinguish
  "direct child" from "grandchild," because Phase 3 has no such case yet.
- If a real need for agency-specific stored configuration appears in a
  later phase, that phase adds `agency.agencies` (or an equivalently
  scoped table) then, informed by what that need actually requires,
  rather than this phase guessing its shape now.
- This product's `agency` Postgres schema namespace (per
  `docs/ADR/0001-naming-and-identifier-neutrality.md`) is reserved but
  currently empty of tables — `product/agency/` is a pure service+API
  module in Phase 3, not a data-owning one.
