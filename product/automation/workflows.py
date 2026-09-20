"""Workflow definition CRUD (docs/ROADMAP.md Phase 10.2). Every function
follows the shape established by every other product module: authorize
via `product.automation.permissions.require()` first, then the actual
`tenant_session_scope()` read/write, then `core.audit_log.record()` for
mutations.

**`created_by_user_id` is set once, at creation, to the creating actor,
and is never itself editable** -- changing which identity a workflow
executes as would let a lower-privileged user "steal" a higher-privileged
one's execution rights merely by editing an existing workflow. Only the
original creator's own identity carries a workflow's authorization
forever (`docs/ADR/0008-automation-depends-on-crm.md`'s own point 2).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.rbac import can
from infra.db import select, tenant_session_scope

from product.automation.actions import validate_action_config, validate_action_type
from product.automation.conditions import validate_conditions
from product.automation.dispatcher import TRIGGER_EVENT_TYPES
from product.automation.errors import AutomationReferenceNotFoundError, AutomationValidationError
from product.automation.models import (
    STATUS_ACTIVE,
    VALID_WORKFLOW_STATUSES,
    Workflow,
    WorkflowRun,
)
from product.automation.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.automation.permissions import WORKFLOW_RESOURCE, require

MAX_CONFIG_JSON_CHARS = 8_000
MAX_NAME_LENGTH = 255

# "scheduled" is not (yet) an event-dispatcher trigger type -- see
# product/automation/scheduled.py's own module docstring for how it is
# actually swept. Still a valid trigger_type value a workflow may declare.
SCHEDULED_TRIGGER_TYPE = "scheduled"
VALID_TRIGGER_TYPES = frozenset({*TRIGGER_EVENT_TYPES, SCHEDULED_TRIGGER_TYPE})


def _validate_json_size(value: object, field_name: str) -> None:
    encoded = json.dumps(value, default=str)
    if len(encoded) > MAX_CONFIG_JSON_CHARS:
        raise AutomationValidationError(
            f"{field_name} exceeds {MAX_CONFIG_JSON_CHARS} characters when serialized."
        )


def _validate_workflow_definition(
    trigger_type: str, trigger_config: dict, conditions: list, action_type: str, action_config: dict
) -> None:
    if trigger_type not in VALID_TRIGGER_TYPES:
        raise AutomationValidationError(
            f"trigger_type must be one of {sorted(VALID_TRIGGER_TYPES)}, got {trigger_type!r}."
        )
    _validate_json_size(trigger_config, "trigger_config")
    _validate_json_size(conditions, "conditions")
    validate_conditions(conditions)
    validate_action_type(action_type)
    _validate_json_size(action_config, "action_config")
    validate_action_config(action_type, action_config)


def _validate_creator_reachable(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """The real IDOR-adjacent check -- mirrors every other module's own
    identical pattern (`product/telephony/numbers.py
    ::_validate_user_reachable()`). Checking `(WORKFLOW_RESOURCE, "read")`
    is deliberately the lowest bar every granted role includes."""
    if not can(actor_id=user_id, tenant_id=tenant_id, action="read", resource=WORKFLOW_RESOURCE):
        raise AutomationReferenceNotFoundError("user", user_id)


@dataclass(frozen=True, slots=True)
class WorkflowView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    trigger_type: str
    trigger_config: dict
    conditions: list
    action_type: str
    action_config: dict
    status: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


def _to_view(row: Workflow) -> WorkflowView:
    return WorkflowView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        trigger_type=row.trigger_type,
        trigger_config=dict(row.trigger_config),
        conditions=list(row.conditions),
        action_type=row.action_type,
        action_config=dict(row.action_config),
        status=row.status,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_workflow(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    trigger_type: str,
    trigger_config: dict | None = None,
    conditions: list | None = None,
    action_type: str,
    action_config: dict | None = None,
) -> WorkflowView:
    require(actor_user_id, tenant_id, resource=WORKFLOW_RESOURCE, action="create")
    if not name or len(name) > MAX_NAME_LENGTH:
        raise AutomationValidationError(f"name must be 1-{MAX_NAME_LENGTH} characters.")
    trigger_config = trigger_config or {}
    conditions = conditions or []
    action_config = action_config or {}
    _validate_workflow_definition(
        trigger_type, trigger_config, conditions, action_type, action_config
    )
    _validate_creator_reachable(tenant_id, actor_user_id)

    with tenant_session_scope(tenant_id) as session:
        row = Workflow(
            tenant_id=tenant_id,
            name=name,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            conditions=conditions,
            action_type=action_type,
            action_config=action_config,
            status=STATUS_ACTIVE,
            created_by_user_id=actor_user_id,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.workflow.create",
        resource_type="automation.workflow",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"trigger_type": trigger_type, "action_type": action_type},
    )
    return _to_view(row)


def get_workflow(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, workflow_id: uuid.UUID
) -> WorkflowView:
    require(actor_user_id, tenant_id, resource=WORKFLOW_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Workflow, workflow_id)
        if row is None or row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("workflow", workflow_id)
        session.expunge(row)
    return _to_view(row)


def list_workflows(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[WorkflowView]:
    require(actor_user_id, tenant_id, resource=WORKFLOW_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Workflow)
                .where(Workflow.tenant_id == tenant_id)
                .order_by(Workflow.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def set_workflow_status(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, workflow_id: uuid.UUID, *, status: str
) -> WorkflowView:
    """Pause/resume -- `docs/ROADMAP.md` Phase 10.2's own explicit
    Rollback requirement: "a misbehaving automation can be paused/disabled
    per-tenant without affecting the rest of the platform." A paused
    workflow is simply never matched by
    `product/automation/dispatcher.py::_matching_active_workflows()`."""
    require(actor_user_id, tenant_id, resource=WORKFLOW_RESOURCE, action="update")
    if status not in VALID_WORKFLOW_STATUSES:
        raise AutomationValidationError(
            f"status must be one of {VALID_WORKFLOW_STATUSES}, got {status!r}."
        )
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Workflow, workflow_id)
        if row is None or row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("workflow", workflow_id)
        row.status = status
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.workflow.set_status",
        resource_type="automation.workflow",
        resource_id=str(workflow_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"status": status},
    )
    return _to_view(row)


def delete_workflow(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=WORKFLOW_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Workflow, workflow_id)
        if row is None or row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("workflow", workflow_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.workflow.delete",
        resource_type="automation.workflow",
        resource_id=str(workflow_id),
        outcome=AuditOutcome.SUCCESS,
    )


@dataclass(frozen=True, slots=True)
class WorkflowRunView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    trigger_dedup_key: str
    status: str
    error: str | None
    created_at: datetime
    completed_at: datetime | None


def _run_to_view(row: WorkflowRun) -> WorkflowRunView:
    return WorkflowRunView(
        id=row.id,
        tenant_id=row.tenant_id,
        workflow_id=row.workflow_id,
        trigger_dedup_key=row.trigger_dedup_key,
        status=row.status,
        error=row.error,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def list_workflow_runs(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[WorkflowRunView]:
    require(actor_user_id, tenant_id, resource=WORKFLOW_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        workflow = session.get(Workflow, workflow_id)
        if workflow is None or workflow.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("workflow", workflow_id)
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(WorkflowRun)
                .where(WorkflowRun.tenant_id == tenant_id, WorkflowRun.workflow_id == workflow_id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_run_to_view(row) for row in rows]


__all__ = [
    "MAX_CONFIG_JSON_CHARS",
    "SCHEDULED_TRIGGER_TYPE",
    "VALID_TRIGGER_TYPES",
    "WorkflowRunView",
    "WorkflowView",
    "create_workflow",
    "delete_workflow",
    "get_workflow",
    "list_workflow_runs",
    "list_workflows",
    "set_workflow_status",
]
