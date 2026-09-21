import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AccessSettingsPanel } from "./AccessSettingsPanel";
import { SupportAccessSettingsPanel } from "./SupportAccessSettingsPanel";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/t1/settings/access" }));

const { inviteMemberMock } = vi.hoisted(() => ({ inviteMemberMock: vi.fn() }));
vi.mock("@/lib/api/agency", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/agency")>();
  return { ...actual, inviteMember: inviteMemberMock };
});

describe("AccessSettingsPanel", () => {
  it("invites through the real agency endpoint, scoped to the tenant in context", async () => {
    inviteMemberMock.mockResolvedValue({ invitation_id: "inv1", raw_token: "tok-abc" });
    const user = userEvent.setup();

    render(<AccessSettingsPanel tenantId="tenant-1" />);

    await user.type(screen.getByLabelText(/email/i), "new@example.com");
    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    await waitFor(() =>
      expect(inviteMemberMock).toHaveBeenCalledWith("tenant-1", "new@example.com"),
    );
  });

  it("surfaces a mutation failure without claiming the invite was sent", async () => {
    inviteMemberMock.mockRejectedValue(
      new ApiError("forbidden", "Not found, or you don't have access to it.", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<AccessSettingsPanel tenantId="tenant-1" />);
    await user.type(screen.getByLabelText(/email/i), "new@example.com");
    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    await waitFor(() =>
      expect(screen.getByText("Not found, or you don't have access to it.")).toBeInTheDocument(),
    );
  });

  it("states that members, roles, and pending invitations cannot be listed", () => {
    render(<AccessSettingsPanel tenantId="tenant-1" />);
    expect(screen.getByText(/no members list/i)).toBeInTheDocument();
  });

  it("renders delegated administration with real headings", () => {
    render(<AccessSettingsPanel tenantId="tenant-1" />);
    expect(
      screen.getByRole("heading", { level: 2, name: "Delegated administration" }),
    ).toBeInTheDocument();
  });
});

describe("SupportAccessSettingsPanel", () => {
  it("renders the support-access section for the tenant in context", () => {
    render(<SupportAccessSettingsPanel tenantId="tenant-1" />);
    expect(screen.getByRole("heading", { level: 2, name: "Support access" })).toBeInTheDocument();
  });
});
