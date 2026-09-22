import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AssignOpportunityForm } from "./AssignOpportunityForm";
import { ApiError } from "@/lib/api/errors";

const { assignOpportunityMock } = vi.hoisted(() => ({ assignOpportunityMock: vi.fn() }));
vi.mock("@/lib/api/crm", () => ({ assignOpportunity: assignOpportunityMock }));

describe("AssignOpportunityForm", () => {
  it("disables submit until a user id is entered, and has no unassign button when unassigned", () => {
    render(
      <AssignOpportunityForm
        tenantId="t1"
        opportunityId="o1"
        currentAssignedUserId={null}
        onAssigned={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Toewijzen" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Toewijzing intrekken" })).not.toBeInTheDocument();
  });

  it("submits a real user id and calls onAssigned with the real API response", async () => {
    assignOpportunityMock.mockResolvedValue({
      id: "o1",
      tenant_id: "t1",
      name: "Deal",
      contact_id: null,
      company_id: null,
      pipeline_id: "p1",
      stage_id: "s1",
      assigned_user_id: "u1",
      amount: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    const onAssigned = vi.fn();
    const user = userEvent.setup();
    render(
      <AssignOpportunityForm
        tenantId="t1"
        opportunityId="o1"
        currentAssignedUserId={null}
        onAssigned={onAssigned}
      />,
    );

    await user.type(screen.getByLabelText("Toewijzen aan gebruikers-ID"), "u1");
    await user.click(screen.getByRole("button", { name: "Toewijzen" }));

    await waitFor(() => expect(assignOpportunityMock).toHaveBeenCalledWith("t1", "o1", "u1"));
    expect(onAssigned).toHaveBeenCalled();
  });

  it("offers an unassign action once assigned, which submits null", async () => {
    assignOpportunityMock.mockResolvedValue({
      id: "o1",
      tenant_id: "t1",
      name: "Deal",
      contact_id: null,
      company_id: null,
      pipeline_id: "p1",
      stage_id: "s1",
      assigned_user_id: null,
      amount: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    const onAssigned = vi.fn();
    const user = userEvent.setup();
    render(
      <AssignOpportunityForm
        tenantId="t1"
        opportunityId="o1"
        currentAssignedUserId="u1"
        onAssigned={onAssigned}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Toewijzing intrekken" }));

    await waitFor(() => expect(assignOpportunityMock).toHaveBeenCalledWith("t1", "o1", null));
    expect(onAssigned).toHaveBeenCalled();
  });

  it("shows the backend's error and does not call onAssigned", async () => {
    assignOpportunityMock.mockRejectedValue(new ApiError("not_found", "assignee not found."));
    const onAssigned = vi.fn();
    const user = userEvent.setup();
    render(
      <AssignOpportunityForm
        tenantId="t1"
        opportunityId="o1"
        currentAssignedUserId={null}
        onAssigned={onAssigned}
      />,
    );

    await user.type(screen.getByLabelText("Toewijzen aan gebruikers-ID"), "unknown-user");
    await user.click(screen.getByRole("button", { name: "Toewijzen" }));

    await waitFor(() => expect(screen.getByText("assignee not found.")).toBeInTheDocument());
    expect(onAssigned).not.toHaveBeenCalled();
  });
});
