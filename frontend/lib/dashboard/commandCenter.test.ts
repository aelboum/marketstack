import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listPipelinesMock,
  listStagesMock,
  listOpportunitiesMock,
  listContactsMock,
  listAppointmentsMock,
  listInboxMock,
  listRunsMock,
  listWorkflowsMock,
} = vi.hoisted(() => ({
  listPipelinesMock: vi.fn(),
  listStagesMock: vi.fn(),
  listOpportunitiesMock: vi.fn(),
  listContactsMock: vi.fn(),
  listAppointmentsMock: vi.fn(),
  listInboxMock: vi.fn(),
  listRunsMock: vi.fn(),
  listWorkflowsMock: vi.fn(),
}));

vi.mock("@/lib/api/crm", () => ({
  listPipelines: listPipelinesMock,
  listStages: listStagesMock,
  listOpportunities: listOpportunitiesMock,
  listContacts: listContactsMock,
}));

vi.mock("@/lib/api/appointments", () => ({
  listAppointments: listAppointmentsMock,
}));

vi.mock("@/lib/api/conversations", () => ({
  listInbox: listInboxMock,
}));

vi.mock("@/lib/api/automation", () => ({
  listRuns: listRunsMock,
  listWorkflows: listWorkflowsMock,
}));

import { loadDashboardKpis, loadPipelineSummary } from "./commandCenter";

function opportunity(overrides: Partial<Record<string, unknown>>) {
  return {
    id: "o",
    tenant_id: "t1",
    name: "Deal",
    contact_id: null,
    company_id: null,
    pipeline_id: "p1",
    stage_id: "s1",
    assigned_user_id: null,
    amount: null,
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

describe("loadPipelineSummary", () => {
  beforeEach(() => {
    listPipelinesMock.mockReset();
    listStagesMock.mockReset();
    listOpportunitiesMock.mockReset();
  });

  it("returns null when the tenant has no pipeline yet -- a real empty state, not an error", async () => {
    listPipelinesMock.mockResolvedValue([]);

    const summary = await loadPipelineSummary("t1");

    expect(summary).toBeNull();
    expect(listStagesMock).not.toHaveBeenCalled();
  });

  it("uses the default pipeline, sums same-currency amounts per stage, and separates open from won", async () => {
    listPipelinesMock.mockResolvedValue([
      { id: "p-other", tenant_id: "t1", name: "Other", is_default: false, created_at: "" },
      { id: "p1", tenant_id: "t1", name: "Sales", is_default: true, created_at: "" },
    ]);
    listStagesMock.mockResolvedValue([
      { id: "s2", pipeline_id: "p1", name: "Won", position: 1, is_won: true, is_lost: false },
      { id: "s1", pipeline_id: "p1", name: "New", position: 0, is_won: false, is_lost: false },
    ]);
    listOpportunitiesMock.mockResolvedValue({
      results: [
        opportunity({ id: "o1", stage_id: "s1", amount: "100.00 EUR" }),
        opportunity({ id: "o2", stage_id: "s1", amount: "50.00 EUR" }),
        opportunity({ id: "o3", stage_id: "s2", amount: "500.00 EUR" }),
        opportunity({ id: "o4", pipeline_id: "p-other", stage_id: "s1", amount: "999.00 EUR" }),
      ],
      hasMore: false,
    });

    const summary = await loadPipelineSummary("t1");

    expect(listStagesMock).toHaveBeenCalledWith("t1", "p1");
    expect(summary?.pipelineName).toBe("Sales");
    expect(summary?.currency).toBe("EUR");
    // Stage order follows `position`, not the order stages were returned in.
    expect(summary?.stages.map((s) => s.stageName)).toEqual(["New", "Won"]);
    expect(summary?.stages[0]).toMatchObject({ dealCount: 2, valueDecimal: 150 });
    expect(summary?.stages[1]).toMatchObject({ dealCount: 1, valueDecimal: 500 });
    // The other pipeline's deal never counts toward this summary.
    expect(summary?.openCount).toBe(2);
    expect(summary?.openValueDecimal).toBe(150);
  });

  it("excludes a mismatched-currency amount from the sum, but still counts the deal", async () => {
    listPipelinesMock.mockResolvedValue([{ id: "p1", tenant_id: "t1", name: "Sales", is_default: true, created_at: "" }]);
    listStagesMock.mockResolvedValue([
      { id: "s1", pipeline_id: "p1", name: "New", position: 0, is_won: false, is_lost: false },
    ]);
    listOpportunitiesMock.mockResolvedValue({
      results: [
        opportunity({ id: "o1", amount: "100.00 EUR" }),
        opportunity({ id: "o2", amount: "80.00 USD" }),
      ],
      hasMore: false,
    });

    const summary = await loadPipelineSummary("t1");

    expect(summary?.currency).toBe("EUR");
    expect(summary?.stages[0].dealCount).toBe(2);
    expect(summary?.stages[0].valueDecimal).toBe(100);
  });

  it("reports a null value for a stage with no priced opportunities -- never a fabricated 0", async () => {
    listPipelinesMock.mockResolvedValue([{ id: "p1", tenant_id: "t1", name: "Sales", is_default: true, created_at: "" }]);
    listStagesMock.mockResolvedValue([
      { id: "s1", pipeline_id: "p1", name: "New", position: 0, is_won: false, is_lost: false },
    ]);
    listOpportunitiesMock.mockResolvedValue({
      results: [opportunity({ id: "o1", amount: null })],
      hasMore: false,
    });

    const summary = await loadPipelineSummary("t1");

    expect(summary?.currency).toBeNull();
    expect(summary?.stages[0].valueDecimal).toBeNull();
  });
});

describe("loadDashboardKpis", () => {
  beforeEach(() => {
    listPipelinesMock.mockReset();
    listStagesMock.mockReset();
    listOpportunitiesMock.mockReset();
    listAppointmentsMock.mockReset();
    listInboxMock.mockReset();
  });

  it("composes real pipeline, appointment, and inbox data into one KPI set", async () => {
    listPipelinesMock.mockResolvedValue([{ id: "p1", tenant_id: "t1", name: "Sales", is_default: true, created_at: "" }]);
    listStagesMock.mockResolvedValue([
      { id: "s1", pipeline_id: "p1", name: "New", position: 0, is_won: false, is_lost: false },
    ]);
    listOpportunitiesMock.mockResolvedValue({
      results: [opportunity({ id: "o1", amount: "250.00 USD" })],
      hasMore: false,
    });
    listAppointmentsMock.mockResolvedValue({ results: [{ id: "a1" }, { id: "a2" }], hasMore: false });
    listInboxMock.mockResolvedValue([{ thread_id: "th1" }]);

    const kpis = await loadDashboardKpis("t1");

    expect(kpis).toEqual({
      openOpportunities: 1,
      pipelineValueDecimal: 250,
      pipelineCurrency: "USD",
      appointmentsToday: 2,
      unreadConversations: 1,
    });
    expect(listInboxMock).toHaveBeenCalledWith("t1", { needs_reply: true });
  });

  it("reports null pipeline KPIs -- never a fabricated zero -- when there is no pipeline yet", async () => {
    listPipelinesMock.mockResolvedValue([]);
    listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
    listInboxMock.mockResolvedValue([]);

    const kpis = await loadDashboardKpis("t1");

    expect(kpis.openOpportunities).toBeNull();
    expect(kpis.pipelineValueDecimal).toBeNull();
    expect(kpis.pipelineCurrency).toBeNull();
    expect(kpis.appointmentsToday).toBe(0);
    expect(kpis.unreadConversations).toBe(0);
  });
});
