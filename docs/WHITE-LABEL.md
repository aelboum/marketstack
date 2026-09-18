# White-Label Architecture

Status: PROPOSED. Categorized as Category C/borderline-B in
`docs/RESPONSIBILITY-MATRIX.md` — built inside this product, designed so it
could be donated to SaaS-OS later without a rewrite if a second white-label
product ever needs the same thing.

## 1. Two Distinct Branding Layers

Do not conflate these — they have different owners and different scopes:

1. **Platform default branding.** What a user sees before any tenant-specific
   branding applies (system emails from the platform itself, the marketing
   site, fallback UI chrome). This is where the eventual commercial name
   lives — a single configuration row, per ADR-0001
   (`docs/ADR/0001-naming-and-identifier-neutrality.md`), never a hardcoded
   string anywhere in code.
2. **Agency branding.** An agency's own brand applied across everything its
   own clients see — this is the actual "white-label" requirement: an
   agency's clients should never see this platform's name at all.
3. **Client branding (optional).** An agency may allow individual clients to
   further customize their own branding within limits the agency sets (e.g.
   a client's own logo on a client-facing booking page, while the agency's
   name still appears in account/billing contexts).

Branding resolution is therefore a **fallback chain**, not a flat
per-tenant setting: client → agency → platform default. This directly
mirrors the tenant hierarchy in `docs/ARCHITECTURE.md` §3 — resolving
branding for a tenant means walking up `core.tenant_ancestry` until a branding
record is found, exactly the kind of hierarchy-aware read
`core.usage.aggregate_usage_including_descendants()` already does for a
different concern.

## 2. Data Model (Product-Owned)

`white_label.tenant_branding` (one row per tenant that has customized
branding — absence means "inherit from parent"):

- `tenant_id` (FK into `core.tenants.id`, referential integrity only, per
  `docs/ARCHITECTURE.md` §2.3 — this product never writes to `core.*`)
- Display name, logo asset reference, favicon asset reference
- Color palette (primary/secondary/accent, whatever the design system needs)
- Typography choice, if the product's design system supports more than one
- Custom domain (see §3)
- Login-page branding overrides
- Email branding (from-name, reply-to, header/footer template overrides —
  layered on top of `core.notifications`'s dispatch pipeline, which already
  anticipates "product-supplied templates" per `saas-os`
  `docs/ARCHITECTURE.md` §4's module-ownership table)
- Support contact details, legal links (terms/privacy URLs) — agency's own,
  not this platform's

## 3. Custom Domain Resolution

**Corrected 2026-09-19, post-Phase-2 implementation.** This section
previously claimed SaaS-OS's ingress "resolves tenant by subdomain/header
today" and described this product's domain-resolution middleware as
sitting "in front of" that mechanism. Direct inspection of the pinned
`saas-os` commit (`2a299a3b5fa62e810d87e3ff2d8e844763e6a38b`) shows that
claim was wrong: SaaS-OS has no subdomain- or header-based tenant
resolution anywhere. The actual chokepoint is
`api.dependencies.get_tenant_context(tenant_id: uuid.UUID, actor_id =
Depends(get_current_actor)) -> RequestContext` — `tenant_id` is bound as
an ordinary FastAPI **path parameter** and validated against a real
session membership (`get_membership(tenant_id, actor_id)`); it is never
read from `Host` or any other header. This is the same function
`docs/MULTI-TENANCY.md` section 8 already documents; the "subdomain/
header" framing here was this document's own error, not a description of
anything that ever existed in SaaS-OS.

What this product actually built in Phase 2, given that correction: an
agency (or a client, if the agency permits it) points a domain
(`app.theiragency.com`) at this product. `white_label.tenant_domains`
(domain → tenant_id, TLS cert state) is this product's own table.
`product/white_label/domains.py`'s `DomainResolutionMiddleware` runs
ahead of routing and does exactly this, no more:

```
Incoming request (Host: app.theiragency.com)
        │
        ▼
product's own DomainResolutionMiddleware
   - Host == PUBLIC_DOMAIN or a subdomain of it -> passthrough, untouched
   - otherwise: resolve_tenant_for_domain(host) against
     white_label.tenant_domains
       - found -> request.state.resolved_tenant_id = tenant_id, passthrough
       - not found -> non-enumerating 404 (fail-closed; never falls
         through to any tenant, including the platform's own)
        │
        ▼
ordinary routing / api.dependencies.get_tenant_context()  ← unchanged,
   SaaS-OS-owned, and NOT fed by this middleware -- it still resolves
   tenant_id from the URL path parameter exactly as it always has.
   request.state.resolved_tenant_id is set but has no consumer yet.
```

**Open question, deliberately not resolved here or in Phase 2**: how a
later phase's product routes actually turn a domain-resolved
`request.state.resolved_tenant_id` into the `tenant_id` path parameter
`get_tenant_context()` requires (a redirect/URL-rewrite to a
tenant-scoped path, a frontend bootstrap endpoint that returns the
resolved `tenant_id` for the frontend to embed in its own subsequent
calls, or some other scheme) is explicit future API/application-design
work — see `docs/RISKS-AND-OPEN-QUESTIONS.md`. Building that mechanism
prematurely, before any product route exists to need it, is exactly the
kind of speculative work this roadmap's own discipline (`docs/ROADMAP.md`
Phase 0's "evidence before infrastructure") argues against.

This is still the specific capability flagged as Category B (interim C)
in `docs/RESPONSIBILITY-MATRIX.md`: generic enough that SaaS-OS could
plausibly want a domain→tenant resolution primitive for any multi-tenant
product with custom domains, but not built there today, and not worth
proposing upstream from a single data point.

TLS certificate provisioning for a custom domain is itself an external
integration concern (D) — e.g. automated via the deployment proxy's ACME
support (`saas-os`'s own Caddy-based proxy already does ACME for its own
domain; this product's own proxy layer extends that per-tenant, an
operational detail decided at implementation time, not here). Not built
in Phase 2 — `tls_status` is a stored column with no automation behind it
yet.

## 4. `BrandingProvider` Interface

Following the exact Protocol+adapter pattern SaaS-OS already uses internally
(`core/billing/provider.py` + `stripe_provider.py`, `core/email/provider.py`
+ `smtp_provider.py`):

```
BrandingProvider (Protocol)
    get_branding(tenant_id) -> Branding
```

Every module that needs to render tenant-facing UI, compose a tenant-facing
email, or produce a tenant-facing PDF (an invoice, a report) calls this
interface — never reads `white_label.tenant_branding` directly. This is what
makes the fallback-chain resolution logic (§1) live in exactly one place,
and what would let this interface be re-pointed at a future SaaS-OS-provided
implementation without touching every call site, should this ever be
upstreamed (Category B path, per `docs/RESPONSIBILITY-MATRIX.md`).

## 5. What Is Explicitly Out of Scope for the Initial Phase

- Per-tenant custom CSS/arbitrary theming beyond the defined palette/logo/
  typography fields — a fixed, generous set of branding fields, not an
  open-ended theme editor.
- White-labeling the underlying AI provider's own branding (e.g. "powered
  by Claude" disclosures where a provider's terms require them) — a legal
  question for the Integrations phase, not an architecture question here.
- Native mobile app white-labeling — no mobile app exists in this roadmap.

## 6. Security Considerations

- Custom domain → tenant resolution must fail closed: an unrecognized domain
  never falls through to a default tenant. Mirrors `api.dependencies
  .get_tenant_context()`'s own documented behavior (a non-enumerating 404 for
  an inaccessible tenant, `saas-os` `docs/MULTI-TENANCY.md` §6) — corrected
  module path, 2026-09-19; this was previously mis-cited as
  `core.identity.get_tenant_context()`, which does not exist.
- Branding assets (logos, etc.) are tenant-owned data — once a real
  object-storage mechanism exists (no `docs/ARCHITECTURE.md` section covers
  this today; tracked only as the "Object/file storage" row in
  `docs/RESPONSIBILITY-MATRIX.md`, not yet built — corrected 2026-09-19, this
  previously cited a nonexistent `docs/ARCHITECTURE.md` §5, which is the
  Workflow/Automation Execution Substrate section, unrelated), it must be
  tenant-namespaced, never a shared bucket path. Phase 2 ships
  `logo_asset_ref`/`favicon_asset_ref` as bare string references only, no
  upload/storage mechanism yet (`docs/ROADMAP.md` Phase 2.3).
- An agency's branding must never leak into another agency's rendered UI —
  this is an ordinary tenant-isolation bug class if the fallback-chain
  resolution logic has an off-by-one in the ancestor walk; test this
  explicitly (see `docs/ROADMAP.md` Phase 2).
