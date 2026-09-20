"""ORM models for the production Phase 10.3 durable-workflow domain
(docs/ROADMAP.md Phase 10.3; docs/ADR/0007-automation-execution-substrate.md's
own "Phase 10.3 Production Implementation" section).

**Product PostgreSQL is the source of truth for business definitions and
business run state -- Temporal's own history is execution infrastructure
state, never duplicated here.** Concretely: this module has no table for
step *retries*, *timers*, *replay history*, or serialized activity
payloads -- those live only in Temporal. What lives here is coarse,
business-meaningful state: what a workflow *is* (`Workflow`), what a
published version *locked in* (`WorkflowVersion`), that a run happened
and its outcome (`Run`), and a business-level ledger of which step did
what (`RunStep`) -- the same "WorkflowRun is the idempotency/audit
ledger, never a mirror of infra.jobs" discipline
`product/automation/models.py` already established for 10.2, extended
here to a durable, multi-step run.

**Versioned, immutable-once-published identity** -- `Workflow` is the
stable identity (a name, an enabled/disabled switch, which version is
currently published). `WorkflowVersion` is a append-only, versioned
snapshot of the actual step graph: `status` moves `draft -> published`
exactly once (`VALID_VERSION_STATUSES`), and no code path in
`product/automation/durable/definitions.py` ever mutates a version's
`steps`/`trigger_type`/`trigger_config`/`start_step_key` after
`status == published` -- editing requires creating a new version, never
patching an existing one (this phase's own explicit "a published version
must be immutable" / "new changes create a new version" requirement).
`Run.workflow_version_id` pins the *exact* version a run executes,
forever, even after a newer version is published or the workflow is
disabled/archived (this phase's own "changing a draft must not mutate a
published version" / "deleting/archiving a workflow must not invalidate
historical runs" requirements) -- there is no code path that lets a
running execution "switch" versions mid-flight.

**Steps are bounded JSON on the version row, not a separate table** --
mirrors `product/automation/models.py::Workflow.trigger_config`/
`conditions`/`action_config`'s own established "bounded JSON, never
unbounded blobs, never a separate table for small structured data"
convention exactly. A version's `steps` is a JSON list of step
dictionaries (validated by `product/automation/durable/dsl.py` before
insert), addressed by `step_key` -- ordered by list position, referenced
by `next_step_key`/`next_step_key_true`/`next_step_key_false`/
`timeout_step_key`, not by primary key. Keeping the whole graph as one
JSON value on the version row (rather than exploding it into a child
table) is also what makes "immutable once published" a single-row
guarantee, not a multi-table invariant that could be split by a partial
write.

**`RunStep` is per-step *business* outcome, not Temporal replay
history** -- one row per step actually entered by a run (status,
bounded error text, timestamps), the mechanism behind this phase's own
required audit events ("step started"/"step completed"/"step failed")
and the "step execution state" business state requirement. It never
stores an activity's raw input/output payload or a retry-attempt count
-- that is exactly the class of data this phase's own "do not duplicate
Temporal's entire execution history in Product PostgreSQL" instruction
exists to keep out of this schema.
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
    Integer,
    Mapped,
    String,
    UniqueConstraint,
    mapped_column,
    now,
)

# --- Workflow (stable identity) --------------------------------------------

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
VALID_WORKFLOW_STATUSES = (STATUS_ACTIVE, STATUS_PAUSED)

MAX_NAME_LENGTH = 255


class Workflow(Base):
    __tablename__ = "durable_workflows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_automation_durable_workflows_tenant_id_id"),
        Index("ix_automation_durable_workflows_tenant_id", "tenant_id"),
        {"schema": "automation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_ACTIVE)
    # Nullable: a brand-new workflow has no published version yet (its
    # only version is still `draft`). Not a composite FK against
    # `WorkflowVersion` on purpose -- a composite FK here would create a
    # circular table dependency (WorkflowVersion already composite-FKs
    # back to Workflow via workflow_id); validated at the service layer
    # (`definitions.py::publish_version()`) instead, mirroring
    # `product/automation/models.py::Workflow.created_by_user_id`'s own
    # "validated at the service layer, not by the FK alone" precedent.
    current_published_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


# --- WorkflowVersion (immutable once published) -----------------------------

VERSION_STATUS_DRAFT = "draft"
VERSION_STATUS_PUBLISHED = "published"
VALID_VERSION_STATUSES = (VERSION_STATUS_DRAFT, VERSION_STATUS_PUBLISHED)

MAX_STEPS_JSON_CHARS = 16_000


class WorkflowVersion(Base):
    __tablename__ = "durable_workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id", name="uq_automation_durable_workflow_versions_tenant_id_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "version_number",
            name="uq_automation_durable_workflow_versions_tenant_workflow_number",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["automation.durable_workflows.tenant_id", "automation.durable_workflows.id"],
            name="fk_automation_durable_workflow_versions_tenant_workflow",
            ondelete="CASCADE",
        ),
        Index("ix_automation_durable_workflow_versions_tenant_id", "tenant_id"),
        Index("ix_automation_durable_workflow_versions_workflow_id", "workflow_id"),
        {"schema": "automation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=VERSION_STATUS_DRAFT)
    # trigger_type == NULL means manual-start only (no event adapter
    # matches this version) -- product/automation/durable/triggers.py's
    # own docstring for the full trigger-matching contract.
    trigger_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    start_step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Bounded JSON list of step dicts -- see module docstring. Validated
    # by product/automation/durable/dsl.py before this row is ever
    # inserted or transitioned to `published`.
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Run (business execution state) -----------------------------------------

RUN_STATUS_QUEUED = "queued"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_WAITING = "waiting"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELLED = "cancelled"
VALID_RUN_STATUSES = (
    RUN_STATUS_QUEUED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_WAITING,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_CANCELLED,
)
# Terminal: no further Temporal submission/signal/cancel is ever issued
# for a run in one of these statuses (definitions.py/runs.py's own
# guard, checked before every state-changing call).
TERMINAL_RUN_STATUSES = frozenset({RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED})

MAX_DEDUP_KEY_LENGTH = 255
MAX_ERROR_LENGTH = 2000
MAX_TEMPORAL_ID_LENGTH = 255
MAX_CONTEXT_JSON_CHARS = 8_000


class Run(Base):
    __tablename__ = "durable_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_automation_durable_runs_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "trigger_dedup_key",
            name="uq_automation_durable_runs_tenant_workflow_dedup",
        ),
        UniqueConstraint(
            "tenant_id", "temporal_workflow_id", name="uq_automation_durable_runs_temporal_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["automation.durable_workflows.tenant_id", "automation.durable_workflows.id"],
            name="fk_automation_durable_runs_tenant_workflow",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_version_id"],
            [
                "automation.durable_workflow_versions.tenant_id",
                "automation.durable_workflow_versions.id",
            ],
            name="fk_automation_durable_runs_tenant_workflow_version",
        ),
        Index("ix_automation_durable_runs_tenant_id", "tenant_id"),
        Index("ix_automation_durable_runs_workflow_id", "workflow_id"),
        Index("ix_automation_durable_runs_status", "status"),
        {"schema": "automation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # The execution actor/principal context -- every business action this
    # run's activities perform re-authorizes as this user, at execution
    # time (never a cached decision) -- product/automation/durable
    # /production_workflow.py's own module docstring, mirroring
    # product/automation/models.py::Workflow.created_by_user_id's
    # identical load-bearing role for 10.2.
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.id"), nullable=False)
    trigger_dedup_key: Mapped[str] = mapped_column(String(MAX_DEDUP_KEY_LENGTH), nullable=False)
    # NULL until submit_queued_durable_runs()/start_run() actually calls
    # Temporal's own start_workflow -- product/automation/durable
    # /runs.py's own module docstring for the queued -> running handoff.
    temporal_workflow_id: Mapped[str | None] = mapped_column(
        String(MAX_TEMPORAL_ID_LENGTH), nullable=True
    )
    temporal_run_id: Mapped[str | None] = mapped_column(
        String(MAX_TEMPORAL_ID_LENGTH), nullable=True
    )
    current_step_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Set (by `record_step_started_activity`) only while `status ==
    # RUN_STATUS_WAITING`, cleared the instant the wait resolves --
    # `runs.py::signal_run()`'s own Product-side defense-in-depth check:
    # a signal is rejected before it is ever sent to Temporal at all if
    # its own `event_type` does not match this column, never trusting
    # only the workflow's own in-process `_expected_event_type` state
    # (`production_workflow.py`'s own module docstring, "Event
    # security").
    waiting_for_event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Bounded run context (trigger ids + prior action-step outputs, ids
    # and small scalars only, never a full business record) -- see
    # product/automation/durable/production_workflow.py's own module
    # docstring for exactly what is and is not allowed into this value,
    # and product/automation/durable/client.py's own "Privacy / history"
    # section (Phase 10.3 infrastructure spike) for why this same
    # discipline extends to what is passed as this workflow's own
    # Temporal input.
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(String(MAX_ERROR_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- RunStep (business-level step ledger, not Temporal history) ------------

STEP_RUN_STATUS_RUNNING = "running"
STEP_RUN_STATUS_SUCCEEDED = "succeeded"
STEP_RUN_STATUS_FAILED = "failed"
STEP_RUN_STATUS_SKIPPED = "skipped"
VALID_STEP_RUN_STATUSES = (
    STEP_RUN_STATUS_RUNNING,
    STEP_RUN_STATUS_SUCCEEDED,
    STEP_RUN_STATUS_FAILED,
    STEP_RUN_STATUS_SKIPPED,
)


class RunStep(Base):
    __tablename__ = "durable_run_steps"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_automation_durable_run_steps_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["automation.durable_runs.tenant_id", "automation.durable_runs.id"],
            name="fk_automation_durable_run_steps_tenant_run",
            ondelete="CASCADE",
        ),
        Index("ix_automation_durable_run_steps_tenant_id", "tenant_id"),
        Index("ix_automation_durable_run_steps_run_id", "run_id"),
        {"schema": "automation"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    step_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(String(MAX_ERROR_LENGTH), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
