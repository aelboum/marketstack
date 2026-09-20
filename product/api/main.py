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

Phase 5 adds `product/conversations/routes.py` (`/v1/conversations`),
three more tenant-owned tables (`conversations.*`), one consolidated
purge participant, and a second `agency.role_provisioned` subscriber
(`product/conversations/event_handlers.py`) -- the identical pattern
Phase 4 established for `product.crm`, repeated here since
`product.conversations` and `product.agency`/`product.crm` must never
import each other directly either.

Phase 6 adds `product/marketing/routes.py` (`/v1/marketing`), three more
tenant-owned tables (`marketing.*`), one consolidated purge participant,
and a third `agency.role_provisioned` subscriber
(`product/marketing/event_handlers.py`). `product.marketing` is the one
module permitted to import a sibling module's service functions
(`product.crm.contacts`, for audience segmentation --
`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`) -- that
exception is enforced by import-linter, not by anything special about how
it is mounted here, so this file's own wiring is otherwise identical to
Phase 4/5's.

Phase 7.1-7.2 adds `product/appointments/routes.py` (`/v1/appointments`),
five more tables (`appointments.*` -- three ordinary RLS-scoped,
`booking_links`/`appointment_manage_tokens` deliberately not, mirroring
`marketing.forms`'s own precedent), two purge participants (mirroring
`product/marketing/purge.py`'s own scoped/unscoped split, see
`product/appointments/purge.py`'s own docstring), and a fourth
`agency.role_provisioned` subscriber
(`product/appointments/event_handlers.py`). `product.appointments` is now
the second module permitted to import `product.crm.contacts` directly
(`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`'s broadened
scope) -- it reuses
`create_or_update_contact_from_trusted_source()` for public booking
rather than building a second anonymous-contact-creation path.

UI-1 (docs/ROADMAP.md UI Track) adds `CORSMiddleware`, narrowly scoped to
this product's own frontend origin(s) with credentials enabled -- the
frontend's browser-side session (`/auth/me`, `/v1/*`) is cookie-based and
calls this backend cross-origin in local dev (frontend :3000, backend
:8000, no reverse proxy -- docker-compose.yml's own comment). Without
this, the browser rejects every credentialed cross-origin response
outright regardless of what the backend actually returns; this was a
real, previously-undocumented gap (see the frontend's own
`lib/api/client.ts` docstring before this change). `build_platform_app()`
deliberately mounts no CORS policy of its own (ADR-0017: business
middleware is a consumer concern, not a reusable-platform one), so this
is this product's -- not `saas-os`'s -- to own. `_frontend_origins()`
reads `FRONTEND_ORIGINS` via plain `os.environ`, mirroring
`product/white_label/domains.py`'s own `PUBLIC_DOMAIN` precedent
(ordinary runtime configuration, not a secret); unset/empty means no
origin is allowed -- fail-closed, not "allow everything," matching this
product's existing `ENVIRONMENT`-must-be-explicit posture
(`infra.secrets`).
"""

from __future__ import annotations

import os

from api.platform import build_platform_app
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from product.agency.routes import router as agency_router
from product.appointments import event_handlers as _appointments_event_handlers  # noqa: F401
from product.appointments.purge import register as register_appointments_purge_participant
from product.appointments.routes import router as appointments_router
from product.conversations import event_handlers as _conversations_event_handlers  # noqa: F401
from product.conversations.purge import register as register_conversations_purge_participant
from product.conversations.routes import router as conversations_router
from product.crm import event_handlers as _crm_event_handlers  # noqa: F401 -- import for its

# module-level subscribe() side effect (see product/crm/event_handlers.py's own docstring),
# registered before create_app() runs any request-serving code. Pure in-process registration,
# touches no database. The same applies to
# product.conversations.event_handlers above.
from product.crm.purge import register as register_crm_purge_participant
from product.crm.routes import router as crm_router
from product.foundation.purge import register as register_foundation_purge_participants
from product.marketing import event_handlers as _marketing_event_handlers  # noqa: F401
from product.marketing.purge import register as register_marketing_purge_participant
from product.marketing.routes import router as marketing_router
from product.white_label.domains import DomainResolutionMiddleware
from product.white_label.purge import register as register_white_label_purge_participants


def _frontend_origins() -> list[str]:
    """Browser origins allowed to make credentialed cross-origin requests
    against this API (e.g. `http://localhost:3000` in local dev), from
    the comma-separated `FRONTEND_ORIGINS` env var. Empty/unset returns
    `[]` -- CORSMiddleware then allows no origin at all, never `*`
    (`docs/ROADMAP.md` UI Track's ARCHITECTURE.md §6.1: no permissive
    production default)."""
    raw = os.environ.get("FRONTEND_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = build_platform_app(title="Product", version="0.0.1")
    app.add_middleware(DomainResolutionMiddleware)
    # Added last (see module docstring) so it wraps every other
    # middleware/route -- Starlette's `add_middleware()` makes the most
    # recently added middleware the outermost layer
    # (`starlette.applications.Starlette.add_middleware` inserts at index
    # 0; `build_middleware_stack()` wraps in reverse). CORS must be
    # outermost: it needs to answer an OPTIONS preflight and annotate
    # every response -- including a 404 from `DomainResolutionMiddleware`
    # -- before/regardless of what runs underneath it.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_frontend_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(agency_router)
    app.include_router(crm_router)
    app.include_router(conversations_router)
    app.include_router(marketing_router)
    app.include_router(appointments_router)
    register_foundation_purge_participants()
    register_white_label_purge_participants()
    register_crm_purge_participant()
    register_conversations_purge_participant()
    register_marketing_purge_participant()
    register_appointments_purge_participant()
    return app


app = create_app()
