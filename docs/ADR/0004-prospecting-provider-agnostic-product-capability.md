# ADR-0004: International, Provider-Agnostic Prospecting Is a Product Capability

Status: ACCEPTED
Date: 2026-09-19

## Context

`docs/ROADMAP.md` Phase 19–20 extends this product's roadmap with an
external prospect-discovery and lead-intelligence capability, functionally
comparable in scope to modern "find and qualify local businesses"
prospecting tooling. The capability must work across multiple countries
from the start (Netherlands, Belgium, Morocco, France, and future
countries), and must source data from multiple, interchangeable external
providers (business discovery, directory, licensed B2B/company-data,
contact enrichment, official/registry, and audit-intelligence providers),
none of which SaaS-OS has any concept of today.

Two architectural risks were identified before any design work began:

1. **Vendor lock-in risk**: naming a specific provider (e.g. Google Places,
   a specific registry API) inside the domain/application layer would tie
   this product's prospecting capability to one vendor's data shape,
   licensing terms, and pricing — the same class of mistake
   `docs/INTEGRATIONS.md` already prevents for every other external
   integration in this product (SMS, WhatsApp, telephony, calendar sync,
   reputation platforms).
2. **SaaS-OS boundary risk**: prospecting is entirely product-specific
   business functionality (comparable to CRM, Marketing, or Conversations,
   all already Category C in `docs/RESPONSIBILITY-MATRIX.md`) — there is no
   plausible argument for any part of it belonging in `saas-os`, which
   `docs/ARCHITECTURE.md` §1 defines as scoped to tenancy, identity,
   billing, audit, and other domain-agnostic platform concerns, not
   business-domain functionality for any one product.

## Decision

1. **Prospecting is entirely a Product capability (Category C), never a
   SaaS-OS Core capability.** No prospecting-specific code, table, schema,
   endpoint, or concept is ever added to `saas-os`. The dependency
   direction is fixed and one-directional:

   ```
   Product Prospecting  →  SaaS Core  →  Infrastructure
   AI Prospecting/Agents →  Product Prospecting → SaaS Core → Infrastructure
   ```

   `SaaS Core → Product Prospecting` never occurs, in either direction,
   under any circumstance — the same rule `docs/ARCHITECTURE.md` §1 already
   states for every other product module, restated here explicitly because
   Phase 19–20 is large enough, and touches enough Category-A mechanisms
   (`core.usage`, `core.billing`, `core.rbac`, `control_plane`), that the
   boundary is worth naming as its own decision record rather than leaving
   it implicit.

2. **Every external data source is provider-agnostic by construction.** No
   provider is named in any domain-layer type, service function signature,
   or database column in a way that would require a rewrite to add or
   replace a provider. `docs/ROADMAP.md` Phase 19.3 defines
   `DiscoveryProvider`, `EnrichmentProvider`, `RegistryProvider`, and
   `AuditProvider` as Protocols, following the exact pattern
   `docs/INTEGRATIONS.md` already establishes for `core.billing`'s Stripe
   adapter and `core.email`'s SMTP adapter. No provider named in
   `docs/ROADMAP.md` Phase 19.1's candidate list (Google Places/Maps
   Platform, DataForSEO, Outscraper, Apollo, Cognism, People Data Labs,
   OMPIC, Dutch/Belgian/French registry sources, or any other) is an
   approved dependency by virtue of appearing there — each is a candidate
   to evaluate, and vendor selection is deferred to the specific
   implementation phase that adds a concrete adapter, per
   `docs/INTEGRATIONS.md`'s closing statement.

3. **The CRM remains the one system of record.** Phase 19.9's handoff design
   writes into Phase 4's existing `crm.contacts`/`crm.companies`/
   opportunity/pipeline entities through their existing services and
   `core.rbac.can()` authorization (per ADR-0002's `get_current_actor`
   pattern) — prospecting never creates a second Company/Contact/
   Opportunity model, and never bypasses CRM's existing authorization
   boundary to write a "prospecting-privileged" record.

4. **No second cross-cutting mechanism is introduced.** Prospecting
   automation (Phase 20) consumes Phase 10's existing trigger/action
   framework; prospecting AI agents (Phase 20.3) register as
   `control_plane` tools per the existing Phase 9.1 pattern; prospecting
   budget/quota controls (Phase 20.2) map onto `core.usage`/`core.billing`;
   prospecting events (Phase 19.10) ride the existing product event
   dispatcher (`docs/ARCHITECTURE.md` §4). No second automation engine, no
   second agent runtime, no second usage/billing system, no second event
   bus.

## Consequences

- A future implementation phase adding a concrete provider adapter (e.g. a
  Google Places `DiscoveryProvider` adapter) is reviewed against this ADR:
  does the domain/application layer still depend only on the Protocol, or
  has a provider-specific type/assumption leaked past the adapter boundary.
- A future implementation phase must re-verify the specific provider's
  current commercial-use, retention, and redistribution terms at the time
  of implementation — `docs/ROADMAP.md` Phase 19.1's findings are a
  snapshot taken during the roadmap spike, not a standing legal clearance.
- Any proposal to add prospecting-specific code to `saas-os` itself (e.g.
  "just put the registry-lookup cache in Core since other products might
  want it") is rejected under this ADR unless and until a second, real
  consuming product demonstrates the same need — the identical
  evidence-before-infrastructure discipline `docs/ARCHITECTURE.md` §4–§5
  already applies to this product's own event dispatcher and workflow
  engine decisions.

## Rejected Alternative

Designing Phase 19–20 around one primary provider (e.g. Google Places as
the default discovery source, with "other providers later" as an
afterthought) to simplify the initial design. Rejected: the brief's
countries (Netherlands, Belgium, Morocco, France) have materially different
registry/identifier landscapes (KVK vs. ICE/RC/OMPIC vs. no equivalent
single registry in some jurisdictions), so a single-provider-first design
would either under-serve non-Dutch countries from day one or require a
rewrite to correct later — exactly the class of avoidable rework
`docs/INTEGRATIONS.md`'s "never hardcode one provider" rule already exists
to prevent for every other integration in this product.
