"""This product's own application entrypoint (mirrors saas-os's
examples/reference-consumer/reference_consumer/app.py, ADR-0017 there).

Builds the FastAPI app by calling the installed saas-os package's
api.platform.build_platform_app() -- the reusable auth/tenant-resolution/
RBAC middleware chain plus /auth/login, /auth/callback, /auth/logout,
/auth/me, and a health endpoint -- and mounts this product's own
middleware/purge participants on top. It never imports api.main:app as
its own application (the ADR-0017-rejected pattern of a consumer
treating SaaS-OS's own dev entrypoint as its production app).

No product *router* is mounted yet (docs/ROADMAP.md Phase 2 ships no
product API endpoints -- Phase 4/CRM is the first). Two things this
phase does add, now that Phase 2.1/2.3 ship this product's first real
tenant-owned tables:

- `DomainResolutionMiddleware` (docs/ROADMAP.md Phase 2.4) -- see
  product/white_label/domains.py's own docstring for exactly what it
  does and does not do yet.
- Tenant-purge participant registration (RA-12-2 discipline, mirrored
  from the reference consumer) for every table this product now owns --
  `foundation.tenant_settings`, `white_label.tenant_branding`,
  `white_label.tenant_domains`. Deferred no longer, unlike Phase 1 (whose
  own version of this docstring correctly said there was nothing yet to
  purge).
"""

from __future__ import annotations

from api.platform import build_platform_app
from fastapi import FastAPI

from product.foundation.purge import register as register_foundation_purge_participants
from product.white_label.domains import DomainResolutionMiddleware
from product.white_label.purge import register as register_white_label_purge_participants


def create_app() -> FastAPI:
    app = build_platform_app(title="Product", version="0.0.1")
    app.add_middleware(DomainResolutionMiddleware)
    register_foundation_purge_participants()
    register_white_label_purge_participants()
    return app


app = create_app()
