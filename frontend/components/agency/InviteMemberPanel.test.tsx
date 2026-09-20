import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InviteMemberPanel } from "./InviteMemberPanel";
import { ApiError } from "@/lib/api/errors";

const { inviteMemberMock } = vi.hoisted(() => ({ inviteMemberMock: vi.fn() }));
vi.mock("@/lib/api/agency", () => ({ inviteMember: inviteMemberMock }));

describe("InviteMemberPanel", () => {
  it("on success, shows the one-time invitation link built from the real raw_token", async () => {
    inviteMemberMock.mockResolvedValue({ invitation_id: "inv-1", raw_token: "secret-token" });
    const user = userEvent.setup();
    render(<InviteMemberPanel tenantId="tenant-1" />);

    await user.type(screen.getByLabelText("Email address"), "new@example.com");
    await user.click(screen.getByRole("button", { name: "Send invitation" }));

    await waitFor(() =>
      expect(screen.getByText(/Invitation created for/)).toBeInTheDocument(),
    );
    const link = screen.getByLabelText("Invitation link") as HTMLInputElement;
    expect(link.value).toContain("tenant=tenant-1");
    expect(link.value).toContain("token=secret-token");
    expect(inviteMemberMock).toHaveBeenCalledWith("tenant-1", "new@example.com");
  });

  it("shows the backend error on failure and does not show a token", async () => {
    inviteMemberMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    const user = userEvent.setup();
    render(<InviteMemberPanel tenantId="tenant-1" />);

    await user.type(screen.getByLabelText("Email address"), "new@example.com");
    await user.click(screen.getByRole("button", { name: "Send invitation" }));

    await waitFor(() =>
      expect(screen.getByText("not found, or no access")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Invitation link")).not.toBeInTheDocument();
  });
});
