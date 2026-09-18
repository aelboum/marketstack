"""Custom domain -> tenant resolution (docs/ROADMAP.md Phase 2.4;
docs/WHITE-LABEL.md section 3).

**Read this before touching anything here** -- docs/WHITE-LABEL.md
section 3 and docs/RESPONSIBILITY-MATRIX.md's "Custom-domain -> tenant
resolution" row both describe this as sitting "in front of
core.identity.get_tenant_context()", which "resolves tenant by
subdomain/header today." Direct inspection of the installed saas-os
package shows that premise is factually wrong: the real chokepoint,
`api.dependencies.get_tenant_context(tenant_id: uuid.UUID, actor_id =
Depends(get_current_actor))`, resolves `tenant_id` from an ordinary
FastAPI **path parameter**, validated against a real session membership
-- never from `Host`/subdomain. There is no subdomain- or header-based
tenant resolution anywhere in saas-os for this to sit in front of.

This module therefore builds only what is independently correct: the
domain -> tenant_id lookup itself (`resolve_tenant_for_domain`, fail-
closed) and a middleware that resolves it onto `request.state` for a
later phase to actually consume. It does NOT claim to feed
`get_tenant_context()` -- nothing does yet, since Phase 1 shipped zero
product routes for it to matter to. How a later phase's routes actually
consume `request.state.resolved_tenant_id` (a URL rewrite, a frontend
bootstrap endpoint that returns the resolved tenant_id for the frontend
to embed in its own subsequent path-parameterized calls, or something
else) is an explicit, unresolved product API-design decision -- not
invented here.
"""

from __future__ import annotations

import os
import uuid

from infra.db import session_scope
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from product.white_label.models import TenantDomain


def resolve_tenant_for_domain(domain: str) -> uuid.UUID | None:
    """Exact-match lookup of `domain` (a bare hostname, e.g.
    "app.theiragency.com" -- no scheme, no port) against
    `white_label.tenant_domains`. Returns `None` for an unmapped or
    malformed domain -- never a guess, never a default tenant. Read via
    a plain, untenanted `infra.db.session_scope()` (see
    `product/white_label/models.py::TenantDomain`'s own docstring for
    why this table is deliberately not RLS-scoped)."""
    if not domain or "/" in domain:
        return None
    with session_scope() as session:
        row = session.get(TenantDomain, domain)
        return row.tenant_id if row is not None else None


def _is_platform_domain(host: str, public_domain: str) -> bool:
    """`host` is either exactly the platform's own default domain, or a
    subdomain of it (e.g. "acme.<public_domain>") -- both are ordinary,
    non-custom traffic this middleware has no business touching."""
    return host == public_domain or host.endswith("." + public_domain)


class DomainResolutionMiddleware(BaseHTTPMiddleware):
    """Mounted ahead of routing in `product/api/main.py`. For a request
    to the platform's own default domain (or a subdomain of it,
    `PUBLIC_DOMAIN` env var), does nothing -- passthrough, unchanged
    behavior. For any other `Host`, treats it as a claimed custom
    domain: resolves it, and rejects with a non-enumerating 404
    (mirrors `core.identity`'s own documented pattern for an
    inaccessible tenant -- same shape, not a different error format) if
    unmapped. Never falls through to any tenant, including the
    platform's own, for an unmapped custom domain.

    `PUBLIC_DOMAIN` is read via plain `os.environ` -- ordinary runtime
    configuration, not a secret (mirrors saas-os's own
    `core/config/settings.py`, which reads its non-secret config the
    same way; `infra.secrets` is reserved for real credentials)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        host = request.headers.get("host", "").split(":", 1)[0]
        public_domain = os.environ.get("PUBLIC_DOMAIN", "")

        if not public_domain or _is_platform_domain(host, public_domain):
            return await call_next(request)

        tenant_id = resolve_tenant_for_domain(host)
        if tenant_id is None:
            return JSONResponse({"detail": "not found"}, status_code=404)

        request.state.resolved_tenant_id = tenant_id
        return await call_next(request)
