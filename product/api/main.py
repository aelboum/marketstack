"""This product's own application entrypoint (mirrors saas-os's
examples/reference-consumer/reference_consumer/app.py, ADR-0017 there).

Builds the FastAPI app by calling the installed saas-os package's
api.platform.build_platform_app() -- the reusable auth/tenant-resolution/
RBAC middleware chain plus /auth/login, /auth/callback, /auth/logout,
/auth/me, and a health endpoint -- and mounts this product's own routers
on top. It never imports api.main:app as its own application (the
ADR-0017-rejected pattern of a consumer treating SaaS-OS's own dev
entrypoint as its production app).

No product router is mounted yet (docs/ROADMAP.md Phase 1.3: "no product
routes yet") and no tenant-purge participant is registered yet -- there is
no product-owned tenant data anywhere until a later phase actually writes
some, so there is nothing yet for a purge participant to do.
"""

from __future__ import annotations

from api.platform import build_platform_app
from fastapi import FastAPI


def create_app() -> FastAPI:
    return build_platform_app(title="Product", version="0.0.1")


app = create_app()
