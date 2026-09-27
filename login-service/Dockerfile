# Login Service image (docs/ADR/0017) -- a separate, product-owned
# process/container. Deliberately does NOT share a base image, dependency
# set, or build context with the main product `Dockerfile`: it never
# installs `saas-os`, never copies `product/`, and has no access to
# anything under the repo root except this directory (build context is
# `./login-service`, not `.`).

FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY entrypoint.sh ./entrypoint.sh

RUN pip install --no-cache-dir -e . \
    && chmod +x ./entrypoint.sh

RUN groupadd --system app && useradd --system --gid app --home /app app \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://localhost:8000/login-svc/healthz', timeout=3)"]

ENTRYPOINT ["./entrypoint.sh"]
