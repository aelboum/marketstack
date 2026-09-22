"""The CRM API (docs/ROADMAP.md Phase 4), mounted under `/v1/crm` in
`product/api/main.py`.

**Ingress dependency choice -- read `docs/ADR/0002-agency-cross-tenant-
route-authorization.md`'s Phase 4 addendum before changing this.** Every
route below uses `api.dependencies.get_current_actor`, not
`api.dependencies.get_tenant_context`/`require_permission()` -- an
agency owner reaching a client's CRM data only via inherited `SUBTREE`
role has no direct membership at that client tenant, so
`get_tenant_context()` would 404 them. Every `product/crm/*.py` service
function performs its own `core.rbac.can()` check via
`product.crm.permissions.require()` before touching any `crm.*` row --
this is a different, equally-enforced ingress dependency, not a bypass.

**Non-enumeration**: `CrmAccessDeniedError` and `CrmReferenceNotFoundError`
both map to the identical `404` shape `api.errors.not_found()` uses
elsewhere in this platform -- never a `403`, never a distinguishable
message between "doesn't exist" and "exists but you can't touch it."
`CrmValidationError` and the `product.foundation.values` validation
errors (bad phone number, bad currency code, bad amount) are client
input errors, mapped to a plain `400` instead -- they are not an
authorization or existence question.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from api.dependencies import get_current_actor
from api.errors import not_found
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from product.crm.activities import (
    complete_task,
    create_note,
    create_task,
    delete_note,
    delete_task,
    list_activities,
)
from product.crm.companies import (
    create_company,
    delete_company,
    get_company,
    list_companies,
    update_company,
)
from product.crm.contacts import (
    create_contact,
    delete_contact,
    get_contact,
    list_contacts,
    update_contact,
)
from product.crm.custom_fields import (
    define_field,
    get_field_values,
    list_field_definitions,
    set_field_value,
)
from product.crm.errors import CrmAccessDeniedError, CrmReferenceNotFoundError, CrmValidationError
from product.crm.imports import (
    MAX_IMPORT_FILE_SIZE_BYTES,
    enqueue_contact_import,
    export_contacts_csv,
    get_import_job,
)
from product.crm.opportunities import (
    assign_opportunity,
    change_stage,
    create_opportunity,
    delete_opportunity,
    get_opportunity,
    list_opportunities,
    update_opportunity,
)
from product.crm.pagination import DEFAULT_PAGE_SIZE
from product.crm.pipelines import create_pipeline, create_stage, list_pipelines, list_stages
from product.crm.tags import attach_tag, create_tag, detach_tag, list_tags, list_tags_for_entity
from product.foundation.values import (
    InvalidCurrencyCodeError,
    InvalidMoneyAmountError,
    InvalidPhoneNumberError,
    Money,
)

router = APIRouter(prefix="/v1/crm", tags=["crm"])

_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (CrmAccessDeniedError, CrmReferenceNotFoundError)
_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    CrmValidationError,
    InvalidPhoneNumberError,
    InvalidCurrencyCodeError,
    InvalidMoneyAmountError,
)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


async def _acall(fn, *args, **kwargs):
    """The `async def` counterpart of `_call()`, identical error mapping
    -- used only by `product/crm/imports.py::enqueue_contact_import()`,
    the one CRM service function that is itself a coroutine (it awaits
    `infra.jobs.enqueue_job()`)."""
    try:
        return await fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


# --- Request bodies ---------------------------------------------------------


class CreateCompanyRequest(BaseModel):
    name: str
    domain: str | None = None
    phone: str | None = None


class UpdateCompanyRequest(BaseModel):
    name: str | None = None
    domain: str | None = None
    phone: str | None = None


class CreateContactRequest(BaseModel):
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    company_id: uuid.UUID | None = None


class UpdateContactRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    company_id: uuid.UUID | None = None


class CreatePipelineRequest(BaseModel):
    name: str
    is_default: bool = False


class CreateStageRequest(BaseModel):
    name: str
    position: int
    is_won: bool = False
    is_lost: bool = False


class CreateOpportunityRequest(BaseModel):
    name: str
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    amount_decimal: str | None = None
    amount_currency: str | None = None


class UpdateOpportunityRequest(BaseModel):
    name: str | None = None
    amount_decimal: str | None = None
    amount_currency: str | None = None


class ChangeStageRequest(BaseModel):
    stage_id: uuid.UUID


class AssignOpportunityRequest(BaseModel):
    assigned_user_id: uuid.UUID | None = None


class CreateTaskRequest(BaseModel):
    title: str
    description: str | None = None
    due_at: datetime | None = None


class CreateNoteRequest(BaseModel):
    body: str


class CompleteTaskRequest(BaseModel):
    completed_at: datetime | None = None


def _money_or_none(amount_decimal: str | None, amount_currency: str | None) -> Money | None:
    if amount_decimal is None and amount_currency is None:
        return None
    if amount_decimal is None or amount_currency is None:
        raise CrmValidationError(
            "amount_decimal and amount_currency must both be set or both omitted."
        )
    return Money.from_decimal(amount_decimal, amount_currency)


def _company_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "domain": view.domain,
        "phone": view.phone,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _contact_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "first_name": view.first_name,
        "last_name": view.last_name,
        "email": view.email,
        "phone": view.phone,
        "company_id": str(view.company_id) if view.company_id else None,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _opportunity_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "contact_id": str(view.contact_id) if view.contact_id else None,
        "company_id": str(view.company_id) if view.company_id else None,
        "pipeline_id": str(view.pipeline_id),
        "stage_id": str(view.stage_id),
        "assigned_user_id": str(view.assigned_user_id) if view.assigned_user_id else None,
        "amount": str(view.amount) if view.amount else None,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _activity_dict(view) -> dict[str, object]:
    base = {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "kind": view.kind,
        "contact_id": str(view.contact_id) if view.contact_id else None,
        "company_id": str(view.company_id) if view.company_id else None,
        "opportunity_id": str(view.opportunity_id) if view.opportunity_id else None,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }
    if view.kind == "task":
        base.update(
            title=view.title,
            description=view.description,
            due_at=view.due_at.isoformat() if view.due_at else None,
            completed_at=view.completed_at.isoformat() if view.completed_at else None,
        )
    else:
        base.update(body=view.body)
    return base


# --- Companies ---------------------------------------------------------------


@router.post("/tenants/{tenant_id}/companies", status_code=status.HTTP_201_CREATED)
def create_company_route(
    tenant_id: uuid.UUID,
    body: CreateCompanyRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _company_dict(
        _call(
            create_company,
            actor_id,
            tenant_id,
            name=body.name,
            domain=body.domain,
            phone=body.phone,
        )
    )


@router.get("/tenants/{tenant_id}/companies")
def list_companies_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    q: str | None = None,
    tag: str | None = None,
    custom_field: list[str] = Query(default=[]),
) -> list[dict[str, object]]:
    return [
        _company_dict(v)
        for v in _call(
            list_companies,
            actor_id,
            tenant_id,
            limit=limit,
            offset=offset,
            q=q,
            tag=tag,
            custom_field=custom_field or None,
        )
    ]


@router.get("/tenants/{tenant_id}/companies/{company_id}")
def get_company_route(
    tenant_id: uuid.UUID, company_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _company_dict(_call(get_company, actor_id, tenant_id, company_id))


@router.patch("/tenants/{tenant_id}/companies/{company_id}")
def update_company_route(
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    body: UpdateCompanyRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _company_dict(
        _call(
            update_company,
            actor_id,
            tenant_id,
            company_id,
            name=body.name,
            domain=body.domain,
            phone=body.phone,
        )
    )


@router.delete(
    "/tenants/{tenant_id}/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_company_route(
    tenant_id: uuid.UUID, company_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_company, actor_id, tenant_id, company_id)


# --- Contacts ------------------------------------------------------------


@router.post("/tenants/{tenant_id}/contacts", status_code=status.HTTP_201_CREATED)
def create_contact_route(
    tenant_id: uuid.UUID,
    body: CreateContactRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _contact_dict(
        _call(
            create_contact,
            actor_id,
            tenant_id,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            phone=body.phone,
            company_id=body.company_id,
        )
    )


@router.get("/tenants/{tenant_id}/contacts")
def list_contacts_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    q: str | None = None,
    tag: str | None = None,
    custom_field: list[str] = Query(default=[]),
) -> list[dict[str, object]]:
    return [
        _contact_dict(v)
        for v in _call(
            list_contacts,
            actor_id,
            tenant_id,
            limit=limit,
            offset=offset,
            q=q,
            tag=tag,
            custom_field=custom_field or None,
        )
    ]


@router.get("/tenants/{tenant_id}/contacts/{contact_id}")
def get_contact_route(
    tenant_id: uuid.UUID, contact_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _contact_dict(_call(get_contact, actor_id, tenant_id, contact_id))


@router.patch("/tenants/{tenant_id}/contacts/{contact_id}")
def update_contact_route(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: UpdateContactRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _contact_dict(
        _call(
            update_contact,
            actor_id,
            tenant_id,
            contact_id,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            phone=body.phone,
            company_id=body.company_id,
        )
    )


@router.delete("/tenants/{tenant_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact_route(
    tenant_id: uuid.UUID, contact_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_contact, actor_id, tenant_id, contact_id)


# --- Pipelines / stages ----------------------------------------------------


@router.post("/tenants/{tenant_id}/pipelines", status_code=status.HTTP_201_CREATED)
def create_pipeline_route(
    tenant_id: uuid.UUID,
    body: CreatePipelineRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    view = _call(create_pipeline, actor_id, tenant_id, name=body.name, is_default=body.is_default)
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "is_default": view.is_default,
        "created_at": view.created_at.isoformat(),
    }


@router.get("/tenants/{tenant_id}/pipelines")
def list_pipelines_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    return [
        {
            "id": str(v.id),
            "tenant_id": str(v.tenant_id),
            "name": v.name,
            "is_default": v.is_default,
            "created_at": v.created_at.isoformat(),
        }
        for v in _call(list_pipelines, actor_id, tenant_id)
    ]


@router.post(
    "/tenants/{tenant_id}/pipelines/{pipeline_id}/stages", status_code=status.HTTP_201_CREATED
)
def create_stage_route(
    tenant_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    body: CreateStageRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    view = _call(
        create_stage,
        actor_id,
        tenant_id,
        pipeline_id,
        name=body.name,
        position=body.position,
        is_won=body.is_won,
        is_lost=body.is_lost,
    )
    return {
        "id": str(view.id),
        "pipeline_id": str(view.pipeline_id),
        "name": view.name,
        "position": view.position,
        "is_won": view.is_won,
        "is_lost": view.is_lost,
    }


@router.get("/tenants/{tenant_id}/pipelines/{pipeline_id}/stages")
def list_stages_route(
    tenant_id: uuid.UUID, pipeline_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    return [
        {
            "id": str(v.id),
            "pipeline_id": str(v.pipeline_id),
            "name": v.name,
            "position": v.position,
            "is_won": v.is_won,
            "is_lost": v.is_lost,
        }
        for v in _call(list_stages, actor_id, tenant_id, pipeline_id)
    ]


# --- Opportunities ---------------------------------------------------------


@router.post("/tenants/{tenant_id}/opportunities", status_code=status.HTTP_201_CREATED)
def create_opportunity_route(
    tenant_id: uuid.UUID,
    body: CreateOpportunityRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    amount = _money_or_none(body.amount_decimal, body.amount_currency)
    return _opportunity_dict(
        _call(
            create_opportunity,
            actor_id,
            tenant_id,
            name=body.name,
            pipeline_id=body.pipeline_id,
            stage_id=body.stage_id,
            contact_id=body.contact_id,
            company_id=body.company_id,
            amount=amount,
        )
    )


@router.get("/tenants/{tenant_id}/opportunities")
def list_opportunities_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    q: str | None = None,
    tag: str | None = None,
    custom_field: list[str] = Query(default=[]),
) -> list[dict[str, object]]:
    return [
        _opportunity_dict(v)
        for v in _call(
            list_opportunities,
            actor_id,
            tenant_id,
            limit=limit,
            offset=offset,
            q=q,
            tag=tag,
            custom_field=custom_field or None,
        )
    ]


@router.get("/tenants/{tenant_id}/opportunities/{opportunity_id}")
def get_opportunity_route(
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _opportunity_dict(_call(get_opportunity, actor_id, tenant_id, opportunity_id))


@router.patch("/tenants/{tenant_id}/opportunities/{opportunity_id}")
def update_opportunity_route(
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    body: UpdateOpportunityRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    amount = _money_or_none(body.amount_decimal, body.amount_currency)
    return _opportunity_dict(
        _call(
            update_opportunity, actor_id, tenant_id, opportunity_id, name=body.name, amount=amount
        )
    )


@router.delete(
    "/tenants/{tenant_id}/opportunities/{opportunity_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_opportunity_route(
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    _call(delete_opportunity, actor_id, tenant_id, opportunity_id)


@router.post("/tenants/{tenant_id}/opportunities/{opportunity_id}/stage")
def change_stage_route(
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    body: ChangeStageRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _opportunity_dict(
        _call(change_stage, actor_id, tenant_id, opportunity_id, body.stage_id)
    )


@router.post("/tenants/{tenant_id}/opportunities/{opportunity_id}/assign")
def assign_opportunity_route(
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    body: AssignOpportunityRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _opportunity_dict(
        _call(assign_opportunity, actor_id, tenant_id, opportunity_id, body.assigned_user_id)
    )


# --- Tasks / notes / activities, per parent entity type ---------------------


@router.post(
    "/tenants/{tenant_id}/contacts/{contact_id}/tasks", status_code=status.HTTP_201_CREATED
)
def create_contact_task_route(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: CreateTaskRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _activity_dict(
        _call(
            create_task,
            actor_id,
            tenant_id,
            title=body.title,
            description=body.description,
            due_at=body.due_at,
            contact_id=contact_id,
        )
    )


@router.post(
    "/tenants/{tenant_id}/companies/{company_id}/tasks", status_code=status.HTTP_201_CREATED
)
def create_company_task_route(
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    body: CreateTaskRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _activity_dict(
        _call(
            create_task,
            actor_id,
            tenant_id,
            title=body.title,
            description=body.description,
            due_at=body.due_at,
            company_id=company_id,
        )
    )


@router.post(
    "/tenants/{tenant_id}/opportunities/{opportunity_id}/tasks", status_code=status.HTTP_201_CREATED
)
def create_opportunity_task_route(
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    body: CreateTaskRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _activity_dict(
        _call(
            create_task,
            actor_id,
            tenant_id,
            title=body.title,
            description=body.description,
            due_at=body.due_at,
            opportunity_id=opportunity_id,
        )
    )


@router.post("/tenants/{tenant_id}/tasks/{task_id}/complete")
def complete_task_route(
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    body: CompleteTaskRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    completed_at = body.completed_at or datetime.now(UTC)
    return _activity_dict(
        _call(complete_task, actor_id, tenant_id, task_id, completed_at=completed_at)
    )


@router.delete("/tenants/{tenant_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task_route(
    tenant_id: uuid.UUID, task_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_task, actor_id, tenant_id, task_id)


@router.post(
    "/tenants/{tenant_id}/contacts/{contact_id}/notes", status_code=status.HTTP_201_CREATED
)
def create_contact_note_route(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: CreateNoteRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _activity_dict(
        _call(create_note, actor_id, tenant_id, body=body.body, contact_id=contact_id)
    )


@router.post(
    "/tenants/{tenant_id}/companies/{company_id}/notes", status_code=status.HTTP_201_CREATED
)
def create_company_note_route(
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    body: CreateNoteRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _activity_dict(
        _call(create_note, actor_id, tenant_id, body=body.body, company_id=company_id)
    )


@router.post(
    "/tenants/{tenant_id}/opportunities/{opportunity_id}/notes", status_code=status.HTTP_201_CREATED
)
def create_opportunity_note_route(
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    body: CreateNoteRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _activity_dict(
        _call(create_note, actor_id, tenant_id, body=body.body, opportunity_id=opportunity_id)
    )


@router.delete("/tenants/{tenant_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note_route(
    tenant_id: uuid.UUID, note_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_note, actor_id, tenant_id, note_id)


@router.get("/tenants/{tenant_id}/contacts/{contact_id}/activities")
def list_contact_activities_route(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _activity_dict(v)
        for v in _call(
            list_activities, actor_id, tenant_id, contact_id=contact_id, limit=limit, offset=offset
        )
    ]


@router.get("/tenants/{tenant_id}/companies/{company_id}/activities")
def list_company_activities_route(
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _activity_dict(v)
        for v in _call(
            list_activities, actor_id, tenant_id, company_id=company_id, limit=limit, offset=offset
        )
    ]


@router.get("/tenants/{tenant_id}/opportunities/{opportunity_id}/activities")
def list_opportunity_activities_route(
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _activity_dict(v)
        for v in _call(
            list_activities,
            actor_id,
            tenant_id,
            opportunity_id=opportunity_id,
            limit=limit,
            offset=offset,
        )
    ]


# --- Custom fields (Phase 4.4) ----------------------------------------------


class DefineFieldRequest(BaseModel):
    entity_type: str
    name: str
    field_type: str


class SetFieldValueRequest(BaseModel):
    field_definition_id: uuid.UUID
    value: object


def _field_definition_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "entity_type": view.entity_type,
        "name": view.name,
        "field_type": view.field_type,
        "created_at": view.created_at.isoformat(),
    }


def _field_value_dict(view) -> dict[str, object]:
    value = view.value
    return {
        "id": str(view.id),
        "field_definition_id": str(view.field_definition_id),
        "entity_type": view.entity_type,
        "entity_id": str(view.entity_id),
        "value": value.isoformat() if hasattr(value, "isoformat") else value,
    }


@router.post("/tenants/{tenant_id}/custom-fields", status_code=status.HTTP_201_CREATED)
def define_field_route(
    tenant_id: uuid.UUID,
    body: DefineFieldRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _field_definition_dict(
        _call(
            define_field,
            actor_id,
            tenant_id,
            entity_type=body.entity_type,
            name=body.name,
            field_type=body.field_type,
        )
    )


@router.get("/tenants/{tenant_id}/custom-fields")
def list_field_definitions_route(
    tenant_id: uuid.UUID,
    entity_type: str,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _field_definition_dict(v)
        for v in _call(list_field_definitions, actor_id, tenant_id, entity_type)
    ]


@router.put("/tenants/{tenant_id}/{entity_type}/{entity_id}/custom-fields")
def set_field_value_route(
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    body: SetFieldValueRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _field_value_dict(
        _call(
            set_field_value,
            actor_id,
            tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            field_definition_id=body.field_definition_id,
            value=body.value,
        )
    )


@router.get("/tenants/{tenant_id}/{entity_type}/{entity_id}/custom-fields")
def get_field_values_route(
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _field_value_dict(v)
        for v in _call(
            get_field_values, actor_id, tenant_id, entity_type=entity_type, entity_id=entity_id
        )
    ]


# --- Tags (Phase 4.4) --------------------------------------------------------


class CreateTagRequest(BaseModel):
    name: str


class TagAttachRequest(BaseModel):
    tag_id: uuid.UUID


def _tag_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "created_at": view.created_at.isoformat(),
    }


@router.post("/tenants/{tenant_id}/tags", status_code=status.HTTP_201_CREATED)
def create_tag_route(
    tenant_id: uuid.UUID, body: CreateTagRequest, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _tag_dict(_call(create_tag, actor_id, tenant_id, name=body.name))


@router.get("/tenants/{tenant_id}/tags")
def list_tags_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    return [_tag_dict(v) for v in _call(list_tags, actor_id, tenant_id)]


@router.post(
    "/tenants/{tenant_id}/{entity_type}/{entity_id}/tags", status_code=status.HTTP_204_NO_CONTENT
)
def attach_tag_route(
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    body: TagAttachRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    _call(
        attach_tag,
        actor_id,
        tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        tag_id=body.tag_id,
    )


@router.delete(
    "/tenants/{tenant_id}/{entity_type}/{entity_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def detach_tag_route(
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    tag_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    _call(
        detach_tag, actor_id, tenant_id, entity_type=entity_type, entity_id=entity_id, tag_id=tag_id
    )


@router.get("/tenants/{tenant_id}/{entity_type}/{entity_id}/tags")
def list_tags_for_entity_route(
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    return [
        _tag_dict(v)
        for v in _call(
            list_tags_for_entity, actor_id, tenant_id, entity_type=entity_type, entity_id=entity_id
        )
    ]


# --- Import / export (Phase 4.5) --------------------------------------------


def _import_job_dict(view) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "status": view.status,
        "total_rows": view.total_rows,
        "succeeded_rows": view.succeeded_rows,
        "failed_rows": view.failed_rows,
        "error_report": view.error_report,
        "created_at": view.created_at.isoformat(),
        "completed_at": view.completed_at.isoformat() if view.completed_at else None,
    }


class ImportContactsRequest(BaseModel):
    csv_content: str


@router.post("/tenants/{tenant_id}/contact-imports", status_code=status.HTTP_202_ACCEPTED)
async def import_contacts_route(
    # NOTE: deliberately NOT "/contacts/import" -- this router already
    # registers "/contacts/{contact_id}" earlier in this file, and FastAPI
    # matches routes in registration order, so "/contacts/import" would be
    # shadowed by "/contacts/{contact_id}" (treating "import" as a contact
    # id, a 422, never reaching this handler). A distinct path segment
    # avoids the collision entirely rather than depending on route order.
    #
    # NOTE 2: a plain JSON body (`csv_content: str`), not a `multipart/
    # form-data` file upload -- FastAPI's `UploadFile` requires the
    # `python-multipart` package to parse multipart bodies at all, which
    # is not an installed or authorized dependency for this phase (this
    # phase's scope discipline: "no new dependencies... use Python's
    # stdlib csv module, not a new library" -- multipart parsing is a
    # distinct concern from CSV parsing, but the same "no new dependency"
    # constraint applies to it too). A future phase adopting real file
    # uploads (e.g. once object storage exists, docs/RESPONSIBILITY-MATRIX
    # .md's "Object/file storage" row) is the natural point to revisit
    # this and add `python-multipart` deliberately, not here.
    tenant_id: uuid.UUID,
    body: ImportContactsRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    if len(body.csv_content.encode("utf-8")) > MAX_IMPORT_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"csv_content exceeds the {MAX_IMPORT_FILE_SIZE_BYTES} byte import size limit.",
        )
    view = await _acall(enqueue_contact_import, actor_id, tenant_id, csv_content=body.csv_content)
    return _import_job_dict(view)


@router.get("/tenants/{tenant_id}/imports/{import_job_id}")
def get_import_job_route(
    tenant_id: uuid.UUID, import_job_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _import_job_dict(_call(get_import_job, actor_id, tenant_id, import_job_id))


@router.get("/tenants/{tenant_id}/contact-exports")
def export_contacts_route(
    # NOTE: same route-ordering reason as import_contacts_route above --
    # "/contacts/export" would be shadowed by "/contacts/{contact_id}".
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> PlainTextResponse:
    csv_text = _call(export_contacts_csv, actor_id, tenant_id)
    return PlainTextResponse(content=csv_text, media_type="text/csv")
