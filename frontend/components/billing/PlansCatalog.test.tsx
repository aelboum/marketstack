import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { PlansCatalog } from "./PlansCatalog";
import { ApiError } from "@/lib/api/errors";

const { listPlansMock } = vi.hoisted(() => ({ listPlansMock: vi.fn() }));
vi.mock("@/lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/billing")>();
  return { ...actual, listPlans: listPlansMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("PlansCatalog", () => {
  it("renders the platform plans returned by GET /v1/billing/plans", async () => {
    listPlansMock.mockResolvedValue([
      { key: "starter", name: "Starter", entitlements: { max_users: 5 } },
      { key: "pro", name: "Pro", entitlements: {} },
    ]);
    render(<PlansCatalog />);

    expect(screen.getAllByText("Loading platform plans…").length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByText("Starter")).toBeInTheDocument());
    expect(screen.getByText("Pro")).toBeInTheDocument();
    expect(screen.getByText("max_users")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("shows an empty state when the catalog has no plans", async () => {
    listPlansMock.mockResolvedValue([]);
    render(<PlansCatalog />);
    await waitFor(() => expect(screen.getByText("No platform plans")).toBeInTheDocument());
  });

  it("shows a permission-denied state on a 403, never the raw backend message", async () => {
    listPlansMock.mockRejectedValue(new ApiError("forbidden", "some backend detail"));
    render(<PlansCatalog />);
    // ApiErrorPanel's non-enumerating PermissionDeniedState renders its
    // own fixed copy for "forbidden" -- never the backend's own message.
    await waitFor(() => expect(screen.getByText("Not found, or you don't have access")).toBeInTheDocument());
    expect(screen.queryByText("some backend detail")).not.toBeInTheDocument();
  });
});
