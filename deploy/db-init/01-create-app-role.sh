#!/usr/bin/env bash
# Copied once from saas-os's own infra/db/init/01-create-app-role.sh
# (2026-09-18) -- generic Postgres role-creation shell that only ever reads
# environment variables, no saas-os-specific logic (docs/REPOSITORY-
# STRATEGY.md's own stated precedent: "Dockerfile, docker-compose, CI
# workflow skeleton -- copied once from the scaffold, then owned outright").
# Not core Python logic, not business logic -- deliberate operational-
# config reuse, not a boundary violation.
#
# Creates the restricted PostgreSQL application runtime role this
# product's own DATABASE_URL points at (docs/REPOSITORY-STRATEGY.md,
# "two independent Alembic environments, one database"). Row-Level
# Security (where used) is never applied to a superuser or a BYPASSRLS
# role, with no override, so the application must run as neither.
#
# Runs automatically, once, via the official postgres image's own
# /docker-entrypoint-initdb.d mechanism -- only on first boot of a brand
# new (empty) data volume. Idempotent (IF NOT EXISTS) as defense in depth
# against a manual re-run.
#
# $POSTGRES_USER / $POSTGRES_DB are already in this container's
# environment (the official image's own bootstrap variables).
# $APP_DB_USER / $APP_DB_PASSWORD come from docker-compose's environment,
# themselves sourced from .env (gitignored, never committed). This script
# only ever sees them as ephemeral container environment variables -- it
# does not persist, print, or log the password anywhere.

set -euo pipefail

: "${APP_DB_USER:?APP_DB_USER must be set}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$APP_DB_USER') THEN
            CREATE ROLE "$APP_DB_USER" LOGIN PASSWORD '$APP_DB_PASSWORD'
                NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
        END IF;
    END
    \$\$;

    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO "$APP_DB_USER";
EOSQL
