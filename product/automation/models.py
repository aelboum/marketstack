"""ORM models for the `automation` schema (docs/ROADMAP.md Phase 10.2).

**Single-step only** -- `Workflow` carries exactly one `action_type`/
`action_config` pair, not a child table of ordered steps. Phase 10.3
(multi-step/branching) is explicitly deferred (`docs/ADR/0007-automation-execution-substrate.md`);
adding a steps table now, before any multi-step engine exists to drive
it, would be exactly the speculative table-building this codebase's own
convention (every other phase) avoids.

**Bounded JSON, never unbounded blobs** -- `trigger_config`/`conditions`/
`action_config` each carry an application-layer size bound
(`product/automation/workflows.py::MAX_CONFIG_JSON_CHARS`), checked
before insert. Never a secret, credential, or arbitrary code -- see
`product/automation/actions.py`'s own module docstring for the closed,
enum-like `action_type` vocabulary this validates against.

**`WorkflowRun` is the idempotency/audit ledger** --
`UniqueConstraint(tenant_id, workflow_id, trigger_dedup_key)` is the real,
database-enforced guard against double-executing the same logical trigger
occurrence for the same workflow, mirroring `product/telephony/models.py
::CallEvent`'s identical `UniqueConstraint`-as-idempotency-backbone
discipline exactly. `product/automation/dispatcher.py::_record_run()`
reserves the row as `pending` *before* the action runs, then finalizes it
to `success`/`failed` afterward (mirrors `core.idempotency`'s own
begin/finalize two-step shape for an operation with an external call in
the middle) -- a duplicate reservation attempt's `IntegrityError` is
treated as "already executed/reserved, skip," never a "check then
insert" as its own guarantee.

**`created_by_user_id` is the load-bearing privilege-boundary field** --
every action execution re-authorizes as this user, at execution time, via
the underlying CRM function's own `require()` call
(`docs/ADR/0008-automation-depends-on-crm.md`'s own point 2) -- never a
workflow-level permission of its own that could outlive or exceed the
creator's real, current access.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import (
    JSON,
    Base,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Mapped,
    String,
    UniqueConstraint,
    mapped_column,
    now,
)

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
VALID_WORKFLOW_STATUSES = (STATUS_ACTIVE, STATUS_PAUSED)

RUN_STATUS_PENDING = "pending"
RUN_STATUS_SUCCESS = "success"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_SKIPPED = "skipped"
VALID_RUN_STATUSES = (RUN_STATUS_PENDING, RUN_STATUS_SUCCESS, RUN_STATUS_FAILED, RUN_STATUS_SKIPPED)

MAX_NAME_LENGTH = 255
MAX_TYPE_LENGTH = 64
MAX_DEDUP_KEY_LENGTH = 255
MAX_ERROR_LENGTH = 2000


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_automation_workflows_tenant_id_id"),
        Index("ix_automation_workflows_tenant_id", "tenant_id"),
        Index("ix_automation_workflows_trigger_type", "trigger_type"),
        {"schema": "automation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(MAX_TYPE_LENGTH), nullable=False)
    trigger_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    action_type: Mapped[str] = mapped_column(String(MAX_TYPE_LENGTH), nullable=False)
    action_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_ACTIVE)
    # Plain FK into the global core.users registry -- not composite,
    # mirroring every other "assignee/owner" field in this codebase
    # (Calendar.owner_user_id, PhoneNumberRoutingTarget.user_id).
    # Validated as a real reachable membership at the service layer
    # (product/automation/workflows.py), not by this FK alone.
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_automation_workflow_runs_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "trigger_dedup_key",
            name="uq_automation_workflow_runs_tenant_workflow_dedup",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["automation.workflows.tenant_id", "automation.workflows.id"],
            name="fk_automation_workflow_runs_tenant_workflow",
            ondelete="CASCADE",
        ),
        Index("ix_automation_workflow_runs_tenant_id", "tenant_id"),
        Index("ix_automation_workflow_runs_workflow_id", "workflow_id"),
        {"schema": "automation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trigger_dedup_key: Mapped[str] = mapped_column(String(MAX_DEDUP_KEY_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(String(MAX_ERROR_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
