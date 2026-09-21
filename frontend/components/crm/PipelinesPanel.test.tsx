import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { PipelinesPanel } from "./PipelinesPanel";
import { ApiError } from "@/lib/api/errors";

const { listPipelinesMock, listStagesMock } = vi.hoisted(() => ({
  listPipelinesMock: vi.fn(),
  listStagesMock: vi.fn(),
}));
vi.mock("@/lib/api/crm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/crm")>();
  return { ...actual, listPipelines: listPipelinesMock, listStages: listStagesMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const PIPELINE = { id: "p1", tenant_id: "t1", name: "Sales", is_default: true };

function stage(overrides: Record<string, unknown> = {}) {
  return {
    id: "s1",
    tenant_id: "t1",
    pipeline_id: "p1",
    name: "Closed",
    position: 0,
    is_won: false,
    is_lost: false,
    ...overrides,
  };
}

describe("PipelinesPanel (UI-8)", () => {
  it("states won and lost in text, not only through badge colour", async () => {
    listPipelinesMock.mockResolvedValue([PIPELINE]);
    listStagesMock.mockResolvedValue([
      stage({ id: "s1", name: "Won deal", is_won: true, position: 0 }),
      stage({ id: "s2", name: "Lost deal", is_lost: true, position: 1 }),
      stage({ id: "s3", name: "Negotiation", position: 2 }),
    ]);

    render(<PipelinesPanel tenantId="t1" />);

    // The outcome must survive being read aloud or viewed without colour.
    await waitFor(() => expect(screen.getByText("Won deal (won)")).toBeInTheDocument());
    expect(screen.getByText("Lost deal (lost)")).toBeInTheDocument();
    // A neutral stage gains no suffix.
    expect(screen.getByText("Negotiation")).toBeInTheDocument();
  });

  it("gives each pipeline card a real heading", async () => {
    listPipelinesMock.mockResolvedValue([PIPELINE]);
    listStagesMock.mockResolvedValue([]);

    render(<PipelinesPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Sales" })).toBeInTheDocument());
    // The create form is a sibling section, not a subsection of a card.
    expect(screen.getByRole("heading", { name: "Create a pipeline" })).toBeInTheDocument();
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listPipelinesMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );

    render(<PipelinesPanel tenantId="t1" />);

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
