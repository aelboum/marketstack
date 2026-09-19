#!/usr/bin/env bash
# Integration test gate (docs/ROADMAP.md Phase 2, extended by Phase 3):
# runs every test marked `integration` (tests/foundation/, tests/white_label/,
# and, since Phase 3, tests/agency/ -- agency/client provisioning,
# cross-agency/cross-client isolation, delegation/deny, support access,
# and HTTP-layer routes) against real, disposable PostgreSQL and Redis
# instances -- never the developer's own persistent `db`/`redis`
# containers, never production. Phase 3 adds no new migration (see
# docs/ADR/0003-agency-client-tenancy-mapping.md), so this script's own
# bootstrap step below is unchanged.
#
# Shares scripts/check-migrations.sh's exact disposable-Postgres startup
# pattern (including its `pwd -W` Windows volume-mount fix) so there is
# one proven way to stand up a throwaway database in this repository, not
# two. Adds a disposable Redis alongside it for the durable-event test.
set -euo pipefail
cd "$(dirname "$0")/.."

PG_CONTAINER_NAME="product-integration-check-pg-$$"
REDIS_CONTAINER_NAME="product-integration-check-redis-$$"
PG_HOST_PORT="${INTEGRATION_CHECK_PG_PORT:-55434}"
REDIS_HOST_PORT="${INTEGRATION_CHECK_REDIS_PORT:-63790}"

cleanup() {
  docker rm -f "$PG_CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm -f "$REDIS_CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== starting disposable postgres:16-alpine =="
docker run --rm -d --name "$PG_CONTAINER_NAME" \
  -e POSTGRES_USER=product \
  -e POSTGRES_PASSWORD=ci-only-placeholder \
  -e POSTGRES_DB=product \
  -e APP_DB_USER=product_app \
  -e APP_DB_PASSWORD=ci-only-app-placeholder \
  -p "${PG_HOST_PORT}:5432" \
  -v "$(pwd -W 2>/dev/null || pwd)/deploy/db-init:/docker-entrypoint-initdb.d" \
  postgres:16-alpine >/dev/null

echo "== starting disposable redis:7-alpine =="
docker run --rm -d --name "$REDIS_CONTAINER_NAME" \
  -p "${REDIS_HOST_PORT}:6379" \
  redis:7-alpine >/dev/null

echo "== waiting for postgres to accept connections (init scripts included) =="
for _ in $(seq 1 60); do
  ready_count=$(docker logs "$PG_CONTAINER_NAME" 2>&1 | grep -c "database system is ready to accept connections" || true)
  if [ "$ready_count" -ge 2 ]; then
    break
  fi
  sleep 1
done
# See scripts/check-migrations.sh's identical check for why this reuses
# $ready_count instead of re-running `grep -q` under `set -o pipefail`
# (SIGPIPE from `-q`'s early exit was being misreported as this check's
# own failure).
[ "$ready_count" -ge 2 ] || {
  echo "postgres never became ready" >&2
  docker logs "$PG_CONTAINER_NAME" >&2
  exit 1
}

echo "== waiting for redis to accept connections =="
for _ in $(seq 1 30); do
  if docker exec "$REDIS_CONTAINER_NAME" redis-cli ping 2>/dev/null | grep -q PONG; then
    break
  fi
  sleep 1
done
docker exec "$REDIS_CONTAINER_NAME" redis-cli ping 2>/dev/null | grep -q PONG || {
  echo "redis never became ready" >&2
  exit 1
}

export ENVIRONMENT=test
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT}/0"
export APP_DB_USER=product_app
export MIGRATIONS_DATABASE_URL="postgresql+psycopg://product:ci-only-placeholder@localhost:${PG_HOST_PORT}/product"  # pragma: allowlist secret
export DATABASE_URL="postgresql+psycopg://product_app:ci-only-app-placeholder@localhost:${PG_HOST_PORT}/product"  # pragma: allowlist secret

echo "== bootstrap: saas-os core migrations, then this product's own =="
python scripts/bootstrap-db.py

echo "== running the integration suite (pytest -m integration) =="
pytest -m integration -v

echo "== integration gate: PASS =="
