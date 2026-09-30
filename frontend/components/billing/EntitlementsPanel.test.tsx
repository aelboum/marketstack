import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { EntitlementsPanel } from "./EntitlementsPanel";
import { ApiError } from "@/lib/api/errors";

const { getEntitlementsMock } = vi.hoisted(() => ({ getEntitlementsMock: vi.fn() }));
vi.mock("@/lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/billing")>();
  return { ...actual, getEntitlements: getEntitlementsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("EntitlementsPanel", () => {
  it("scopes the request to the given tenant and renders the returned entitlements", async () => {
    getEntitlementsMock.mockResolvedValue({ max_users: 10, can_export: true });
    render(<EntitlementsPanel tenantId="t1" />);

    await waitFor(() => expect(getEntitlementsMock).toHaveBeenCalledWith("t1"));
    await waitFor(() => expect(screen.getByText("max_users")).toBeInTheDocument());
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("can_export")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("shows an empty state when there are no effective entitlements", async () => {
    getEntitlementsMock.mockResolvedValue({});
    render(<EntitlementsPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No entitlements")).toBeInTheDocument());
  });

  it("shows a retryable error state on a server error", async () => {
    getEntitlementsMock.mockRejectedValue(new ApiError("server", "Something went wrong."));
    render(<EntitlementsPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Something went wrong.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
