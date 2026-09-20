"""The production durable-workflow API (docs/ROADMAP.md Phase 10.3),
mounted under `/v1/automation/durable` in `product/api/main.py`. Mirrors
`product/automation/routes.py`'s own established shape: `api.dependencies
.get_current_actor`, never `get_tenant_context()`/`require_permission()`
-- every service function performs its own `core.rbac.can()` check via
`product.automation.durable.permissions.require()`.

**Only the routes needed to operate the domain -- nothing that exposes
Temporal's own internal API surface or an execution control ordinary
users should not have.** No route lists/inspects/cancels a workflow
execution by its raw Temporal id; every route addresses a run by its own
Product-owned `run_id`, resolved to the right Temporal execution
internally (`product/automation/durable/runs.py`).

**`start_run`/`cancel_run`/`signal_run`/the queued-runs submission route
are `async def`** -- the one deliberate, reviewed exception to this
file's own routes otherwise mirroring 10.2's sync-`def` convention
exactly. Each calls straight into an `async def` service function in
`product/automation/durable/runs.py`/`triggers.py` that itself talks to
the Temporal client; FastAPI runs an `async def` route directly on the
main event loop, so this needs no `asyncio.run()` bridge at all -- see
`runs.py`'s own module docstring for why that bridge is unnecessary here
and was unsafe for 10.2's own synchronous event publishers.
"""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from product.automation.durable import definitions, runs, triggers
from product.automation.durable.config import DurableConfigurationError
from product.automation.errors import (
    AutomationAccessDeniedError,
    AutomationConditionError,
    AutomationReferenceNotFoundError,
    AutomationValidationError,
)
from product.automation.pagination import DEFAULT_PAGE_SIZE

router = APIRouter(prefix="/v1/automation/durable", tags=["automation-durable"])

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


async def _acall(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except _NOT_FOUND_ERRORS:
        raise not_found("resource") from None
    except DurableConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from None


class CreateWorkflowRequest(BaseModel):
    name: str = Field(max_length=255)
    start_step_key: str
    steps: list
    trigger_type: str | None = None
    trigger_config: dict = Field(default_factory=dict)


class CreateOrUpdateDraftVersionRequest(BaseModel):
    start_step_key: str
    steps: list
    trigger_type: str | None = None
    trigger_config: dict = Field(default_factory=dict)


class SetWorkflowStatusRequest(BaseModel):
    status: str


class StartRunRequest(BaseModel):
    context: dict = Field(default_factory=dict)
    idempotency_key: str | None = None


class CancelRunRequest(BaseModel):
    reason: str = Field(default="", max_length=255)


class SignalRunRequest(BaseModel):
    event_type: str
    payload: dict = Field(default_factory=dict)


def _workflow_dict(view: definitions.WorkflowView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "name": view.name,
        "status": view.status,
        "current_published_version_id": (
            str(view.current_published_version_id) if view.current_published_version_id else None
        ),
        "created_by_user_id": str(view.created_by_user_id),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _version_dict(view: definitions.WorkflowVersionView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "workflow_id": str(view.workflow_id),
        "version_number": view.version_number,
        "status": view.status,
        "trigger_type": view.trigger_type,
        "trigger_config": view.trigger_config,
        "start_step_key": view.start_step_key,
        "steps": view.steps,
        "created_by_user_id": str(view.created_by_user_id),
        "created_at": view.created_at.isoformat(),
        "published_at": view.published_at.isoformat() if view.published_at else None,
    }


def _run_dict(view: runs.RunView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "workflow_id": str(view.workflow_id),
        "workflow_version_id": str(view.workflow_version_id),
        "status": view.status,
        "actor_user_id": str(view.actor_user_id),
        "temporal_workflow_id": view.temporal_workflow_id,
        "current_step_key": view.current_step_key,
        "waiting_for_event_type": view.waiting_for_event_type,
        "error": view.error,
        "created_at": view.created_at.isoformat(),
        "started_at": view.started_at.isoformat() if view.started_at else None,
        "completed_at": view.completed_at.isoformat() if view.completed_at else None,
    }


def _run_step_dict(view: runs.RunStepView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "run_id": str(view.run_id),
        "step_key": view.step_key,
        "step_type": view.step_type,
        "status": view.status,
        "error": view.error,
        "started_at": view.started_at.isoformat(),
        "completed_at": view.completed_at.isoformat() if view.completed_at else None,
    }


@router.post("/tenants/{tenant_id}/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow_route(
    tenant_id: uuid.UUID,
    body: CreateWorkflowRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    workflow_view, version_view = _call(
        definitions.create_workflow,
        actor_id,
        tenant_id,
        name=body.name,
        start_step_key=body.start_step_key,
        steps=body.steps,
        trigger_type=body.trigger_type,
        trigger_config=body.trigger_config,
    )
    return {"workflow": _workflow_dict(workflow_view), "version": _version_dict(version_view)}


@router.get("/tenants/{tenant_id}/workflows")
def list_workflows_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _workflow_dict(v)
        for v in _call(definitions.list_workflows, actor_id, tenant_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/workflows/{workflow_id}")
def get_workflow_route(
    tenant_id: uuid.UUID, workflow_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _workflow_dict(_call(definitions.get_workflow, actor_id, tenant_id, workflow_id))


@router.patch("/tenants/{tenant_id}/workflows/{workflow_id}/status")
def set_workflow_status_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    body: SetWorkflowStatusRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _workflow_dict(
        _call(definitions.set_workflow_status, actor_id, tenant_id, workflow_id, status=body.status)
    )


@router.post(
    "/tenants/{tenant_id}/workflows/{workflow_id}/versions", status_code=status.HTTP_201_CREATED
)
def create_draft_version_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    body: CreateOrUpdateDraftVersionRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _version_dict(
        _call(
            definitions.create_draft_version,
            actor_id,
            tenant_id,
            workflow_id,
            start_step_key=body.start_step_key,
            steps=body.steps,
            trigger_type=body.trigger_type,
            trigger_config=body.trigger_config,
        )
    )


@router.get("/tenants/{tenant_id}/workflows/{workflow_id}/versions")
def list_versions_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _version_dict(v)
        for v in _call(
            definitions.list_versions, actor_id, tenant_id, workflow_id, limit=limit, offset=offset
        )
    ]


@router.get("/tenants/{tenant_id}/workflows/{workflow_id}/versions/{version_id}")
def get_version_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _version_dict(
        _call(definitions.get_version, actor_id, tenant_id, workflow_id, version_id)
    )


@router.put("/tenants/{tenant_id}/workflows/{workflow_id}/versions/{version_id}")
def update_draft_version_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    body: CreateOrUpdateDraftVersionRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _version_dict(
        _call(
            definitions.update_draft_version,
            actor_id,
            tenant_id,
            workflow_id,
            version_id,
            start_step_key=body.start_step_key,
            steps=body.steps,
            trigger_type=body.trigger_type,
            trigger_config=body.trigger_config,
        )
    )


@router.post("/tenants/{tenant_id}/workflows/{workflow_id}/versions/{version_id}/publish")
def publish_version_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _version_dict(
        _call(definitions.publish_version, actor_id, tenant_id, workflow_id, version_id)
    )


@router.post(
    "/tenants/{tenant_id}/workflows/{workflow_id}/runs", status_code=status.HTTP_201_CREATED
)
async def start_run_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    body: StartRunRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _run_dict(
        await _acall(
            runs.start_run,
            actor_id,
            tenant_id,
            workflow_id,
            context=body.context,
            idempotency_key=body.idempotency_key,
        )
    )


@router.get("/tenants/{tenant_id}/workflows/{workflow_id}/runs")
def list_runs_route(
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, object]]:
    return [
        _run_dict(v)
        for v in _call(runs.list_runs, actor_id, tenant_id, workflow_id, limit=limit, offset=offset)
    ]


@router.get("/tenants/{tenant_id}/runs/{run_id}")
def get_run_route(
    tenant_id: uuid.UUID, run_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    return _run_dict(_call(runs.get_run, actor_id, tenant_id, run_id))


@router.get("/tenants/{tenant_id}/runs/{run_id}/steps")
def list_run_steps_route(
    tenant_id: uuid.UUID, run_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> list[dict[str, object]]:
    return [_run_step_dict(v) for v in _call(runs.list_run_steps, actor_id, tenant_id, run_id)]


@router.post("/tenants/{tenant_id}/runs/{run_id}/cancel")
async def cancel_run_route(
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    body: CancelRunRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> dict[str, object]:
    return _run_dict(await _acall(runs.cancel_run, actor_id, tenant_id, run_id, reason=body.reason))


@router.post("/tenants/{tenant_id}/runs/{run_id}/signal", status_code=status.HTTP_204_NO_CONTENT)
async def signal_run_route(
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    body: SignalRunRequest,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> None:
    await _acall(
        runs.signal_run,
        actor_id,
        tenant_id,
        run_id,
        event_type=body.event_type,
        payload=body.payload,
    )


@router.post("/tenants/{tenant_id}/queued-runs/submit")
async def submit_queued_runs_route(
    tenant_id: uuid.UUID, actor_id: uuid.UUID = Depends(get_current_actor)
) -> dict[str, object]:
    """The bounded, explicitly-invoked sweep
    (`product/automation/durable/triggers.py::submit_queued_durable_runs()`'s
    own module docstring) -- never called by this product's own code;
    exists for manual/testing invocation or an external per-tenant
    scheduler, mirroring `product/automation/routes.py
    ::sweep_scheduled_workflows_route()`'s own identical, already-disclosed
    caveat exactly."""
    submitted = await _acall(triggers.submit_queued_durable_runs, actor_id, tenant_id)
    return {"submitted_count": submitted}
