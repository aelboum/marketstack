import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RunStepsList } from "./RunStepsList";
import { ApiError } from "@/lib/api/errors";

const { listRunStepsMock } = vi.hoisted(() => ({ listRunStepsMock: vi.fn() }));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return { ...actual, listRunSteps: listRunStepsMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function step(overrides: Record<string, unknown> = {}) {
  return {
    id: "s1",
    run_id: "r1",
    step_key: "action",
    step_type: "action",
    status: "succeeded",
    error: null,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    ...overrides,
  };
}

describe("RunStepsList", () => {
  it("distinguishes succeeded, failed, skipped, and running steps -- not by colour alone", async () => {
    listRunStepsMock.mockResolvedValue([
      step({ id: "s1", status: "succeeded" }),
      step({ id: "s2", status: "failed", error: "webhook host is not public." }),
      step({ id: "s3", status: "skipped" }),
      step({ id: "s4", status: "running", completed_at: null }),
    ]);

    render(<RunStepsList tenantId="t1" runId="r1" />);

    await waitFor(() => expect(screen.getByText("succeeded")).toBeInTheDocument());
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("skipped")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    // Each status word is real distinguishing text, not merely a colour.
    expect(screen.getByText("webhook host is not public.")).toBeInTheDocument();
  });

  it("never invents a 'pending' step -- a step with no row simply is not shown", async () => {
    listRunStepsMock.mockResolvedValue([step({ status: "running" })]);
    render(<RunStepsList tenantId="t1" runId="r1" />);
    await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
    expect(screen.queryByText("pending")).not.toBeInTheDocument();
  });

  it("shows an empty state before any step has run", async () => {
    listRunStepsMock.mockResolvedValue([]);
    render(<RunStepsList tenantId="t1" runId="r1" />);
    await waitFor(() => expect(screen.getByText("No step detail yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listRunStepsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<RunStepsList tenantId="t1" runId="r1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
