import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AcceptInvitationForm } from "./AcceptInvitationForm";
import { ApiError } from "@/lib/api/errors";

const { acceptInvitationMock } = vi.hoisted(() => ({ acceptInvitationMock: vi.fn() }));
vi.mock("@/lib/api/agency", () => ({ acceptInvitation: acceptInvitationMock }));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("AcceptInvitationForm", () => {
  it("pre-fills from initial props and submits them", async () => {
    acceptInvitationMock.mockResolvedValue({ tenant_id: "tenant-1", membership_id: "m1" });
    const user = userEvent.setup();
    render(<AcceptInvitationForm initialTenantId="tenant-1" initialToken="tok-1" />);

    await user.click(screen.getByRole("button", { name: "Accept invitation" }));

    await waitFor(() => expect(acceptInvitationMock).toHaveBeenCalledWith("tenant-1", "tok-1"));
  });

  it("on success, links to the new tenant's dashboard and confirms starting access was assigned", async () => {
    acceptInvitationMock.mockResolvedValue({ tenant_id: "tenant-1", membership_id: "m1" });
    const user = userEvent.setup();
    render(<AcceptInvitationForm initialTenantId="tenant-1" initialToken="tok-1" />);

    await user.click(screen.getByRole("button", { name: "Accept invitation" }));

    await waitFor(() => expect(screen.getByText(/joined this tenant/)).toBeInTheDocument());
    expect(screen.getByText(/starting access already in place/)).toBeInTheDocument();
    // The response carries no role/permission field
    // (InvitationAccepted = {tenant_id, membership_id}) -- this form must
    // never invent one to describe.
    expect(screen.queryByText(/no way/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the dashboard" })).toHaveAttribute(
      "href",
      "/t/tenant-1/dashboard",
    );
  });

  it("shows the backend's single collapsed message for every kind of invalid token", async () => {
    acceptInvitationMock.mockRejectedValue(
      new ApiError(
        "validation",
        "Invitation is invalid, expired, revoked, already accepted, or does not belong to this tenant.",
        { status: 400 },
      ),
    );
    const user = userEvent.setup();
    render(<AcceptInvitationForm initialTenantId="tenant-1" initialToken="bad-token" />);

    await user.click(screen.getByRole("button", { name: "Accept invitation" }));

    await waitFor(() =>
      expect(
        screen.getByText(
          "Invitation is invalid, expired, revoked, already accepted, or does not belong to this tenant.",
        ),
      ).toBeInTheDocument(),
    );
  });
});
