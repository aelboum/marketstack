import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkflowStatusControl } from "./WorkflowStatusControl";
import type { Workflow } from "@/lib/api/automation";
import { ApiError } from "@/lib/api/errors";

const { setWorkflowStatusMock } = vi.hoisted(() => ({ setWorkflowStatusMock: vi.fn() }));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return { ...actual, setWorkflowStatus: setWorkflowStatusMock };
});

function workflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: "w1",
    tenant_id: "t1",
    name: "Test",
    status: "paused",
    current_published_version_id: "v1",
    created_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("WorkflowStatusControl", () => {
  it("activating requires confirmation -- pausing does not", async () => {
    setWorkflowStatusMock.mockResolvedValue(workflow({ status: "active" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<WorkflowStatusControl tenantId="t1" workflow={workflow()} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Activate" }));
    expect(setWorkflowStatusMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Activate" }));

    await waitFor(() => expect(setWorkflowStatusMock).toHaveBeenCalledWith("t1", "w1", "active"));
    expect(onChanged).toHaveBeenCalledWith(workflow({ status: "active" }));
  });

  it("pauses immediately, without a confirmation dialog", async () => {
    setWorkflowStatusMock.mockResolvedValue(workflow({ status: "paused" }));
    const user = userEvent.setup();

    render(<WorkflowStatusControl tenantId="t1" workflow={workflow({ status: "active" })} onChanged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Pause" }));

    await waitFor(() => expect(setWorkflowStatusMock).toHaveBeenCalledWith("t1", "w1", "paused"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("disables Activate when there is no published version, and explains why", () => {
    render(
      <WorkflowStatusControl
        tenantId="t1"
        workflow={workflow({ current_published_version_id: null })}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Activate" })).toBeDisabled();
    expect(screen.getByText(/Publish a version before activating/)).toBeInTheDocument();
  });

  it("shows the backend's own error on a failed status change", async () => {
    setWorkflowStatusMock.mockRejectedValue(
      new ApiError("forbidden", "Not found, or you don't have access to it.", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<WorkflowStatusControl tenantId="t1" workflow={workflow({ status: "active" })} onChanged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Pause" }));

    await waitFor(() =>
      expect(screen.getByText("Not found, or you don't have access to it.")).toBeInTheDocument(),
    );
  });
});
