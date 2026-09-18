# ADR-0001: Working Name and Identifier Neutrality

Status: ACCEPTED
Date: 2026-09-18

## Context

The product being planned in this repository has a temporary working name,
"MarketStack," used only in conversation and planning documents. The final
commercial/product name has not been chosen and is expected to change before
launch. SaaS-OS itself (`docs/architecture/SAAS-OS-DISTRIBUTION-ARCHITECTURE.md`
in the `saas-os` repository) already established the precedent that a
consuming project's identity is its own concern, entirely decoupled from
SaaS-OS's own naming — this ADR applies the same discipline one level down,
to this product's own internal code.

Committing "MarketStack" into code, package names, database identifiers, or
infrastructure names would make a future rename expensive and error-prone
(the exact failure mode ADR-0015 in `saas-os` avoids by keeping products out
of that repository entirely). Renaming a display string in configuration is
cheap; renaming a Python package, a Postgres schema, twenty Docker image
tags, and a fleet of environment variable names across every deployment
environment is not.

## Decision

1. **"MarketStack" is a working name only.** It is not used in code, package
   names, class/function/variable names, database schema or table names,
   Docker image names, environment variable names, URLs, or any other
   technical identifier, in this repository or any repository it produces.
2. **The neutral technical identifier is `product`.** Where an identifier is
   required and no more specific name applies:
   - Python backend package/import root: `product` (e.g. `product.crm`,
     `product.accounting`) — mirroring the exact vocabulary SaaS-OS's own
     `docs/ARCHITECTURE.md` §1 already uses for this layer ("Product —
     everything specific to one SaaS product").
   - Postgres schema namespace per module: `crm.*`, `marketing.*`,
     `conversations.*`, `accounting.*`, `agency.*`, `automation.*`, etc. —
     one schema per module, inside the one physical database this project
     owns, per `saas-os`'s `docs/DATA-ARCHITECTURE.md` §1 and
     `docs/ADR/0016-independent-database-migration-histories.md`. No
     `MarketStack`-named schema exists anywhere.
   - The project's own Alembic migration-tracking table uses Alembic's
     ordinary default (`alembic_version`) — distinct from `saas-os`'s own
     `alembic_version_saas_os`, per the two-independent-environments model
     (`docs/REPOSITORY-STRATEGY.md`).
   - Docker image/service names: `product-api`, `product-worker`,
     `product-frontend`.
   - Environment variable prefix for anything specific to this product
     (not already owned by `saas-os`'s own `infra/secrets` conventions):
     `PRODUCT_*` (e.g. `PRODUCT_STORAGE_BUCKET`).
   - Frontend package name: `product` (or a scoped npm name chosen at
     Phase 1.5, e.g. `@internal/product-web` — not brand-specific either
     way).
3. **The end-user-facing display name is a runtime configuration value, not
   a code identifier.** White-labeling (`docs/WHITE-LABEL.md`) already
   requires every tenant/agency to see its own brand name, logo, and colors
   — the platform's own default display name (used before a tenant applies
   its own branding, e.g. in system emails, the marketing site, or
   fallback UI chrome) is one more row in that same configuration
   mechanism, never a hardcoded string. Changing the commercial name later
   is changing one configuration value, never a code change.
4. **The repository directory itself** (currently `marketstack` on disk) is
   not a binding technical identifier — it is a filesystem convenience.
   Renaming it (e.g. to a neutral name, or to the eventual commercial name)
   at any point requires no code change under this decision. Renaming it is
   not performed as part of this planning phase (see
   `docs/RISKS-AND-OPEN-QUESTIONS.md` — it is listed there as a decision
   for you, not assumed here).

## Consequences

- Every phase in `docs/ROADMAP.md` that introduces a new identifier (a
  package, a schema, a Docker service, an env var) must use `product` (or a
  more specific neutral sub-name, e.g. `crm`, `accounting`) — never the
  working name. This is a review gate: a PR introducing a `marketstack_*`
  identifier is a defect, not a style nit, exactly as SaaS-OS treats a
  dependency-rule violation as a defect (`saas-os` `docs/ARCHITECTURE.md`
  §2).
- The final commercial name, once chosen, is applied by (a) setting the
  default branding configuration value from item 3, and (b) optionally
  renaming the repository directory and any external-facing DNS/deployment
  names — never a source-code rename.

## Rejected Alternative

Using "MarketStack" as the actual package/schema name now, with a "rename
later" plan. Rejected for the same reason SaaS-OS's own distribution
architecture investigation rejected copy-based project templates (`saas-os`
`docs/architecture/SAAS-OS-DISTRIBUTION-ARCHITECTURE.md` §5): a rename touching
dozens of identifiers across code, schema, and infrastructure is exactly the
class of mechanical, error-prone, easy-to-miss-a-spot operation this decision
exists to avoid needing at all.
