import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ApprovalDetail } from "./ApprovalDetail";
import { ApiError } from "@/lib/api/errors";

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const { getApprovalMock } = vi.hoisted(() => ({ getApprovalMock: vi.fn() }));
vi.mock("@/lib/api/approvals", () => ({ getApproval: getApprovalMock }));

const APPROVAL = {
  id: "a1",
  tenant_id: "t1",
  tool_key: "ai.crm.qualify_lead",
  action_label: "Lead kwalificeren",
  status: "pending",
  status_label: "Wacht op goedkeuring",
  reason: "Deze actie vereist menselijke goedkeuring.",
  proposer_user_id: "u1",
  approver_user_id: null,
  created_at: "2026-06-10T09:00:00Z",
  decided_at: null,
  can_decide: true,
  can_execute: false,
};

describe("ApprovalDetail", () => {
  it("answers what/why/who/when/status in business language from real data", async () => {
    getApprovalMock.mockResolvedValue(APPROVAL);

    render(<ApprovalDetail tenantId="t1" approvalId="a1" />);

    await waitFor(() => expect(screen.getByText("Lead kwalificeren")).toBeInTheDocument());
    expect(screen.getByText("Deze actie vereist menselijke goedkeuring.")).toBeInTheDocument();
    expect(screen.getByText("Een gebruiker in uw organisatie")).toBeInTheDocument();
    expect(screen.getByText("Wacht op goedkeuring")).toBeInTheDocument();
    // No raw technical identifiers leaked into the detail view.
    expect(screen.queryByText("ai.crm.qualify_lead")).not.toBeInTheDocument();
    expect(screen.queryByText("u1")).not.toBeInTheDocument();
  });

  it("shows a recoverable error state on failure", async () => {
    getApprovalMock.mockRejectedValue(new ApiError("server", "Kon niet laden."));

    render(<ApprovalDetail tenantId="t1" approvalId="a1" />);

    await waitFor(() => expect(screen.getByText("Kon niet laden.")).toBeInTheDocument());
  });
});
