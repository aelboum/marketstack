"""This product's own application entrypoint (mirrors saas-os's
examples/reference-consumer/reference_consumer/app.py, ADR-0017 there).

Builds the FastAPI app by calling the installed saas-os package's
api.platform.build_platform_app() -- the reusable auth/tenant-resolution/
RBAC middleware chain plus /auth/login, /auth/callback, /auth/logout,
/auth/me, and a health endpoint -- and mounts this product's own
middleware/purge participants on top. It never imports api.main:app as
its own application (the ADR-0017-rejected pattern of a consumer
treating SaaS-OS's own dev entrypoint as its production app).

Two things Phase 2 added, once it shipped this product's first real
tenant-owned tables:

- `DomainResolutionMiddleware` (docs/ROADMAP.md Phase 2.4) -- see
  product/white_label/domains.py's own docstring for exactly what it
  does and does not do yet.
- Tenant-purge participant registration (RA-12-2 discipline, mirrored
  from the reference consumer) for every table this product owns --
  `foundation.tenant_settings`, `white_label.tenant_branding`,
  `white_label.tenant_domains`.

Phase 3 (docs/ROADMAP.md) adds this product's first product router --
`product/agency/routes.py`, mounted at `/v1/agency` -- and no new
tenant-owned table (docs/ADR/0003-agency-client-tenancy-mapping.md), so
no new purge participant either.

Phase 4 adds `product/crm/routes.py` (`/v1/crm`), this product's first
own tenant-owned tables (`crm.*`, seven of them, one consolidated purge
participant -- see `product/crm/purge.py`'s own docstring for why they
are not seven separate participants). CRM permissions are NOT eagerly
registered here -- `core.rbac.register_permission()` needs a real
database connection, and `create_app()` (and this module's own
`app = create_app()` at import time, below) must stay callable with no
database configured, exactly as it always has (`tests/test_app_smoke.py`
imports this module with no `DATABASE_URL` set). Every CRM permission is
registered lazily, on first actual grant, by `product/crm/permissions.py
::grant_to_role()` -- the same idempotent-registration discipline
`product/agency/roles.py` already uses.
"""

from __future__ import annotations

from api.platform import build_platform_app
from fastapi import FastAPI

from product.agency.routes import router as agency_router
from product.crm import event_handlers as _crm_event_handlers  # noqa: F401 -- import for its

# module-level subscribe() side effect (see product/crm/event_handlers.py's own docstring),
# registered before create_app() runs any request-serving code. Pure in-process registration,
# touches no database.
from product.crm.purge import register as register_crm_purge_participant
from product.crm.routes import router as crm_router
from product.foundation.purge import register as register_foundation_purge_participants
from product.white_label.domains import DomainResolutionMiddleware
from product.white_label.purge import register as register_white_label_purge_participants


def create_app() -> FastAPI:
    app = build_platform_app(title="Product", version="0.0.1")
    app.add_middleware(DomainResolutionMiddleware)
    app.include_router(agency_router)
    app.include_router(crm_router)
    register_foundation_purge_participants()
    register_white_label_purge_participants()
    register_crm_purge_participant()
    return app


app = create_app()
