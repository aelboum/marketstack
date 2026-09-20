import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AssignThreadForm } from "./AssignThreadForm";
import { ApiError } from "@/lib/api/errors";

const { assignThreadMock } = vi.hoisted(() => ({ assignThreadMock: vi.fn() }));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return { ...actual, assignThread: assignThreadMock };
});

describe("AssignThreadForm", () => {
  it("assigns to the entered user id via the real endpoint", async () => {
    assignThreadMock.mockResolvedValue({ id: "th1", assigned_to_user_id: "u1" });
    const onAssigned = vi.fn();
    const user = userEvent.setup();

    render(<AssignThreadForm tenantId="t1" threadId="th1" currentAssigneeUserId={null} onAssigned={onAssigned} />);
    await user.type(screen.getByLabelText("Assign to user ID"), "u1");
    await user.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() => expect(assignThreadMock).toHaveBeenCalledWith("t1", "th1", "u1"));
    expect(onAssigned).toHaveBeenCalledWith({ id: "th1", assigned_to_user_id: "u1" });
  });

  it("shows the backend's real error for an assignee with no tenant membership (IDOR-adjacent check)", async () => {
    assignThreadMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<AssignThreadForm tenantId="t1" threadId="th1" currentAssigneeUserId={null} onAssigned={vi.fn()} />);
    await user.type(screen.getByLabelText("Assign to user ID"), "stranger-id");
    await user.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() => expect(screen.getByText("not found, or no access")).toBeInTheDocument());
  });
});
