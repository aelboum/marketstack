"""Two-step database bootstrap (docs/REPOSITORY-STRATEGY.md, "Database
migrations: two independent Alembic environments, one database"; also
docs/ROADMAP.md Phase 1.2).

Order matters: SaaS-OS's own core migrations must run first (so
core.tenants etc. exist before this product's own foreign keys into them),
then this product's own migrations. Mirrors the exact working sequence
saas-os's own tests/test_reference_consumer_integration.py proves against a
real installed wheel + disposable Postgres.

No product migration exists yet in Phase 1 (docs/ROADMAP.md 1.2: "no
product tables yet") -- step 2 currently upgrades an empty history, which
is a correct no-op, not a placeholder.

Reads DATABASE_URL / MIGRATIONS_DATABASE_URL from the process environment
(via the installed saas-os package's infra.db.config), the same way every
other saas-os deployment does -- no separate .env-loading mechanism is
introduced here since saas-os itself does not use one (docker-compose's
own `env_file: .env`, or real environment variables in CI, are the only
two ways this project's env vars are ever supplied).

Usage:
    python scripts/bootstrap-db.py
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from infra.db.migration_runner import run_core_migrations

_PRODUCT_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "product" / "migrations"


def bootstrap() -> None:
    # 1. SaaS-OS's own migrations first.
    run_core_migrations()

    # 2. This product's own, separate migrations.
    project_cfg = Config()
    project_cfg.set_main_option("script_location", str(_PRODUCT_MIGRATIONS_DIR))
    command.upgrade(project_cfg, "head")


if __name__ == "__main__":
    bootstrap()
    print(
        "Database bootstrap complete: saas-os core migrations + this "
        "product's own migrations are both at head."
    )
