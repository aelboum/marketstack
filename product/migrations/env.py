"""This product's own Alembic environment (docs/REPOSITORY-STRATEGY.md,
"two independent Alembic environments, one database") -- independent of
SaaS-OS's own (the installed saas-os package's infra/db/migrations/env.py):
its own script directory (this directory), its own default-named
`alembic_version` table (no override, unlike SaaS-OS's own
`alembic_version_saas_os`), invoked separately, always after SaaS-OS's own
migrations (see scripts/bootstrap-db.py).

Mirrors saas-os's examples/reference-consumer/reference_consumer/migrations
/env.py exactly: reuses infra.db.config.get_migrations_database_config()
from the installed saas-os package for the connection -- both environments
target the same one physical database per project, so reusing SaaS-OS's
own config/secrets plumbing here is the correct, intended pattern, not a
boundary violation.

target_metadata is None: no product model exists yet in Phase 1
(docs/ROADMAP.md 1.2, "no product tables yet") -- there is nothing to
autogenerate against. A later phase's own migrations may use autogenerate
freely once product/<module> models exist.
"""

from logging.config import fileConfig

from alembic import context
from infra.db.config import get_migrations_database_config
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = None


def _get_url() -> str:
    return get_migrations_database_config().url


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
