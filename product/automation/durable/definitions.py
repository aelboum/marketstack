"""Workflow/workflow-version definition CRUD (docs/ROADMAP.md Phase
10.3). Mirrors `product/automation/workflows.py`'s own established
shape exactly: authorize via `require()` first, then the
`tenant_session_scope()` read/write, then `core.audit_log.record()` for
every mutation.

**Immutability enforcement lives here, not in the database.** Nothing
below ever assigns to `WorkflowVersion.steps`/`start_step_key`/
`trigger_type`/`trigger_config` once `status == VERSION_STATUS_PUBLISHED`
-- `update_draft_version()` raises `AutomationValidationError` before
even opening a write transaction if the target version is already
published (this phase's own "a published version must be immutable"
requirement). `publish_version()` is the one and only place `status`
moves `draft -> published`, and it never moves back.

**`created_by_user_id` is the same load-bearing privilege-boundary
field 10.2 already established** (`product/automation/workflows.py`'s
own module docstring, `docs/ADR/0008-automation-depends-on-crm.md`'s
point 2) -- set once, at workflow creation, from the creating actor,
never itself editable, and it becomes every run's own default
`actor_user_id` (`runs.py`'s own module docstring) -- the identity every
step re-authorizes as, at execution time.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.rbac import can
from infra.db import select, tenant_session_scope

from product.automation.dispatcher import TRIGGER_EVENT_TYPES
from product.automation.durable.dsl import validate_workflow_definition
from product.automation.durable.models import (
    MAX_NAME_LENGTH,
    STATUS_ACTIVE,
    VALID_WORKFLOW_STATUSES,
    VERSION_STATUS_DRAFT,
    VERSION_STATUS_PUBLISHED,
    Workflow,
    WorkflowVersion,
)
from product.automation.durable.permissions import DURABLE_WORKFLOW_RESOURCE, require
from product.automation.errors import AutomationReferenceNotFoundError, AutomationValidationError
from product.automation.pagination import DEFAULT_PAGE_SIZE, clamp_limit

VALID_DURABLE_TRIGGER_TYPES = frozenset(TRIGGER_EVENT_TYPES)
MAX_TRIGGER_CONFIG_JSON_CHARS = 8_000


def _validate_trigger(trigger_type: str | None, trigger_config: dict) -> None:
    if trigger_type is not None and trigger_type not in VALID_DURABLE_TRIGGER_TYPES:
        raise AutomationValidationError(
            f"trigger_type must be one of {sorted(VALID_DURABLE_TRIGGER_TYPES)} or null "
            f"(manual-start only), got {trigger_type!r}."
        )
    encoded = json.dumps(trigger_config, default=str)
    if len(encoded) > MAX_TRIGGER_CONFIG_JSON_CHARS:
        raise AutomationValidationError(
            f"trigger_config exceeds {MAX_TRIGGER_CONFIG_JSON_CHARS} characters when serialized."
        )


def _validate_creator_reachable(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """The IDOR-adjacent check -- identical precedent to
    `product/automation/workflows.py::_validate_creator_reachable()`."""
    if not can(
        actor_id=user_id, tenant_id=tenant_id, action="read", resource=DURABLE_WORKFLOW_RESOURCE
    ):
        raise AutomationReferenceNotFoundError("user", user_id)


@dataclass(frozen=True, slots=True)
class WorkflowView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    status: str
    current_published_version_id: uuid.UUID | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkflowVersionView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    version_number: int
    status: str
    trigger_type: str | None
    trigger_config: dict
    start_step_key: str
    steps: list
    created_by_user_id: uuid.UUID
    created_at: datetime
    published_at: datetime | None


def _workflow_to_view(row: Workflow) -> WorkflowView:
    return WorkflowView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        status=row.status,
        current_published_version_id=row.current_published_version_id,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _version_to_view(row: WorkflowVersion) -> WorkflowVersionView:
    return WorkflowVersionView(
        id=row.id,
        tenant_id=row.tenant_id,
        workflow_id=row.workflow_id,
        version_number=row.version_number,
        status=row.status,
        trigger_type=row.trigger_type,
        trigger_config=dict(row.trigger_config),
        start_step_key=row.start_step_key,
        steps=list(row.steps),
        created_by_user_id=row.created_by_user_id,
        published_at=row.published_at,
        created_at=row.created_at,
    )


def create_workflow(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    start_step_key: str,
    steps: list,
    trigger_type: str | None = None,
    trigger_config: dict | None = None,
) -> tuple[WorkflowView, WorkflowVersionView]:
    """Creates the stable `Workflow` identity plus its first version, as
    `draft` (`version_number=1`) -- never `published` directly; a caller
    must call `publish_version()` explicitly, so a definition is always
    reviewable before it can ever execute."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="create")
    if not name or len(name) > MAX_NAME_LENGTH:
        raise AutomationValidationError(f"name must be 1-{MAX_NAME_LENGTH} characters.")
    trigger_config = trigger_config or {}
    _validate_trigger(trigger_type, trigger_config)
    validate_workflow_definition(start_step_key, steps)
    _validate_creator_reachable(tenant_id, actor_user_id)

    with tenant_session_scope(tenant_id) as session:
        workflow_row = Workflow(
            tenant_id=tenant_id,
            name=name,
            status=STATUS_ACTIVE,
            created_by_user_id=actor_user_id,
        )
        session.add(workflow_row)
        session.flush()
        version_row = WorkflowVersion(
            tenant_id=tenant_id,
            workflow_id=workflow_row.id,
            version_number=1,
            status=VERSION_STATUS_DRAFT,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            start_step_key=start_step_key,
            steps=steps,
            created_by_user_id=actor_user_id,
        )
        session.add(version_row)
        session.flush()
        session.refresh(workflow_row)
        session.refresh(version_row)
        session.expunge(workflow_row)
        session.expunge(version_row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_workflow.create",
        resource_type="automation.durable_workflow",
        resource_id=str(workflow_row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"version_number": 1},
    )
    return _workflow_to_view(workflow_row), _version_to_view(version_row)


def create_draft_version(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    *,
    start_step_key: str,
    steps: list,
    trigger_type: str | None = None,
    trigger_config: dict | None = None,
) -> WorkflowVersionView:
    """A new, separate `draft` version -- never mutates any existing
    version (`draft` or `published`). This is the *only* way to change a
    workflow whose current version is already published (module
    docstring's own "new changes create a new version" rule)."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="update")
    trigger_config = trigger_config or {}
    _validate_trigger(trigger_type, trigger_config)
    validate_workflow_definition(start_step_key, steps)

    with tenant_session_scope(tenant_id) as session:
        workflow_row = session.get(Workflow, workflow_id)
        if workflow_row is None or workflow_row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("workflow", workflow_id)
        latest_number = session.execute(
            select(WorkflowVersion.version_number)
            .where(
                WorkflowVersion.tenant_id == tenant_id,
                WorkflowVersion.workflow_id == workflow_id,
            )
            .order_by(WorkflowVersion.version_number.desc())
            .limit(1)
        ).scalar_one()
        version_row = WorkflowVersion(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            version_number=latest_number + 1,
            status=VERSION_STATUS_DRAFT,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            start_step_key=start_step_key,
            steps=steps,
            created_by_user_id=actor_user_id,
        )
        session.add(version_row)
        session.flush()
        session.refresh(version_row)
        session.expunge(version_row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_workflow.create_draft_version",
        resource_type="automation.durable_workflow",
        resource_id=str(workflow_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"version_number": version_row.version_number},
    )
    return _version_to_view(version_row)


def update_draft_version(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    start_step_key: str,
    steps: list,
    trigger_type: str | None = None,
    trigger_config: dict | None = None,
) -> WorkflowVersionView:
    """In-place edit of a `draft` version only -- raises
    `AutomationValidationError` if the target is already `published`
    (module docstring's own immutability rule). Never touches
    `version_number`/`workflow_id`/`created_by_user_id`."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="update")
    trigger_config = trigger_config or {}
    _validate_trigger(trigger_type, trigger_config)
    validate_workflow_definition(start_step_key, steps)

    with tenant_session_scope(tenant_id) as session:
        version_row = session.get(WorkflowVersion, version_id)
        if (
            version_row is None
            or version_row.tenant_id != tenant_id
            or version_row.workflow_id != workflow_id
        ):
            raise AutomationReferenceNotFoundError("workflow_version", version_id)
        if version_row.status != VERSION_STATUS_DRAFT:
            raise AutomationValidationError(
                "a published workflow version is immutable -- create a new draft version "
                "instead (create_draft_version())."
            )
        version_row.trigger_type = trigger_type
        version_row.trigger_config = trigger_config
        version_row.start_step_key = start_step_key
        version_row.steps = steps
        session.flush()
        session.refresh(version_row)
        session.expunge(version_row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_workflow.update_draft_version",
        resource_type="automation.durable_workflow",
        resource_id=str(workflow_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"version_number": version_row.version_number},
    )
    return _version_to_view(version_row)


def publish_version(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_id: uuid.UUID
) -> WorkflowVersionView:
    """Freezes a `draft` version to `published` (permanent, one-way) and
    points `Workflow.current_published_version_id` at it -- the only
    version new runs (`runs.py::start_run()`) may execute going forward.
    Does not affect any `Run` already referencing an older
    `workflow_version_id` (module docstring's own "deleting/archiving a
    workflow must not invalidate historical runs" -- the same logic
    applies to superseding a version)."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="update")
    published_metadata: dict[str, object] = {}
    with tenant_session_scope(tenant_id) as session:
        version_row = session.get(WorkflowVersion, version_id)
        if (
            version_row is None
            or version_row.tenant_id != tenant_id
            or version_row.workflow_id != workflow_id
        ):
            raise AutomationReferenceNotFoundError("workflow_version", version_id)
        if version_row.status == VERSION_STATUS_PUBLISHED:
            raise AutomationValidationError("this workflow version is already published.")
        # Re-validate at publish time too -- the DSL/action/condition
        # vocabulary this version's own `steps` was checked against at
        # draft-save time cannot have changed within one request, but
        # publishing is the point of no return, so this is checked again
        # rather than trusted from an earlier call.
        validate_workflow_definition(version_row.start_step_key, version_row.steps)

        version_row.status = VERSION_STATUS_PUBLISHED
        version_row.published_at = datetime.now(UTC)
        session.flush()

        workflow_row = session.get(Workflow, workflow_id)
        assert workflow_row is not None  # the version row above already proved it exists
        workflow_row.current_published_version_id = version_row.id
        session.flush()
        session.refresh(version_row)
        session.expunge(version_row)
        published_metadata = {"version_number": version_row.version_number}
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="automation.durable_workflow.publish_version",
        resource_type="automation.durable_workflow",
        resource_id=str(workflow_id),
        outcome=AuditOutcome.SUCCESS,
        metadata=published_metadata,
    )
    return _version_to_view(version_row)


def set_workflow_status(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, workflow_id: uuid.UUID, *, status: str
) -> WorkflowView:
    """Enable/disable -- a disabled workflow's own event-trigger adapter
    (`triggers.py`) never queues a new run for it, and
    `runs.py::start_run()` refuses a manual start too. Mirrors
    `product/automation/workflows.py::set_workflow_status()`'s identical
    "pause without affecting the rest of the platform" rollback
    contract, extended to durable workflows. Already-running/waiting
    runs are unaffected -- disabling stops *future* runs, never an
    in-flight one (use `runs.py::cancel_run()` for that, explicitly)."""
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="update")
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
        action="automation.durable_workflow.set_status",
        resource_type="automation.durable_workflow",
        resource_id=str(workflow_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"status": status},
    )
    return _workflow_to_view(row)


def get_workflow(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, workflow_id: uuid.UUID
) -> WorkflowView:
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Workflow, workflow_id)
        if row is None or row.tenant_id != tenant_id:
            raise AutomationReferenceNotFoundError("workflow", workflow_id)
        session.expunge(row)
    return _workflow_to_view(row)


def list_workflows(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[WorkflowView]:
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="read")
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
    return [_workflow_to_view(row) for row in rows]


def get_version(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_id: uuid.UUID
) -> WorkflowVersionView:
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(WorkflowVersion, version_id)
        if row is None or row.tenant_id != tenant_id or row.workflow_id != workflow_id:
            raise AutomationReferenceNotFoundError("workflow_version", version_id)
        session.expunge(row)
    return _version_to_view(row)


def list_versions(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[WorkflowVersionView]:
    require(actor_user_id, tenant_id, resource=DURABLE_WORKFLOW_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(WorkflowVersion)
                .where(
                    WorkflowVersion.tenant_id == tenant_id,
                    WorkflowVersion.workflow_id == workflow_id,
                )
                .order_by(WorkflowVersion.version_number.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_version_to_view(row) for row in rows]


__all__ = [
    "VALID_DURABLE_TRIGGER_TYPES",
    "WorkflowVersionView",
    "WorkflowView",
    "create_draft_version",
    "create_workflow",
    "get_version",
    "get_workflow",
    "list_versions",
    "list_workflows",
    "publish_version",
    "set_workflow_status",
    "update_draft_version",
]
