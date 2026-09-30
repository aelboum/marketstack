import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import BillingPage from "./page";
import { TenantProvider } from "@/lib/tenant/tenant-context";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/t1/billing" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const {
  listSubscriptionsMock,
  getEntitlementsMock,
  listPlansMock,
  listResalePlansMock,
  listAvailableResalePlansMock,
} = vi.hoisted(() => ({
  listSubscriptionsMock: vi.fn(),
  getEntitlementsMock: vi.fn(),
  listPlansMock: vi.fn(),
  listResalePlansMock: vi.fn(),
  listAvailableResalePlansMock: vi.fn(),
}));
vi.mock("@/lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/billing")>();
  return {
    ...actual,
    listSubscriptions: listSubscriptionsMock,
    getEntitlements: getEntitlementsMock,
    listPlans: listPlansMock,
    listResalePlans: listResalePlansMock,
    listAvailableResalePlans: listAvailableResalePlansMock,
  };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function renderPage(tenantId: string) {
  return render(
    <TenantProvider tenantId={tenantId}>
      <BillingPage />
    </TenantProvider>,
  );
}

describe("BillingPage (UI-14)", () => {
  it("scopes every tenant-owned Billing call to the tenant id from the route, with no way to type a different one", async () => {
    listSubscriptionsMock.mockResolvedValue([]);
    getEntitlementsMock.mockResolvedValue({});
    listPlansMock.mockResolvedValue([]);
    listResalePlansMock.mockResolvedValue([]);
    listAvailableResalePlansMock.mockResolvedValue([]);

    renderPage("tenant-42");

    await waitFor(() => expect(listSubscriptionsMock).toHaveBeenCalledWith("tenant-42"));
    expect(getEntitlementsMock).toHaveBeenCalledWith("tenant-42");
    await waitFor(() => expect(listResalePlansMock).toHaveBeenCalledWith("tenant-42"));

    // The Billing page itself never renders a free-text tenant/workspace
    // id field -- the tenant comes from the route only (useTenant()).
    expect(screen.queryByLabelText(/tenant/i)).not.toBeInTheDocument();
    expect(document.querySelector('input[type="text"]')).not.toBeInTheDocument();
  });

  it("renders the page heading and every Billing section", async () => {
    listSubscriptionsMock.mockResolvedValue([]);
    getEntitlementsMock.mockResolvedValue({});
    listPlansMock.mockResolvedValue([]);
    listResalePlansMock.mockResolvedValue([]);
    listAvailableResalePlansMock.mockResolvedValue([]);

    renderPage("t1");

    expect(screen.getByRole("heading", { name: "Subscription & plans" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Subscription" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Entitlements" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Platform plans" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Resale plans" })).toBeInTheDocument();
  });

  it("renders existing subscription data end to end", async () => {
    listSubscriptionsMock.mockResolvedValue([
      {
        id: "sub-1",
        tenant_id: "t1",
        plan_id: "p1",
        plan_key: "starter",
        resale_plan_id: null,
        status: "active",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    getEntitlementsMock.mockResolvedValue({ max_users: 5 });
    listPlansMock.mockResolvedValue([{ key: "starter", name: "Starter", entitlements: {} }]);
    listResalePlansMock.mockResolvedValue([]);
    listAvailableResalePlansMock.mockResolvedValue([]);

    renderPage("t1");

    await waitFor(() => expect(screen.getAllByText("starter").length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByText("max_users")).toBeInTheDocument());
  });
});
