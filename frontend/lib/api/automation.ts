// Typed API functions for the Phase 10.3 durable Automation backend
// (`product/automation/durable/routes.py`, mounted at
// `/v1/automation/durable`), built on the UI-1 `request()` foundation --
// UI-10 adds no second HTTP client.
//
// **Two workflow engines exist in the backend and are NOT the same
// resource.** `product/automation/routes.py` (`/v1/automation`, Phase
// 10.2) is a flat, single-action, non-versioned engine with no
// step-level run detail. `product/automation/durable/routes.py`
// (`/v1/automation/durable`, Phase 10.3) is versioned and Temporal-
// backed, with real per-step run detail (status/timing/error per step).
// This client deliberately talks to the durable engine only: UI-10's
// own spec requires distinguishing "successful / failed / skipped /
// pending / running steps" in run detail, and only the durable engine's
// `RunStep` rows carry that. A workflow created here does not exist in,
// and cannot be seen through, the flat `/v1/automation` router -- they
// do not share ids. That router is simply not consumed by this UI.
//
// **This UI creates and edits single-action workflows only.** The
// durable engine's `steps` field is a genuine step DAG (`action` /
// `condition` / `delay` / `wait_for_event` node types, up to 20 steps,
// arbitrary branching -- see `product/automation/durable/dsl.py`).
// Building every one of those into this phase would be a second,
// larger feature; UI-10 always writes exactly one `action`-type step
// (`start_step_key` pointing at it, `next_step_key: null`) and only
// renders that shape back. A workflow with a richer step graph --
// impossible to create from this UI, but not impossible to encounter,
// since the same tenant may have workflows built directly against the
// API -- shows its later steps by id only rather than inventing a
// rendering for step types this phase does not build.
//
// **`ai.crm.qualify_lead` is a real, registered action as of this
// phase's backend (`product/action_registry_composition.py
// ::wire_production_automation_actions()` wires it into every running
// instance).** UI-10 is explicitly scoped to the five non-AI actions
// only -- `ACTION_TYPES` below deliberately omits it. The backend will
// still accept it if sent, so its absence here is a frontend policy,
// not a backend limitation; the AI automation UI is a later phase's
// scope.
//
// Deliberately absent, because the backend has none:
//   - no filter/search param on any list endpoint here (workflows,
//     versions, runs) -- `limit`/`offset` only, verified against every
//     route in `durable/routes.py`;
//   - no retry/attempt history: `RunStep` carries no retry count or
//     attempt log -- that state lives only inside Temporal, per
//     `durable/models.py`'s own docstring, and is not part of this
//     product's API surface;
//   - no way to edit a *published* version's steps directly -- only a
//     draft version is mutable (`PUT .../versions/{id}`); changing a
//     published workflow means creating a new draft, then publishing it.

import { request } from "@/lib/api/client";

export type TriggerType =
  | "crm.contact.created"
  | "appointments.appointment.booked"
  | "telephony.call.completed"
  | "crm.opportunity.stage_changed";

/** The four trigger event types the durable dispatcher actually
 * matches (`product/automation/dispatcher.py::TRIGGER_EVENT_TYPES`).
 * Unlike the flat engine, the durable engine has no `"scheduled"`
 * trigger type. */
export const TRIGGER_TYPES: TriggerType[] = [
  "crm.contact.created",
  "appointments.appointment.booked",
  "telephony.call.completed",
  "crm.opportunity.stage_changed",
];

/** The five non-AI actions this phase builds forms for. Deliberately
 * excludes the real, backend-registered `"ai.crm.qualify_lead"` -- see
 * this module's own docstring. */
export type ActionType =
  | "create_task"
  | "update_contact"
  | "move_opportunity"
  | "send_email"
  | "send_webhook";

export const ACTION_TYPES: ActionType[] = [
  "create_task",
  "update_contact",
  "move_opportunity",
  "send_email",
  "send_webhook",
];

/** `product/automation/actions.py::MAX_ACTION_CONFIG_STRING_CHARS`. */
export const MAX_ACTION_CONFIG_STRING_CHARS = 4000;

export type WorkflowStatus = "active" | "paused";
export type VersionStatus = "draft" | "published";
export type RunStatus = "queued" | "running" | "waiting" | "completed" | "failed" | "cancelled";
export type StepRunStatus = "running" | "succeeded" | "failed" | "skipped";

/** The only step shape this UI ever writes or renders in full -- a
 * single terminal action node. See module docstring. */
export type ActionStep = {
  step_key: string;
  type: "action";
  action_type: ActionType;
  action_config: Record<string, string>;
  next_step_key: null;
};

/** A step this UI did not create (a condition/delay/wait_for_event node,
 * or an action step from a richer graph). Rendered by id only -- never
 * reconstructed into a fake `ActionStep`. */
export type UnknownStep = {
  step_key: string;
  type: string;
  [key: string]: unknown;
};

export type WorkflowStep = ActionStep | UnknownStep;

export type Workflow = {
  id: string;
  tenant_id: string;
  name: string;
  status: WorkflowStatus;
  current_published_version_id: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
};

export type WorkflowVersion = {
  id: string;
  tenant_id: string;
  workflow_id: string;
  version_number: number;
  status: VersionStatus;
  trigger_type: TriggerType | null;
  trigger_config: Record<string, unknown>;
  start_step_key: string;
  steps: WorkflowStep[];
  created_by_user_id: string;
  created_at: string;
  published_at: string | null;
};

export type Run = {
  id: string;
  tenant_id: string;
  workflow_id: string;
  workflow_version_id: string;
  status: RunStatus;
  actor_user_id: string;
  temporal_workflow_id: string | null;
  current_step_key: string | null;
  waiting_for_event_type: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type RunStep = {
  id: string;
  run_id: string;
  step_key: string;
  step_type: string;
  status: StepRunStatus;
  error: string | null;
  started_at: string;
  completed_at: string | null;
};

export type Page<T> = {
  results: T[];
  /** Heuristic only (`results.length === limit`) -- every list endpoint
   * here returns a plain array, never a total count. */
  hasMore: boolean;
};

function toPage<T>(results: T[], limit: number): Page<T> {
  return { results, hasMore: results.length === limit };
}

/** `product/automation/pagination.py::DEFAULT_PAGE_SIZE`. */
const DEFAULT_LIMIT = 25;

// --- Workflows ---------------------------------------------------------

export function listWorkflows(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Workflow>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<Workflow[]>(`/v1/automation/durable/tenants/${tenantId}/workflows`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getWorkflow(tenantId: string, workflowId: string): Promise<Workflow> {
  return request<Workflow>(`/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}`);
}

export type CreateWorkflowInput = {
  name: string;
  start_step_key: string;
  steps: WorkflowStep[];
  trigger_type?: TriggerType | null;
  trigger_config?: Record<string, unknown>;
};

export function createWorkflow(
  tenantId: string,
  input: CreateWorkflowInput,
): Promise<{ workflow: Workflow; version: WorkflowVersion }> {
  return request<{ workflow: Workflow; version: WorkflowVersion }>(
    `/v1/automation/durable/tenants/${tenantId}/workflows`,
    { method: "POST", body: input },
  );
}

export function setWorkflowStatus(
  tenantId: string,
  workflowId: string,
  workflowStatus: WorkflowStatus,
): Promise<Workflow> {
  return request<Workflow>(
    `/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}/status`,
    { method: "PATCH", body: { status: workflowStatus } },
  );
}

// --- Versions ------------------------------------------------------------

export function listVersions(
  tenantId: string,
  workflowId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<WorkflowVersion>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<WorkflowVersion[]>(
    `/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}/versions`,
    { query: { limit, offset: params.offset ?? 0 } },
  ).then((results) => toPage(results, limit));
}

export function getVersion(
  tenantId: string,
  workflowId: string,
  versionId: string,
): Promise<WorkflowVersion> {
  return request<WorkflowVersion>(
    `/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}/versions/${versionId}`,
  );
}

export type DraftVersionInput = {
  start_step_key: string;
  steps: WorkflowStep[];
  trigger_type?: TriggerType | null;
  trigger_config?: Record<string, unknown>;
};

/** Creates a new draft version -- the only way to change a workflow
 * whose current version is already published. */
export function createDraftVersion(
  tenantId: string,
  workflowId: string,
  input: DraftVersionInput,
): Promise<WorkflowVersion> {
  return request<WorkflowVersion>(
    `/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}/versions`,
    { method: "POST", body: input },
  );
}

/** Overwrites a version that is still a draft. The backend refuses this
 * once the version is published (a `AutomationValidationError` -> 400). */
export function updateDraftVersion(
  tenantId: string,
  workflowId: string,
  versionId: string,
  input: DraftVersionInput,
): Promise<WorkflowVersion> {
  return request<WorkflowVersion>(
    `/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}/versions/${versionId}`,
    { method: "PUT", body: input },
  );
}

export function publishVersion(
  tenantId: string,
  workflowId: string,
  versionId: string,
): Promise<WorkflowVersion> {
  return request<WorkflowVersion>(
    `/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}/versions/${versionId}/publish`,
    { method: "POST" },
  );
}

// --- Runs ----------------------------------------------------------------

export function listRuns(
  tenantId: string,
  workflowId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Run>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<Run[]>(
    `/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}/runs`,
    { query: { limit, offset: params.offset ?? 0 } },
  ).then((results) => toPage(results, limit));
}

export function startRun(
  tenantId: string,
  workflowId: string,
  input: { context?: Record<string, unknown>; idempotency_key?: string | null } = {},
): Promise<Run> {
  return request<Run>(`/v1/automation/durable/tenants/${tenantId}/workflows/${workflowId}/runs`, {
    method: "POST",
    body: input,
  });
}

export function getRun(tenantId: string, runId: string): Promise<Run> {
  return request<Run>(`/v1/automation/durable/tenants/${tenantId}/runs/${runId}`);
}

/** Not paginated on the backend -- `list_run_steps` returns every step
 * for the run (`durable/routes.py`'s own route has no `limit`/`offset`). */
export function listRunSteps(tenantId: string, runId: string): Promise<RunStep[]> {
  return request<RunStep[]>(`/v1/automation/durable/tenants/${tenantId}/runs/${runId}/steps`);
}

export function cancelRun(
  tenantId: string,
  runId: string,
  input: { reason?: string } = {},
): Promise<Run> {
  return request<Run>(`/v1/automation/durable/tenants/${tenantId}/runs/${runId}/cancel`, {
    method: "POST",
    body: input,
  });
}
