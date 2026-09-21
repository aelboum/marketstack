import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RunDetailCard } from "./RunDetailCard";
import type { Run } from "@/lib/api/automation";

const { cancelRunMock } = vi.hoisted(() => ({ cancelRunMock: vi.fn() }));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return { ...actual, cancelRun: cancelRunMock };
});

function run(overrides: Partial<Run> = {}): Run {
  return {
    id: "r1",
    tenant_id: "t1",
    workflow_id: "w1",
    workflow_version_id: "v1",
    status: "running",
    actor_user_id: "u1",
    temporal_workflow_id: "internal-should-not-render",
    current_step_key: "action",
    waiting_for_event_type: null,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:01Z",
    completed_at: null,
    ...overrides,
  };
}

describe("RunDetailCard", () => {
  it("offers Cancel for a non-terminal run, and requires confirmation", async () => {
    cancelRunMock.mockResolvedValue(run({ status: "cancelled" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<RunDetailCard tenantId="t1" run={run()} onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Cancel run" }));
    expect(cancelRunMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel run" }));

    await waitFor(() => expect(cancelRunMock).toHaveBeenCalledWith("t1", "r1"));
    expect(onChanged).toHaveBeenCalledWith(run({ status: "cancelled" }));
  });

  it("offers no Cancel action for a terminal run status", () => {
    render(<RunDetailCard tenantId="t1" run={run({ status: "completed" })} onChanged={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });

  it("shows waiting_for_event_type only when the backend actually sets it", () => {
    const { rerender } = render(
      <RunDetailCard tenantId="t1" run={run({ status: "waiting", waiting_for_event_type: null })} onChanged={vi.fn()} />,
    );
    expect(screen.queryByText("Waiting for")).not.toBeInTheDocument();

    rerender(
      <RunDetailCard
        tenantId="t1"
        run={run({ status: "waiting", waiting_for_event_type: "crm.contact.created" })}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByText("Waiting for")).toBeInTheDocument();
    expect(screen.getByText("crm.contact.created")).toBeInTheDocument();
  });

  it("never renders the raw Temporal workflow id", () => {
    render(<RunDetailCard tenantId="t1" run={run()} onChanged={vi.fn()} />);
    expect(screen.queryByText("internal-should-not-render")).not.toBeInTheDocument();
  });
});
