"""The Automation API (docs/ROADMAP.md Phase 10.2), mounted under
`/v1/automation` in `product/api/main.py`.

**Ingress dependency choice** -- identical reasoning to every other
module's own `routes.py`: `api.dependencies.get_current_actor`, never
`get_tenant_context()`/`require_permission()`. Every
`product/automation/*.py` service function performs its own
`core.rbac.can()` check via `product.automation.permissions.require()`.

**Non-enumeration**: `AutomationAccessDeniedError`/
`AutomationReferenceNotFoundError` map to the identical `404` shape
`api.errors.not_found()` uses elsewhere. `AutomationValidationError`/
`AutomationConditionError` map to `400`.

**The scheduled-sweep route mirrors `product/appointments/routes.py
::sweep_reminders_route()`'s own documented caveat exactly** -- never
called by this product's own code; exists for manual/testing invocation
or an external per-tenant scheduler (`docs/ROADMAP.md` Phase 10.2's own
scheduled-trigger scope, `product/automation/scheduled.py`'s own module
docstring for the full reasoning).
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from product.automation.errors import (
    AutomationAccessDeniedError,
    AutomationConditionError,
    AutomationReferenceNotFoundError,
    AutomationValidationError,
)
from product.automation.pagination import DEFAULT_PAGE_SIZE
from product.automation.scheduled import sweep_scheduled_workflows
from product.automation.workflows import (
    WorkflowRunView,
    WorkflowView,
    create_workflow,
    delete_workflow,
    get_workflow,
    list_workflow_runs,
    list_workflows,
    set_workflow_status,
)

router = APIRouter(prefix="/v1/automation", tags=["automation"])

_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (
    AutomationAccessDeniedError,
    AutomationReferenceNotFoundError,
)
_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    AutomationValidationError,
    AutomationConditionError,
)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None


class CreateWorkflowRequest(BaseModel):
    name: str = Field(max_length=255)
    trigger_type: str
    trigger_config: dict = Field(default_factory=dict)
    conditions: list = Field(default_factory=list)
    action_type: str
    action_config: dict = Field(default_factory=dict)


class SetWorkflowStatusRequest(BaseModel):
    status: str


def _workflow_dict(view: WorkflowView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "trigger_type": view.trigger_type,
        "trigger_config": view.trigger_config,
        "conditions": view.conditions,
        "action_type": view.action_type,
        "action_config": view.action_config,
        "status": view.status,
        "created_by_user_id": str(view.created_by_user_id),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _run_dict(view: WorkflowRunView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "workflow_id": str(view.workflow_id),
        "trigger_dedup_key": view.trigger_dedup_key,
        "status": view.status,
        "error": view.error,
        "created_at": view.created_at.isoformat(),
        "completed_at": view.completed_at.isoformat() if view.completed_at else None,
    }


@router.post("/tenants/{tenant_id}/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow_route(
    tenant_id: uuid.UUID,
    body: CreateWorkflowRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _workflow_dict(
        _call(
            create_workflow,
            actor_id,
            tenant_id,
            name=body.name,
            trigger_type=body.trigger_type,
            trigger_config=body.trigger_config,
            conditions=body.conditions,
            action_type=body.action_type,
            action_config=body.action_config,
        )
    )


@router.get("/tenants/{tenant_id}/workflows")
def list_workflows_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _workflow_dict(v)
        for v in _call(list_workflows, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/workflows/{workflow_id}")
def get_workflow_route(
    tenant_id: uuid.UUID, workflow_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _workflow_dict(_call(get_workflow, actor_id, tenant_id, workflow_id))


@router.patch("/tenants/{tenant_id}/workflows/{workflow_id}/status")
def set_workflow_status_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    body: SetWorkflowStatusRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _workflow_dict(
        _call(set_workflow_status, actor_id, tenant_id, workflow_id, status=body.status)
    )


@router.delete(
    "/tenants/{tenant_id}/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_workflow_route(
    tenant_id: uuid.UUID, workflow_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> None:
    _call(delete_workflow, actor_id, tenant_id, workflow_id)


@router.get("/tenants/{tenant_id}/workflows/{workflow_id}/runs")
def list_workflow_runs_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _run_dict(v)
        for v in _call(
            list_workflow_runs, actor_id, tenant_id, workflow_id, limit=limit, offset=offset
        )
    ]


@router.post("/tenants/{tenant_id}/scheduled-sweep")
def sweep_scheduled_workflows_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    result = _call(sweep_scheduled_workflows, actor_id, tenant_id)
    return {
        "swept_count": result.swept_count,
        "fired_workflow_ids": [str(i) for i in result.fired_workflow_ids],
    }
