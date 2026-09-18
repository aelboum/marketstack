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

An agency (or a client, if the agency permits it) points a domain
(`app.theiragency.com`) at this product. Resolution needs to happen **before**
`core.identity.get_tenant_context()` can do its job (which resolves by
subdomain/header today) — so this product's own ingress adds a thin
domain-to-tenant-id lookup middleware in front of it:

```
Incoming request (Host: app.theiragency.com)
        │
        ▼
product's own domain-resolution middleware
   (white_label.tenant_domains: domain → tenant_id, TLS cert state)
        │
        ▼
core.identity.get_tenant_context()   ← unchanged, SaaS-OS-owned
        │
        ▼
core.rbac / rest of the ingress chain  ← unchanged, SaaS-OS-owned
```

This is the specific mechanism flagged as Category B (interim C) in
`docs/RESPONSIBILITY-MATRIX.md`: generic enough that SaaS-OS could plausibly
want this for any multi-tenant product with custom domains, but not built
there today, and not worth proposing upstream from a single data point.

TLS certificate provisioning for a custom domain is itself an external
integration concern (D) — e.g. automated via the deployment proxy's ACME
support (`saas-os`'s own Caddy-based proxy already does ACME for its own
domain; this product's own proxy layer extends that per-tenant, an
operational detail decided at Phase 2 implementation time, not here).

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
  never falls through to a default tenant. Mirrors `core.identity
  .get_tenant_context()`'s own documented behavior (a non-enumerating 404 for
  an inaccessible tenant, `saas-os` `docs/MULTI-TENANCY.md` §6).
- Branding assets (logos, etc.) are tenant-owned data — stored through the
  object-storage abstraction in `docs/ARCHITECTURE.md` §5/`docs/RESPONSIBILITY
  -MATRIX.md` ("Object/file storage" row), tenant-namespaced, never a shared
  bucket path.
- An agency's branding must never leak into another agency's rendered UI —
  this is an ordinary tenant-isolation bug class if the fallback-chain
  resolution logic has an off-by-one in the ancestor walk; test this
  explicitly (see `docs/ROADMAP.md` Phase 2).
