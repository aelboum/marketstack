import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalActions } from "./ApprovalActions";
import { ApiError } from "@/lib/api/errors";
import type { Approval } from "@/lib/api/approvals";

const { approveApprovalMock, rejectApprovalMock, executeApprovalMock } = vi.hoisted(() => ({
  approveApprovalMock: vi.fn(),
  rejectApprovalMock: vi.fn(),
  executeApprovalMock: vi.fn(),
}));

vi.mock("@/lib/api/approvals", () => ({
  approveApproval: approveApprovalMock,
  rejectApproval: rejectApprovalMock,
  executeApproval: executeApprovalMock,
}));

function pendingApproval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "a1",
    tenant_id: "t1",
    tool_key: "ai.crm.qualify_lead",
    action_label: "Lead kwalificeren",
    status: "pending",
    status_label: "Wacht op goedkeuring",
    reason: "Dit vereist goedkeuring.",
    proposer_user_id: "u1",
    approver_user_id: null,
    created_at: "2026-06-10T09:00:00Z",
    decided_at: null,
    can_decide: true,
    can_execute: false,
    ...overrides,
  };
}

describe("ApprovalActions", () => {
  it("renders no actions once neither decide nor execute applies -- state-driven, not hidden by assumed authorization", () => {
    const { container } = render(
      <ApprovalActions
        tenantId="t1"
        approval={pendingApproval({ can_decide: false, can_execute: false, status: "rejected" })}
        onChanged={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("requires confirmation before approving, then calls the real backend action exactly once", async () => {
    approveApprovalMock.mockResolvedValue(pendingApproval({ status: "approved", can_decide: false, can_execute: true }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<ApprovalActions tenantId="t1" approval={pendingApproval()} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Goedkeuren" }));
    expect(screen.getByRole("dialog", { name: "Actie goedkeuren?" })).toBeInTheDocument();
    // Not yet called -- confirmation is required first.
    expect(approveApprovalMock).not.toHaveBeenCalled();

    await user.click(screen.getAllByRole("button", { name: "Goedkeuren" })[1]);

    await waitFor(() => expect(approveApprovalMock).toHaveBeenCalledTimes(1));
    expect(approveApprovalMock).toHaveBeenCalledWith("t1", "a1");
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows a distinct stale/conflict notice on 409, and refetches -- never a generic error", async () => {
    approveApprovalMock.mockRejectedValue(new ApiError("server", "conflict", { status: 409 }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<ApprovalActions tenantId="t1" approval={pendingApproval()} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Goedkeuren" }));
    await user.click(screen.getAllByRole("button", { name: "Goedkeuren" })[1]);

    await waitFor(() =>
      expect(
        screen.getByText(/niet meer actueel/),
      ).toBeInTheDocument(),
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows a business-language message on 403, not a raw backend error", async () => {
    rejectApprovalMock.mockRejectedValue(new ApiError("forbidden", "Not found, or you don't have access to it.", { status: 403 }));
    const user = userEvent.setup();

    render(<ApprovalActions tenantId="t1" approval={pendingApproval()} onChanged={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Afwijzen" }));
    await user.click(screen.getAllByRole("button", { name: "Afwijzen" })[1]);

    await waitFor(() =>
      expect(screen.getByText("U bent niet bevoegd om deze actie uit te voeren.")).toBeInTheDocument(),
    );
  });

  it("only shows Execute once the approval is actually approved (can_execute), never before", () => {
    render(
      <ApprovalActions tenantId="t1" approval={pendingApproval()} onChanged={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Uitvoeren" })).not.toBeInTheDocument();
  });

  it("disables the confirm button while the action is in flight -- no double-submit", async () => {
    let resolveApprove: (value: Approval) => void = () => {};
    approveApprovalMock.mockReturnValue(
      new Promise<Approval>((resolve) => {
        resolveApprove = resolve;
      }),
    );
    const user = userEvent.setup();

    render(<ApprovalActions tenantId="t1" approval={pendingApproval()} onChanged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Goedkeuren" }));
    const confirmButton = screen.getAllByRole("button", { name: /Goedkeuren|Working/ })[1];
    await user.click(confirmButton);

    await waitFor(() => expect(confirmButton).toBeDisabled());
    resolveApprove(pendingApproval({ status: "approved" }));
  });
});
