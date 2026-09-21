import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import {
  ACTION_TYPES,
  TRIGGER_TYPES,
  cancelRun,
  createDraftVersion,
  createWorkflow,
  getRun,
  getVersion,
  getWorkflow,
  listRunSteps,
  listRuns,
  listVersions,
  listWorkflows,
  publishVersion,
  setWorkflowStatus,
  startRun,
  updateDraftVersion,
} from "./automation";

describe("automation API functions -- exact request shape sent to the real durable routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("ACTION_TYPES never includes the real, backend-registered ai.crm.qualify_lead", () => {
    expect(ACTION_TYPES).toEqual([
      "create_task",
      "update_contact",
      "move_opportunity",
      "send_email",
      "send_webhook",
    ]);
    expect(ACTION_TYPES).not.toContain("ai.crm.qualify_lead");
  });

  it("TRIGGER_TYPES is exactly the four real dispatcher event types", () => {
    expect(TRIGGER_TYPES).toEqual([
      "crm.contact.created",
      "appointments.appointment.booked",
      "telephony.call.completed",
      "crm.opportunity.stage_changed",
    ]);
  });

  it("listWorkflows() -> GET with limit/offset only (no filter exists on this endpoint)", async () => {
    requestMock.mockResolvedValue([{ id: "1" }]);
    const result = await listWorkflows("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/automation/durable/tenants/t1/workflows", {
      query: { limit: 25, offset: 0 },
    });
    expect(result.hasMore).toBe(false);
  });

  it("getWorkflow() -> GET /workflows/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getWorkflow("t1", "w1");
    expect(requestMock).toHaveBeenCalledWith("/v1/automation/durable/tenants/t1/workflows/w1");
  });

  it("createWorkflow() -> POST with name/start_step_key/steps/trigger fields", async () => {
    requestMock.mockResolvedValue({ workflow: {}, version: {} });
    await createWorkflow("t1", {
      name: "Welcome",
      start_step_key: "action",
      steps: [{ step_key: "action", type: "action", action_type: "create_task", action_config: {}, next_step_key: null }],
      trigger_type: "crm.contact.created",
    });
    expect(requestMock).toHaveBeenCalledWith("/v1/automation/durable/tenants/t1/workflows", {
      method: "POST",
      body: {
        name: "Welcome",
        start_step_key: "action",
        steps: [{ step_key: "action", type: "action", action_type: "create_task", action_config: {}, next_step_key: null }],
        trigger_type: "crm.contact.created",
      },
    });
  });

  it("setWorkflowStatus() -> PATCH .../status with status", async () => {
    requestMock.mockResolvedValue({});
    await setWorkflowStatus("t1", "w1", "active");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/workflows/w1/status",
      { method: "PATCH", body: { status: "active" } },
    );
  });

  it("listVersions() -> GET with limit/offset", async () => {
    requestMock.mockResolvedValue([]);
    await listVersions("t1", "w1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/workflows/w1/versions",
      { query: { limit: 25, offset: 0 } },
    );
  });

  it("getVersion() -> GET /versions/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getVersion("t1", "w1", "v1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/workflows/w1/versions/v1",
    );
  });

  it("createDraftVersion() -> POST .../versions", async () => {
    requestMock.mockResolvedValue({});
    const input = { start_step_key: "action", steps: [], trigger_type: null };
    await createDraftVersion("t1", "w1", input);
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/workflows/w1/versions",
      { method: "POST", body: input },
    );
  });

  it("updateDraftVersion() -> PUT .../versions/{id}", async () => {
    requestMock.mockResolvedValue({});
    const input = { start_step_key: "action", steps: [], trigger_type: null };
    await updateDraftVersion("t1", "w1", "v1", input);
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/workflows/w1/versions/v1",
      { method: "PUT", body: input },
    );
  });

  it("publishVersion() -> POST .../versions/{id}/publish, no body", async () => {
    requestMock.mockResolvedValue({});
    await publishVersion("t1", "w1", "v1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/workflows/w1/versions/v1/publish",
      { method: "POST" },
    );
  });

  it("listRuns() -> GET .../workflows/{id}/runs with limit/offset", async () => {
    requestMock.mockResolvedValue([]);
    await listRuns("t1", "w1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/workflows/w1/runs",
      { query: { limit: 25, offset: 0 } },
    );
  });

  it("startRun() -> POST .../runs", async () => {
    requestMock.mockResolvedValue({});
    await startRun("t1", "w1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/workflows/w1/runs",
      { method: "POST", body: {} },
    );
  });

  it("getRun() -> GET .../tenants/{t}/runs/{id} (not nested under a workflow)", async () => {
    requestMock.mockResolvedValue({});
    await getRun("t1", "r1");
    expect(requestMock).toHaveBeenCalledWith("/v1/automation/durable/tenants/t1/runs/r1");
  });

  it("listRunSteps() -> GET .../runs/{id}/steps, unpaginated (no query object)", async () => {
    requestMock.mockResolvedValue([]);
    await listRunSteps("t1", "r1");
    expect(requestMock).toHaveBeenCalledWith("/v1/automation/durable/tenants/t1/runs/r1/steps");
  });

  it("cancelRun() -> POST .../runs/{id}/cancel", async () => {
    requestMock.mockResolvedValue({});
    await cancelRun("t1", "r1", { reason: "no longer needed" });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/automation/durable/tenants/t1/runs/r1/cancel",
      { method: "POST", body: { reason: "no longer needed" } },
    );
  });
});
