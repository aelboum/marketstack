import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { KpiStrip } from "./KpiStrip";

const { loadDashboardKpisMock } = vi.hoisted(() => ({ loadDashboardKpisMock: vi.fn() }));

vi.mock("@/lib/dashboard/commandCenter", () => ({
  loadDashboardKpis: loadDashboardKpisMock,
}));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("KpiStrip", () => {
  it("shows a loading state while the KPIs load", () => {
    loadDashboardKpisMock.mockReturnValue(new Promise(() => {}));

    render(<KpiStrip tenantId="t1" />);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders real KPI values from the command-center layer, not a fabricated number", async () => {
    loadDashboardKpisMock.mockResolvedValue({
      openOpportunities: 4,
      pipelineValueDecimal: 2500,
      pipelineCurrency: "USD",
      appointmentsToday: 1,
      unreadConversations: 6,
    });

    render(<KpiStrip tenantId="t1" />);

    const strip = await screen.findByTestId("kpi-strip");
    expect(within(strip).getByText("Open kansen")).toBeInTheDocument();
    expect(within(strip).getByText("4")).toBeInTheDocument();
    expect(within(strip).getByText("2500.00 USD")).toBeInTheDocument();
    expect(within(strip).getByText("1")).toBeInTheDocument();
    expect(within(strip).getByText("6")).toBeInTheDocument();
    expect(loadDashboardKpisMock).toHaveBeenCalledWith("t1");
  });

  it("shows an honest '—', never a fabricated value, when a KPI has no data yet", async () => {
    loadDashboardKpisMock.mockResolvedValue({
      openOpportunities: null,
      pipelineValueDecimal: null,
      pipelineCurrency: null,
      appointmentsToday: 0,
      unreadConversations: 0,
    });

    render(<KpiStrip tenantId="t1" />);

    const strip = await screen.findByTestId("kpi-strip");
    // openOpportunities and pipelineValueDecimal are both genuinely
    // unknown -- appointmentsToday/unreadConversations are real zero
    // counts, not "unknown," so they render "0", never "—".
    expect(within(strip).getAllByText("—")).toHaveLength(2);
    expect(within(strip).getAllByText("0")).toHaveLength(2);
  });

  it("shows a retryable error state when loading the KPIs fails", async () => {
    const { ApiError } = await import("@/lib/api/errors");
    loadDashboardKpisMock.mockRejectedValue(
      new ApiError("network", "Could not reach the Product backend."),
    );

    render(<KpiStrip tenantId="t1" />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Could not reach the Product backend.")).toBeInTheDocument();
  });
});
