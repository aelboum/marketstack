"""The Telephony API (docs/ROADMAP.md Phase 8), mounted under
`/v1/telephony` in `product/api/main.py`.

**Read-only, deliberately** -- see `product/telephony/__init__.py`'s own
module docstring for the full reasoning: every write path
(`provision_phone_number()`, `initiate_outbound_call()`,
`receive_inbound_call_event()`) requires an explicit `TelephonyProvider`
with no real default, so no route could function against it in production
regardless. These two list/get routes are real, live, tenant-scoped,
RBAC-gated reads over whatever `telephony.*` data exists, however it got
there (a future real-vendor integration, admin tooling, or a test).

**Ingress dependency choice** -- identical reasoning to
`product/appointments/routes.py`'s own module docstring
(`docs/ADR/0002-agency-cross-tenant-route-authorization.md`'s Phase 4
addendum): `api.dependencies.get_current_actor`, never
`get_tenant_context()`/`require_permission()`. Every
`product/telephony/*.py` service function performs its own
`core.rbac.can()` check via `product.telephony.permissions.require()`
before touching any `telephony.*` row.

**Non-enumeration**: `TelephonyAccessDeniedError`/
`TelephonyReferenceNotFoundError` map to the identical `404` shape
`api.errors.not_found()` uses elsewhere in this platform.
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found
from fastapi import APIRouter, Depends

from product.telephony.calls import CallView, get_call, list_calls
from product.telephony.errors import (
    TelephonyAccessDeniedError,
    TelephonyReferenceNotFoundError,
)
from product.telephony.numbers import PhoneNumberView, get_phone_number, list_phone_numbers
from product.telephony.pagination import DEFAULT_PAGE_SIZE

router = APIRouter(prefix="/v1/telephony", tags=["telephony"])

_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    TelephonyAccessDeniedError,
    TelephonyReferenceNotFoundError,
)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


def _phone_number_dict(view: PhoneNumberView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "phone_number": view.phone_number,
        "provider_name": view.provider_name,
        "provider_number_id": view.provider_number_id,
        "status": view.status,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _call_dict(view: CallView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "phone_number_id": str(view.phone_number_id),
        "provider_name": view.provider_name,
        "provider_call_id": view.provider_call_id,
        "direction": view.direction,
        "from_number": view.from_number,
        "to_number": view.to_number,
        "status": view.status,
        "contact_id": str(view.contact_id) if view.contact_id else None,
        "assigned_user_id": str(view.assigned_user_id) if view.assigned_user_id else None,
        "started_at": view.started_at.isoformat() if view.started_at else None,
        "ended_at": view.ended_at.isoformat() if view.ended_at else None,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


@router.get("/tenants/{tenant_id}/phone-numbers")
def list_phone_numbers_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _phone_number_dict(v)
        for v in _call(list_phone_numbers, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/phone-numbers/{phone_number_id}")
def get_phone_number_route(
    tenant_id: uuid.UUID,
    phone_number_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _phone_number_dict(_call(get_phone_number, actor_id, tenant_id, phone_number_id))


@router.get("/tenants/{tenant_id}/calls")
def list_calls_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    status: str | None = None,
    direction: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _call_dict(v)
        for v in _call(
            list_calls,
            actor_id,
            tenant_id,
            status=status,
            direction=direction,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("/tenants/{tenant_id}/calls/{call_id}")
def get_call_route(
    tenant_id: uuid.UUID, call_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _call_dict(_call(get_call, actor_id, tenant_id, call_id))
