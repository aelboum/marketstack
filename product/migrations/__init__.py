"""This product's own, independent Alembic environment -- separate from
saas-os's own (applied via infra.db.migration_runner.run_core_migrations(),
never by pointing this environment at saas-os's package internals). See
docs/REPOSITORY-STRATEGY.md, "Database migrations: two independent Alembic
environments, one database"."""
