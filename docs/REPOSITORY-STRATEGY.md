# Repository & Dependency Strategy

Status: PROPOSED, following `saas-os`'s own accepted conclusion
(`docs/architecture/SAAS-OS-DISTRIBUTION-ARCHITECTURE.md`,
`docs/ADR/0015-saas-os-distribution-and-consumer-boundary.md`,
`docs/ADR/0016-independent-database-migration-histories.md`,
`docs/ADR/0017-saas-os-api-application-boundary.md`, all Accepted in
`saas-os`) rather than re-deriving it independently. `saas-os` already ran
this investigation (candidate architectures A through H, a decision matrix,
a security analysis) and settled on a specific model with a working
reference implementation (`examples/reference-consumer/` in `saas-os`).
This document applies that settled model to this specific product.

## Decision: this repository consumes `saas-os` as a versioned package

- **This is a separate repository from `saas-os`.** It is never merged into
  `saas-os`, never placed under `saas-os`'s `products/` directory (which
  `saas-os` `docs/ADR/0015-...` rule 11/12 explicitly forbids for any real
  product), and never a fork of `saas-os`.
- **Dependency direction**: this repository's `pyproject.toml` depends on
  `saas-os`; `saas-os` never depends on this repository, in any form, at any
  time (`saas-os` ADR-0015 rule 5).
- **Distribution channel**: a pinned Git/VCS dependency initially —
  `saas-os @ git+https://<host>/<org>/saas-os@<commit-sha>` — per `saas-os`
  ADR-0015 rules 6–8. Pin an exact commit SHA, not a mutable tag, for the
  same supply-chain reason `saas-os`'s own distribution investigation gives
  (§12 of that document): a tag can move, a commit SHA cannot.
- **Upgrade discipline**: SemVer, covering `saas-os`'s Python API surface,
  its migrations, its Contract schema, and its AI Control Plane registration
  API as one coordinated release (`saas-os`'s own investigation §8). This
  product adopts a patch/minor bump whenever convenient; a major bump is a
  deliberate, reviewed decision, never forced by SaaS-OS's own release
  schedule.
- **Move to a private package index later, on evidence** — a specific pain
  point (e.g. "which commit SHA are we even on" becoming a recurring
  question), not a scheduled migration. Not needed at launch.

## Scaffold: start from `examples/reference-consumer`, don't design from scratch

`saas-os`'s `examples/reference-consumer/` is not a toy — it is the
architecture-validation fixture (ADR-0018 there) that already proves, against
a real installed wheel and a real disposable Postgres database, every
mechanical piece this product needs:

- Importing `core`, `infra`, `api`, `control_plane` as an ordinary installed
  package dependency, never a path hack.
- Its own application entrypoint built on `api.platform.build_platform_app()`
  (ADR-0017).
- Its own, separate Alembic migration environment and version-tracking table
  (see next section).
- Its own API route, registered against its own `core.rbac` permission.
- Its own AI Control Plane tool, registered the sanctioned way.
- Its own tenant-purge participant (`core.tenancy.purge_participants
  .TenantPurgeParticipant`), so this product's own data is correctly
  removed/anonymized when a tenant is purged.
- `reference_consumer/scenarios.py` additionally demonstrates the full
  agency/client tenancy pattern this product's Phase 3 (`docs/ROADMAP.md`)
  builds on: hierarchical tenancy, scoped roles, delegation, explicit deny,
  service accounts, support access, hierarchy-aware billing/usage.

**Phase 1.1** (`docs/ROADMAP.md`) is: copy the *structural pattern* of
`reference-consumer` (directory shape, `app.py` composition, migration
wiring, `pyproject.toml` shape) into this repository — never its business
logic, and never as a live dependency on the `saas-os` repository's own
working tree. This mirrors exactly how `saas-os` ADR-0015 rule 9–10 describes
a scaffold's purpose: copied once, then this product owns it outright.

## Database migrations: two independent Alembic environments, one database

Per `saas-os` ADR-0016 (Accepted) and the distribution investigation §6:

```
This product's one physical Postgres database

  core.*, control_plane.*        ← owned by saas-os
      tracked by: alembic_version_saas_os
      script directory: shipped inside the installed `saas-os` package
      applied by: `saas-os`'s own migration entrypoint — the
                  `saas-os-migrate upgrade` console script, or
                  `infra.db.migration_runner.run_core_migrations()`
                  called from this product's own bootstrap script —
                  never by pointing this product's own Alembic at
                  saas-os's filesystem path directly

  crm.*, marketing.*, accounting.*, agency.*, ...   ← owned by this product,
      one schema per module (docs/ARCHITECTURE.md §2.3)
      tracked by: alembic_version (this product's own, ordinary default)
      script directory: this product's own repository
      applied by: this product's own `alembic upgrade head`
```

- **Bootstrap order**: `saas-os`'s core migrations first (so `core.tenants`
  etc. exist before this product's own foreign keys into them), then this
  product's own migrations. A single bootstrap script runs both, in order —
  never left as two commands a deploy pipeline must remember separately
  (`saas-os`'s own investigation §16 flags exactly this as the one real
  operational risk in this model).
- **No autogenerate against a shared metadata object** — `saas-os`'s own
  migrations are hand-written for this exact reason (`infra/db` cannot
  import `core`). This product's own migrations may use autogenerate against
  its own models freely; the two histories never need to resolve against
  each other's metadata.
- **CI**: this product's own CI mirrors `saas-os`'s own `migrations` job — a
  disposable Postgres container, run `saas-os`'s core migrations, then this
  product's own, assert both succeed.

## What ships as a runtime dependency vs. what this product owns outright

| From `saas-os` (installed package, versioned, upgraded) | Owned by this product (copied once or built here, never versioned against `saas-os`) |
|---|---|
| `core.*`, `infra.*`, `control_plane.*`, `contracts.*` | Every `product/*` module |
| The reusable parts of `api.*` (`api.platform`, auth/tenant-resolution/health middleware) | This product's own `api/main.py` composition root, its own routes |
| `saas-os`'s own bundled core migrations | This product's own migrations |
| — | Dockerfile, docker-compose, CI workflow skeleton (copied once from the scaffold, then owned outright — `saas-os` ADR-0015 rule 9–10) |
| — | The entire frontend (`docs/ARCHITECTURE.md` §6 — no shared frontend package exists to depend on) |

## What this decision deliberately does not require building

Per `saas-os`'s own investigation §19 (its Explicit Non-Goals, inherited
here): no centralized AI Control Plane service, no private package index yet,
no generic cross-repo plugin framework, no shared multi-project database or
runtime. This product's own deployment is fully independent: its own
database, its own secrets, its own Docker Compose stack, its own release
schedule — SaaS-OS has no shared resource for this product's operational
choices to collide with.

## Open item this document does not resolve

Whether/when this product moves from a Git/VCS pin to a private package
index, and the exact scaffold-template contents (a plain `git clone`-and-rename
vs. a generator), are explicitly left open by `saas-os`'s own investigation
(§17 there) and are not re-decided here — revisit using this product's own
actual friction as evidence, once Phase 1 is underway, not on a schedule.
