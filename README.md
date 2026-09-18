# Product (working name: "MarketStack") — Roadmap & Architecture

Status: **PLANNING ONLY. No implementation has started.** This repository currently
contains documentation and architectural decisions only — no source code, no
dependencies, no database schema, no CI.

"MarketStack" is a temporary working name used in conversation and planning
documents only. See `docs/ADR/0001-naming-and-identifier-neutrality.md` for the
binding rule: it must never appear in code, package names, database identifiers,
Docker image names, environment variables, or any other technical identifier.
Throughout this repository's own code (once it exists), the neutral identifier
`product` is used instead.

## What this is

A HighLevel-style, agency-oriented SaaS platform (CRM, marketing, conversations,
telephony, AI, appointments, automation, reputation, agency/white-label
management, SaaS resale/billing, templates, reporting, and a deliberately small
accounting module) built **on top of** the `saas-os` platform foundation
(`C:\Users\imran\Documents\saas-os`), consumed as a versioned package dependency,
never as a fork or a merge into that repository.

## Documents in this repository

| Document | Purpose |
|---|---|
| `docs/ADR/0001-naming-and-identifier-neutrality.md` | Binding decision on the working name and technical identifiers |
| `docs/ARCHITECTURE.md` | Product-layer architecture: the four-layer model restated for this product, module boundaries, internal dependency rules |
| `docs/RESPONSIBILITY-MATRIX.md` | For every capability area: is it (A) already in SaaS-OS, (B) a generic gap SaaS-OS should eventually fill, (C) product-specific, or (D) an external integration — and why |
| `docs/ROADMAP.md` | Phase-by-phase implementation plan, in SaaS-OS's own template discipline (Objective/Dependencies/Scope/Tests/Security/Acceptance/Rollback/Outcome/Checkpoint) |
| `docs/WHITE-LABEL.md` | White-label/branding architecture |
| `docs/ACCOUNTING-SCOPE.md` | Mini-accounting module scope, explicit out-of-scope list, Dutch-market considerations |
| `docs/INTEGRATIONS.md` | External integration strategy and adapter pattern |
| `docs/SECURITY-PRIVACY.md` | How this product inherits and extends SaaS-OS's security/privacy boundaries |
| `docs/REPOSITORY-STRATEGY.md` | How this repository consumes `saas-os` (packaging, migrations, versioning) |
| `docs/RISKS-AND-OPEN-QUESTIONS.md` | Unresolved architectural questions and the specific decisions that need your approval before Phase 1 starts |

## Reading order

1. `docs/ADR/0001-naming-and-identifier-neutrality.md` (short, settles a recurring question)
2. `docs/ARCHITECTURE.md`
3. `docs/RESPONSIBILITY-MATRIX.md`
4. `docs/REPOSITORY-STRATEGY.md`
5. `docs/ROADMAP.md`
6. The remaining documents, as needed per phase

## Development

**Status: Phase 1 (Repository Foundation) + Phase 2 (Product Foundation)
only.** This repository has a working application composition root, its
own independent migration environment, a full local/CI check suite, and
this product's own shared foundation (`Money`/phone-number value
objects, tenant-scoped settings, the product event dispatcher, white-
label branding resolution, custom-domain resolution) -- but no
business-domain product functionality yet (no CRM, no product API
routes beyond `/auth/*` and `/healthz`). See `docs/ROADMAP.md` for what
each later phase adds.

```bash
# Backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # .venv/bin on macOS/Linux
cp .env.example .env   # fill in local-only values; .env is gitignored

# Bootstrap the database (saas-os's own core migrations, then this
# product's own -- docs/REPOSITORY-STRATEGY.md)
python scripts/bootstrap-db.py

# Frontend
cd frontend && npm install

# Run the checks (mirrors CI exactly -- .github/workflows/ci.yml)
bash scripts/check-backend.sh       # ruff, ruff format, pyright, pytest, import-linter
bash scripts/check-frontend.sh      # typecheck, eslint, next build
bash scripts/check-security.sh      # pip-audit, npm audit, detect-secrets (needs the `security` extra)
bash scripts/check-migrations.sh    # disposable-Postgres migration bootstrap proof (needs Docker)
bash scripts/check-integration.sh   # tests/**/test_*_integration.py against disposable Postgres + Redis (needs Docker)
bash scripts/check-docker.sh        # docker build + runtime smoke test (needs Docker)
bash scripts/check-all.sh           # backend + frontend + security (fast checks only)
```

## Governing principle

```
Product  ──depends on──>  SaaS Core  ──depends on──>  Infrastructure
Product  ──depends on──>  AI Control Plane  ──depends on──>  SaaS Core
```

SaaS-OS is never modified by this product's work. Every capability this product
needs that SaaS-OS does not already provide is either built inside this
repository (if product-specific) or flagged as a proposal for the SaaS-OS
maintainers to evaluate separately (if genuinely generic) — never added directly
to `saas-os` as a side effect of building this product. See
`docs/RESPONSIBILITY-MATRIX.md` for the capability-by-capability reasoning.
