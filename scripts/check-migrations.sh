#!/usr/bin/env bash
# Migration bootstrap gate (docs/ROADMAP.md Phase 1.2/1.5, extended by
# Phase 2.1/2.3/2.4's own migrations): proves a clean,
# disposable PostgreSQL database can be taken from nothing to both
# migration histories at head via the real two-step path
# (scripts/bootstrap-db.py) -- never the developer's own persistent `db`
# container, never production.
#
# Starts its own throwaway postgres:16-alpine container (mirrors saas-os's
# own CI `migrations` job precedent), runs the two-role init script
# (deploy/db-init/01-create-app-role.sh) via the official image's
# /docker-entrypoint-initdb.d hook, runs scripts/bootstrap-db.py against
# it, asserts the expected schemas/version tables exist, then always tears
# the container down (trap, so a failed assertion still cleans up).
set -euo pipefail
cd "$(dirname "$0")/.."

CONTAINER_NAME="product-migration-check-$$"
HOST_PORT="${MIGRATION_CHECK_PG_PORT:-55432}"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== starting disposable postgres:16-alpine =="
docker run --rm -d --name "$CONTAINER_NAME" \
  -e POSTGRES_USER=product \
  -e POSTGRES_PASSWORD=ci-only-placeholder \
  -e POSTGRES_DB=product \
  -e APP_DB_USER=product_app \
  -e APP_DB_PASSWORD=ci-only-app-placeholder \
  -p "${HOST_PORT}:5432" \
  -v "$(pwd -W 2>/dev/null || pwd)/deploy/db-init:/docker-entrypoint-initdb.d" \
  postgres:16-alpine >/dev/null
# `pwd -W` (Git Bash only) prints the native Windows drive-letter path --
# required here because Docker Desktop's volume-mount arg parsing on
# Windows does not reliably translate a plain MSYS POSIX path
# (`/c/Users/...`) combined with a `:`-separated container path; a POSIX
# path silently produced an EMPTY mount once during development of this
# script (the init script never ran, role creation silently skipped, no
# error at the `docker run` step itself). `|| pwd` keeps this portable to
# a non-Git-Bash `bash` (Linux CI) where `-W` does not exist.

echo "== waiting for postgres to accept connections (init scripts included) =="
# The official postgres image starts twice on a brand-new volume: once on
# a Unix socket only, to run /docker-entrypoint-initdb.d/ (our two-role
# init script), then a second time listening on TCP for real traffic.
# `pg_isready` against the container's own socket can observe the FIRST
# ("accepting connections") startup, before the init script has actually
# run -- the exact race that silently skipped role creation once during
# development of this script. Waiting for the "ready to accept
# connections" log line to appear twice is what actually proves the init
# scripts ran and the final, externally-reachable server is up.
for _ in $(seq 1 60); do
  ready_count=$(docker logs "$CONTAINER_NAME" 2>&1 | grep -c "database system is ready to accept connections" || true)
  if [ "$ready_count" -ge 2 ]; then
    break
  fi
  sleep 1
done
docker logs "$CONTAINER_NAME" 2>&1 | grep -q "database system is ready to accept connections" || {
  echo "postgres never became ready" >&2
  docker logs "$CONTAINER_NAME" >&2
  exit 1
}

export ENVIRONMENT=test
export REDIS_URL="redis://127.0.0.1:6379/0"
export APP_DB_USER=product_app
export MIGRATIONS_DATABASE_URL="postgresql+psycopg://product:ci-only-placeholder@localhost:${HOST_PORT}/product"  # pragma: allowlist secret
export DATABASE_URL="postgresql+psycopg://product_app:ci-only-app-placeholder@localhost:${HOST_PORT}/product"  # pragma: allowlist secret

echo "== bootstrap: saas-os core migrations, then this product's own =="
python scripts/bootstrap-db.py

echo "== asserting expected schemas and version tables exist =="
python - <<'PYEOF'
import os

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["MIGRATIONS_DATABASE_URL"])
with engine.connect() as conn:
    saas_os_version = conn.execute(
        text("SELECT version_num FROM alembic_version_saas_os")
    ).scalar_one()
    assert saas_os_version, "saas-os's own alembic_version_saas_os is empty"

    # This product's own alembic_version table -- since Phase 2.1/2.3/2.4
    # (docs/ROADMAP.md), it is no longer empty: three real migrations now
    # exist (foundation.tenant_settings, white_label.tenant_branding,
    # white_label.tenant_domains), head is 0003_white_label_tenant_domains.
    product_version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert product_version == "0003_white_label_tenant_domains", (
        f"expected product migrations at head 0003_white_label_tenant_domains, got {product_version!r}"
    )

    schema_rows = conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname = ANY(:names)"),
        {"names": ["core", "control_plane", "self_learning", "foundation", "white_label"]},
    ).all()
schemas_present = {row[0] for row in schema_rows}
expected = {"core", "control_plane", "self_learning", "foundation", "white_label"}
assert schemas_present == expected, f"expected {expected}, got {schemas_present}"

print(
    f"OK: saas-os core migrations at {saas_os_version}; "
    f"product migrations at {product_version}; schemas present: {sorted(schemas_present)}"
)
PYEOF

echo "== migration bootstrap gate: PASS =="
