import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { PipelineWidget } from "./PipelineWidget";

const { loadPipelineSummaryMock } = vi.hoisted(() => ({ loadPipelineSummaryMock: vi.fn() }));

vi.mock("@/lib/dashboard/commandCenter", () => ({
  loadPipelineSummary: loadPipelineSummaryMock,
}));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("PipelineWidget", () => {
  it("shows a loading state while the pipeline summary loads", () => {
    loadPipelineSummaryMock.mockReturnValue(new Promise(() => {}));

    render(<PipelineWidget tenantId="t1" />);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows an empty state when the tenant has no pipeline yet -- not a fabricated table", async () => {
    loadPipelineSummaryMock.mockResolvedValue(null);

    render(<PipelineWidget tenantId="t1" />);

    expect(await screen.findByText("Nog geen pijplijn")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders real per-stage deal counts and values through the shared DataTable", async () => {
    loadPipelineSummaryMock.mockResolvedValue({
      pipelineName: "Sales",
      currency: "EUR",
      stages: [
        { stageId: "s1", stageName: "New", isWon: false, isLost: false, dealCount: 3, valueDecimal: 900 },
        { stageId: "s2", stageName: "Won", isWon: true, isLost: false, dealCount: 1, valueDecimal: 500 },
      ],
      openCount: 3,
      openValueDecimal: 900,
    });

    render(<PipelineWidget tenantId="t1" />);

    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Fase" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Deals" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Waarde" })).toBeInTheDocument();
    expect(within(table).getByText("New")).toBeInTheDocument();
    expect(within(table).getByText("900.00 EUR")).toBeInTheDocument();
    expect(within(table).getByText("Won")).toBeInTheDocument();
    expect(within(table).getByText("500.00 EUR")).toBeInTheDocument();
  });

  it("shows '—' for a stage with no priced opportunities, never a fabricated value", async () => {
    loadPipelineSummaryMock.mockResolvedValue({
      pipelineName: "Sales",
      currency: null,
      stages: [
        { stageId: "s1", stageName: "New", isWon: false, isLost: false, dealCount: 2, valueDecimal: null },
      ],
      openCount: 2,
      openValueDecimal: null,
    });

    render(<PipelineWidget tenantId="t1" />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("—")).toBeInTheDocument();
  });

  it("shows a retryable error state when loading the pipeline summary fails", async () => {
    const { ApiError } = await import("@/lib/api/errors");
    loadPipelineSummaryMock.mockRejectedValue(
      new ApiError("network", "Could not reach the Product backend."),
    );

    render(<PipelineWidget tenantId="t1" />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Could not reach the Product backend.")).toBeInTheDocument();
  });
});
