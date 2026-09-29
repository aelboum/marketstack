import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ActivitiesPanel } from "./ActivitiesPanel";
import type { Activity } from "@/lib/api/crm";

const { listActivitiesMock, deleteTaskMock, deleteNoteMock } = vi.hoisted(() => ({
  listActivitiesMock: vi.fn(),
  deleteTaskMock: vi.fn(),
  deleteNoteMock: vi.fn(),
}));
vi.mock("@/lib/api/crm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/crm")>();
  return {
    ...actual,
    listActivities: listActivitiesMock,
    deleteTask: deleteTaskMock,
    deleteNote: deleteNoteMock,
  };
});

function task(overrides: Partial<Activity> = {}): Activity {
  return {
    id: "task1",
    tenant_id: "t1",
    kind: "task",
    contact_id: "ct1",
    company_id: null,
    opportunity_id: null,
    created_at: "2026-03-01T00:00:00Z",
    updated_at: "2026-03-01T00:00:00Z",
    title: "Follow up",
    description: null,
    due_at: null,
    completed_at: null,
    ...overrides,
  } as Activity;
}

describe("ActivitiesPanel", () => {
  it("deleting a task requires confirmation before calling the API", async () => {
    listActivitiesMock.mockResolvedValue([task()]);
    deleteTaskMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<ActivitiesPanel tenantId="t1" parent={{ contactId: "ct1" }} />);

    await screen.findByText("Follow up");
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteTaskMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteTaskMock).toHaveBeenCalledWith("t1", "task1"));
  });

  it("cancelling the confirmation dialog leaves the task in place", async () => {
    listActivitiesMock.mockResolvedValue([task()]);
    const user = userEvent.setup();

    render(<ActivitiesPanel tenantId="t1" parent={{ contactId: "ct1" }} />);

    await screen.findByText("Follow up");
    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Keep it" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(deleteTaskMock).not.toHaveBeenCalled();
  });
});
