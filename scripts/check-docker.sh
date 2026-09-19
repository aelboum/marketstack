#!/usr/bin/env bash
# Docker build + runtime validation (docs/ROADMAP.md Phase 1.5). Kept OUT
# of check-all.sh -- slow (image builds take tens of seconds) and needs a
# running Docker daemon, unlike check-backend.sh/check-frontend.sh/
# check-security.sh. Run explicitly, or via the CI `docker` job. Scoped
# down from saas-os's own much larger scripts/check-docker.sh: this
# product has no `worker` service and no product API routes yet
# (docs/ROADMAP.md Phase 1 scope) -- there is nothing yet for a worker or
# route-level smoke test to exercise.
#
# Never publishes a host port outside an isolated Compose project (-p), so
# this cannot conflict with unrelated containers already running on this
# machine.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${SAAS_OS_PAT:?SAAS_OS_PAT must be set (a token with read access to the private aelboum/saas-os repo) -- the backend image clones it during pip install}"

BACKEND_TAG="product-backend:check"
FRONTEND_TAG="product-frontend:check"

echo "== docker build: backend =="
docker build --secret id=saas_os_pat,env=SAAS_OS_PAT -t "$BACKEND_TAG" .

echo "== docker build: frontend =="
docker build -t "$FRONTEND_TAG" ./frontend

# docker-compose.yml's services declare `env_file: .env` -- CI (and a
# fresh checkout) has none, and must not require a real one.
[ -f .env ] || cp .env.example .env

echo "== docker run: backend (against disposable db+redis, isolated compose project, no host ports) =="
COMPOSE_RUNTIME="docker compose -p product-check-runtime"
_runtime_cleanup() {
    $COMPOSE_RUNTIME down -v --remove-orphans >/dev/null 2>&1 || true
}
trap _runtime_cleanup EXIT

$COMPOSE_RUNTIME up -d db redis
$COMPOSE_RUNTIME build backend

# The freshly created `db` container has no schema -- the same two-step
# bootstrap (saas-os core migrations, then this product's own) that
# scripts/check-migrations.sh/check-integration.sh run against their own
# disposable postgres must also run here, or every DB-backed route
# (including /readyz, via product.white_label's own domain-resolution
# middleware) 500s on startup. scripts/ is intentionally excluded from
# the backend image itself (.dockerignore) -- not runtime code -- so it
# is bind-mounted into a one-off container from the already-built image
# instead of baking it in.
echo "-- migration bootstrap (against the runtime db, before the app starts) --"
$COMPOSE_RUNTIME run --rm -v "$(pwd -W 2>/dev/null || pwd)/scripts:/app/scripts:ro" backend python scripts/bootstrap-db.py

$COMPOSE_RUNTIME up -d backend
BACKEND_CID=$($COMPOSE_RUNTIME ps -q backend)

echo "-- waiting for the backend container to report healthy (Dockerfile HEALTHCHECK) --"
HEALTHY=""
for _ in $(seq 1 30); do
    STATUS=$(docker inspect -f '{{.State.Health.Status}}' "$BACKEND_CID" 2>/dev/null || echo "")
    if [ "$STATUS" = "healthy" ]; then
        HEALTHY=1
        break
    fi
    sleep 2
done
if [ -z "$HEALTHY" ]; then
    echo "FAIL: backend did not become healthy"
    docker logs "$BACKEND_CID" || true
    exit 1
fi

# Dial `localhost`, not the loopback IP literal `127.0.0.1` -- see the
# Dockerfile HEALTHCHECK's own comment: product.white_label's domain-
# resolution middleware only passes through requests whose Host matches
# PUBLIC_DOMAIN (`localhost`, per .env.example); "127.0.0.1" is a
# different string and gets treated as an unmapped custom domain (404).
echo "-- liveness (200) --"
docker exec "$BACKEND_CID" python -c \
    "import urllib.request as u; r = u.urlopen('http://localhost:8000/healthz', timeout=3); assert r.status == 200, r.status"

echo "-- readiness (200, db+redis reachable) --"
docker exec "$BACKEND_CID" python -c \
    "import urllib.request as u; r = u.urlopen('http://localhost:8000/readyz', timeout=3); assert r.status == 200, r.status"

_runtime_cleanup
trap - EXIT

echo "== docker run: frontend (starts, checked, stopped -- no host port published) =="
CID=$(docker run -d "$FRONTEND_TAG")
sleep 5
RUNNING=$(docker ps --filter "id=$CID" --filter "status=running" --format '{{.ID}}')
if [ -z "$RUNNING" ]; then
    echo "FAIL: frontend container is not running after startup"
    docker logs "$CID" || true
    docker rm -f "$CID" >/dev/null 2>&1 || true
    exit 1
fi
LOGS=$(docker logs "$CID" 2>&1)
if [[ "$LOGS" != *"Ready"* ]]; then
    echo "FAIL: frontend did not report Ready"
    echo "$LOGS"
    docker rm -f "$CID" >/dev/null 2>&1 || true
    exit 1
fi
docker rm -f "$CID" >/dev/null

echo "== docker compose config (isolated project name, no containers started) =="
docker compose -p product-check config >/dev/null

echo "All Docker checks passed."
