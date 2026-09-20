import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SupportAccessPanel } from "./SupportAccessPanel";
import { ApiError } from "@/lib/api/errors";

const { approveSupportAccessMock, denySupportAccessMock, revokeSupportAccessMock, requestSupportAccessMock } =
  vi.hoisted(() => ({
    approveSupportAccessMock: vi.fn(),
    denySupportAccessMock: vi.fn(),
    revokeSupportAccessMock: vi.fn(),
    requestSupportAccessMock: vi.fn(),
  }));

vi.mock("@/lib/api/agency", () => ({
  approveSupportAccess: approveSupportAccessMock,
  denySupportAccess: denySupportAccessMock,
  revokeSupportAccess: revokeSupportAccessMock,
  requestSupportAccess: requestSupportAccessMock,
}));

describe("SupportAccessPanel", () => {
  it("requires explicit confirmation before approving a request", async () => {
    approveSupportAccessMock.mockResolvedValue({
      request_id: "req-1",
      approved_at: "2026-01-01T00:00:00Z",
    });
    const user = userEvent.setup();
    render(<SupportAccessPanel tenantId="tenant-1" />);

    const [requestIdInput] = screen.getAllByLabelText("Request ID");
    await user.type(requestIdInput, "req-1");
    await user.click(screen.getAllByRole("button", { name: "Approve" })[0]);

    // The backend call must not have fired yet -- only the confirmation
    // dialog has opened.
    expect(approveSupportAccessMock).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText("Approve this support-access request?"),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(approveSupportAccessMock).toHaveBeenCalledWith("tenant-1", "req-1"));
  });

  it("cancelling the confirmation dialog never calls the backend", async () => {
    const user = userEvent.setup();
    render(<SupportAccessPanel tenantId="tenant-1" />);

    const [, , revokeInput] = screen.getAllByLabelText("Request ID");
    await user.type(revokeInput, "req-2");
    await user.click(screen.getAllByRole("button", { name: "Revoke" })[0]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(revokeSupportAccessMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a permission-denied-shaped message on a 403 from deny", async () => {
    denySupportAccessMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 403 }),
    );
    const user = userEvent.setup();
    render(<SupportAccessPanel tenantId="tenant-1" />);

    const [, denyInput] = screen.getAllByLabelText("Request ID");
    await user.type(denyInput, "req-3");
    await user.click(screen.getAllByRole("button", { name: "Deny" })[0]);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Deny" }));

    await waitFor(() =>
      expect(screen.getByText("not found, or no access")).toBeInTheDocument(),
    );
  });
});
