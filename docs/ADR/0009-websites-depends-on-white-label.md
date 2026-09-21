# ADR-0009: Websites May Depend on White-Label (One-Directional)

Status: ACCEPTED
Date: 2026-09-21

## Context

`docs/ROADMAP.md` Phase 11.1's own Dependencies line names "Phase 2.3
(branding, applied to published pages)" explicitly, and its own Acceptance
Criteria requires "a page can be built, published, and rendered correctly
under the tenant's own branding." `product/white_label/branding.py` already
implements exactly this resolution (`BrandingProvider`/`DbBrandingProvider`,
a fallback chain across client -> agency -> platform default) — it is not a
capability Websites would otherwise have to invent, and its own module
docstring states the intended consumption shape plainly: "every module that
needs to render tenant-facing UI... calls this interface -- never reads
`white_label.tenant_branding` directly."

`docs/ARCHITECTURE.md` §2.2 offers exactly two sanctioned paths for one
module needing another's capability: promote a genuinely generic capability
to `product/foundation/`, or react to another module's state change via the
event dispatcher. Branding resolution fits neither: it is not domain-agnostic
(it is inherently "resolve this tenant's own `white_label.tenant_branding`
row"), and it is not a reaction to a discrete event -- a public page render
needs the *current* resolved branding at read time, not a stream of past
branding changes to reconstruct it from. This is the same shape
`docs/ADR/0005-...` already named and resolved for
Marketing/Appointments -> CRM and `docs/ADR/0006-...` for AI -> CRM/
Conversations/Telephony: a live, synchronous read against an already-
published interface, for a real, roadmap-specified purpose.

## Decision

1. `product.websites` MAY import `product.white_label`'s own published
   `BrandingProvider` interface (`product/white_label/branding.py`) --
   never `product.white_label.models` directly, and never any other product
   module's internals. `product.white_label` may NEVER import
   `product.websites` -- the dependency is one-directional only, matching
   the actual data-flow direction (branding is upstream configuration;
   Websites is a downstream consumer, read-only).
2. `product.websites` remains fully independent from every other product
   module (`agency`, `crm`, `marketing`, `conversations`, `telephony`,
   `ai`, `appointments`, `automation`, `reputation`, `billing`,
   `accounting`, `reporting`, `templates`, `integrations`) -- this
   exception is narrow and specific to White-Label, not a general loosening
   of §2.2's rule, and not a license for Websites to depend on CRM (a
   published page never reads CRM data directly; any future funnel/
   lead-capture integration, per `docs/ROADMAP.md` Phase 11.2's own
   dependency on Phase 6.3, is out of this decision's scope and would need
   its own review when that subphase is actually built).
3. Enforced with import-linter, not only documentation
   (`pyproject.toml`):
   - `"product.websites"` is removed from the "Product modules do not
     depend on each other directly" independence contract's `modules`
     list -- it now has its own, more precise rule instead of the blanket
     one, mirroring exactly how Phase 6/9/10 removed
     `product.marketing`/`product.appointments`/`product.ai`/
     `product.automation` for their own CRM edges.
   - A new `forbidden`-type contract, "Websites does not depend on any
     product module except White-Label"
     (`source_modules = ["product.websites"]`, `forbidden_modules` = every
     product module except `product.white_label`).
   - A new `layers`-type contract, "Websites may depend on White-Label,
     never White-Label on Websites" (`layers = ["product.websites",
     "product.white_label"]`).

## Non-Vacuousness Proof (performed, not assumed)

Verified for real against the actual repository at implementation time:

1. `product.websites.routes` imports `product.white_label.branding
   .DbBrandingProvider` (the real, shipped import,
   `product/websites/routes.py::public_get_page_route()`) — `lint-imports`
   reports this **kept** by the new layers contract.
2. `lint-imports` run against the full repository after this change: **13
   contracts kept, 0 broken** (up from 11 before this ADR) — the two new
   contracts are additive, and every pre-existing contract, including
   every other module's own continued isolation from `product.websites`
   (unchanged in each of their own `forbidden_modules` lists), remains
   intact.
3. `product.white_label` was not modified by this change at all — it
   still appears in the independence contract's own `modules` list
   (unchanged), so it still cannot import `product.websites` or any other
   product module; this ADR grants Websites an edge *to* White-Label, never
   the reverse.

## Rejected Alternative

Duplicating a small "resolve this tenant's own display name/colors"
function inside `product/websites/` itself, reading
`white_label.tenant_branding` directly or maintaining a second, parallel
resolution. Rejected for the identical reason
`docs/ADR/0005-...`'s own Rejected Alternative section already argues
against a parallel projection: `DbBrandingProvider`'s own fallback-chain
logic (client -> agency -> platform default, fail-closed on an
unrecognized tenant) is non-trivial and already correctly implemented and
tested (`docs/ROADMAP.md` Phase 2.3's own adversarial cross-agency test);
re-deriving it would risk a second, subtly different implementation
drifting from the first, and `white_label/branding.py`'s own module
docstring explicitly names "never reads `white_label.tenant_branding`
directly" as the rule this ADR is honoring, not working around.

## Consequences

- `product/websites/routes.py` is the one place in this product that
  imports across the `websites -> white_label` boundary — the resolution
  happens only at public-page-render time, a pure read, no mutation, no
  new authorization risk (`DbBrandingProvider.get_branding()` performs no
  write).
- A future contributor adding a second `product.websites -> product
  .white_label` call site should do so through this same narrow surface
  (`BrandingProvider`) rather than reading `white_label.tenant_branding`
  directly — not mechanically enforced, a code-review expectation this ADR
  records, mirroring `docs/ADR/0005-...`'s own identical note.
- `product.websites`'s own custom-domain field
  (`product/websites/models.py::Website.custom_domain`) is explicitly NOT
  wired into `product/white_label/domains.py::DomainResolutionMiddleware`
  by this decision or by Phase 11.1's own implementation -- resolving a
  domain to a tenant's *dashboard* (White-Label's own concern) and
  resolving a domain to a *published website* are structurally separate
  questions; this ADR grants Websites a read into White-Label's own
  *branding* resolution only, not its domain-routing middleware. Wiring
  the two together, if ever needed, is a materially different, larger
  decision than this one and requires its own review.
