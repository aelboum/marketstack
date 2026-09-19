# Backend development image (docs/ROADMAP.md Phase 1.1/1.5). Mirrors
# saas-os's own root Dockerfile shape, adapted: this product installs
# saas-os itself as a pinned Git dependency (pyproject.toml), so the build
# image needs `git` on PATH for pip to clone it -- saas-os's own Dockerfile
# has no VCS dependency and does not need this.
#
# Not a production-hardened image (no multi-stage slimming) -- that is
# later deployment work, not Phase 1.
#
# No secret is ever baked into this image: all secrets are injected at
# container runtime via environment variables supplied by
# docker-compose.yml's `env_file: .env` (never committed) or the host at
# deploy time. The build context excludes .env/.venv/.git/node_modules/etc
# via .dockerignore.

FROM python:3.13-slim

WORKDIR /app

# Only `git` is installed (needed for pip to clone the pinned saas-os
# commit) -- unlike saas-os's own Dockerfile, this image does not also
# install `build-essential`. saas-os's own comment on that line says it
# is needed "only if a wheel isn't available for the target platform";
# verified empirically here that `pip install -e .` completes cleanly on
# python:3.13-slim/linux-amd64 without a C compiler present (psycopg is
# installed via its `[binary]` extra, which ships a prebuilt wheel).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY product ./product

# Only the declared runtime dependencies ([project] dependencies, which
# pulls in the pinned saas-os commit) are installed -- the [dev]/[security]
# extras (ruff/pyright/pytest/import-linter/pip-audit/detect-secrets) are
# intentionally not installed into this image. uvicorn is not a second,
# separate direct dependency here -- it resolves transitively via the
# saas-os package's own `uvicorn>=0.30` runtime dependency.
#
# saas-os is a private repository, so pip's internal git clone needs a
# credential. Supplied as a BuildKit secret (--secret id=saas_os_pat, see
# scripts/check-docker.sh), never as an ARG/ENV: those are cached and
# readable in image history, a mounted secret is not. The credential
# helper is unset again inside this same RUN so no trace of it survives
# into the layer's committed .gitconfig.
RUN --mount=type=secret,id=saas_os_pat \
    git config --global credential.helper '!f() { echo "username=x-access-token"; echo "password=$(cat /run/secrets/saas_os_pat)"; }; f' \
    && pip install --no-cache-dir -e . \
    && git config --global --unset credential.helper

# Run as a non-root user (least privilege, applied to the container
# itself). Ownership is granted after all root-only build steps
# (apt-get, pip install) are done.
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# In-container healthcheck. python:3.13-slim has neither curl nor wget --
# python itself is already present, so the stdlib's own urllib.request is
# used instead of installing a package solely for this check. Probes
# `/readyz` (readiness -- a container whose process is alive but whose
# required dependencies, e.g. PostgreSQL/Redis, are unreachable should be
# reported unhealthy), not `/healthz` (liveness only).
#
# Must dial `localhost`, never the loopback IP literal `127.0.0.1`:
# product.white_label.domains.DomainResolutionMiddleware treats any Host
# header other than PUBLIC_DOMAIN (or a subdomain of it) as a claimed
# custom domain and 404s it once white_label.tenant_domains exists but
# has no matching row -- ".env.example"/deploy configuration sets
# PUBLIC_DOMAIN=localhost, which "127.0.0.1" (a different string) never
# matches.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://localhost:8000/readyz', timeout=3)"]

# Phase 1 has no equivalent of saas-os's own configurable api/server.py
# (host/port sourced from core.config.Settings) -- this product has no
# need for that yet, so uvicorn is invoked directly against the fixed
# 0.0.0.0:8000 this image already EXPOSEs. Revisit if a later phase needs
# runtime-configurable host/port.
CMD ["uvicorn", "product.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
