"""The Templates/Snapshots API (docs/ROADMAP.md Phase 14), mounted under
`/v1/templates` in `product/api/main.py` -- **not yet actually mounted**;
see this module's own package docstring (`product/templates/__init__.py`)
and this phase's implementation/audit report for why `product/api/main.py`
is out of this phase's scope.

**Ingress dependency choice** -- identical reasoning to
`product/reputation/routes.py`'s own module docstring: every route uses
`api.dependencies.get_current_actor`, never `get_tenant_context()`/
`require_permission()`. Every `product/templates/*.py` service function
performs its own `core.rbac.can()` check via `product.templates
.permissions.require()` before touching any `templates.*` row or calling
`core.crm`.

**Non-enumeration**: `TemplatesAccessDeniedError`/`SnapshotNotFoundError`,
and `product.crm`'s own `CrmAccessDeniedError`/`CrmReferenceNotFoundError`
propagating from an `apply` call's own CRM-side authorization/lookup, all
map to the identical `404` shape `api.errors.not_found()` uses elsewhere.
`TemplatesValidationError` maps to `400`. `SnapshotApplyError`
(`docs/ADR/0013-...`'s own disclosed residual-failure case -- a genuine
infrastructure fault after all validation already passed) is
deliberately NOT caught here -- it propagates as an ordinary unhandled
exception (`500`), the correct shape for a server-side fault that is not
the caller's mistake and not a cross-tenant information question.
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from product.crm.errors import CrmAccessDeniedError, CrmReferenceNotFoundError
from product.templates.errors import (
    SnapshotNotFoundError,
    TemplatesAccessDeniedError,
    TemplatesValidationError,
)
from product.templates.models import MAX_DESCRIPTION_LENGTH, MAX_NAME_LENGTH
from product.templates.snapshots import (
    SnapshotView,
    apply_snapshot,
    create_snapshot,
    get_snapshot,
    list_snapshots,
)

router = APIRouter(prefix="/v1/templates", tags=["templates"])

_VALIDATION_ERRORS: tuple[type[Exception], ...] = (TemplatesValidationError,)
_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    TemplatesAccessDeniedError,
    SnapshotNotFoundError,
    CrmAccessDeniedError,
    CrmReferenceNotFoundError,
)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


# --- Request bodies ----------------------------------------------------------


class CreateSnapshotRequest(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    domains: list[str] = Field(min_length=1)


class ApplySnapshotRequest(BaseModel):
    target_tenant_id: uuid.UUID


# --- Serialization -------------------------------------------------------------


def _snapshot_dict(view: SnapshotView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "description": view.description,
        "schema_version": view.schema_version,
        "included_domains": view.included_domains,
        "payload": view.payload,
        "created_by_user_id": str(view.created_by_user_id),
        "created_at": view.created_at.isoformat(),
    }


# --- Snapshots -----------------------------------------------------------------


@router.post("/tenants/{tenant_id}/snapshots", status_code=status.HTTP_201_CREATED)
def create_snapshot_route(
    tenant_id: uuid.UUID,
    body: CreateSnapshotRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _snapshot_dict(
        _call(
            create_snapshot,
            actor_id,
            tenant_id,
            name=body.name,
            description=body.description,
            domains=body.domains,
        )
    )


@router.get("/tenants/{tenant_id}/snapshots")
def list_snapshots_route(
    tenant_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _snapshot_dict(v)
        for v in _call(list_snapshots, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/snapshots/{snapshot_id}")
def get_snapshot_route(
    tenant_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _snapshot_dict(_call(get_snapshot, actor_id, tenant_id, snapshot_id))


@router.post("/tenants/{tenant_id}/snapshots/{snapshot_id}/apply")
def apply_snapshot_route(
    tenant_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    body: ApplySnapshotRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    result = _call(apply_snapshot, actor_id, tenant_id, snapshot_id, body.target_tenant_id)
    return {
        "snapshot_id": str(result.snapshot_id),
        "target_tenant_id": str(result.target_tenant_id),
        "created_counts": result.created_counts,
    }


__all__ = ["router"]
