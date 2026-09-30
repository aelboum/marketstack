import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SubscriptionsPanel } from "./SubscriptionsPanel";
import { ApiError } from "@/lib/api/errors";

const {
  listSubscriptionsMock,
  createSubscriptionMock,
  changeSubscriptionPlanMock,
  cancelSubscriptionMock,
  listPlansMock,
  listAvailableResalePlansMock,
} = vi.hoisted(() => ({
  listSubscriptionsMock: vi.fn(),
  createSubscriptionMock: vi.fn(),
  changeSubscriptionPlanMock: vi.fn(),
  cancelSubscriptionMock: vi.fn(),
  listPlansMock: vi.fn(),
  listAvailableResalePlansMock: vi.fn(),
}));
vi.mock("@/lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/billing")>();
  return {
    ...actual,
    listSubscriptions: listSubscriptionsMock,
    createSubscription: createSubscriptionMock,
    changeSubscriptionPlan: changeSubscriptionPlanMock,
    cancelSubscription: cancelSubscriptionMock,
    listPlans: listPlansMock,
    listAvailableResalePlans: listAvailableResalePlansMock,
  };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const SUBSCRIPTION = {
  id: "sub-1",
  tenant_id: "t1",
  plan_id: "plan-uuid-1",
  plan_key: "starter",
  resale_plan_id: null,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function setDefaultPlanMocks() {
  listPlansMock.mockResolvedValue([{ key: "pro", name: "Pro", entitlements: {} }]);
  listAvailableResalePlansMock.mockResolvedValue([]);
}

describe("SubscriptionsPanel", () => {
  it("renders existing subscription data scoped to the given tenant", async () => {
    setDefaultPlanMocks();
    listSubscriptionsMock.mockResolvedValue([SUBSCRIPTION]);
    render(<SubscriptionsPanel tenantId="t1" />);

    await waitFor(() => expect(listSubscriptionsMock).toHaveBeenCalledWith("t1"));
    await waitFor(() => expect(screen.getByText("starter")).toBeInTheDocument());
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("shows an empty state when the tenant has no subscription", async () => {
    setDefaultPlanMocks();
    listSubscriptionsMock.mockResolvedValue([]);
    render(<SubscriptionsPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No subscription yet")).toBeInTheDocument());
  });

  it("creates a subscription against the chosen platform plan and refreshes the list", async () => {
    setDefaultPlanMocks();
    listSubscriptionsMock.mockResolvedValueOnce([]).mockResolvedValueOnce([SUBSCRIPTION]);
    createSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    const user = userEvent.setup();
    render(<SubscriptionsPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("No subscription yet")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Subscribe" })).toBeInTheDocument());
    const startForm = screen.getByRole("button", { name: "Subscribe" }).closest("form")!;
    await user.selectOptions(within(startForm).getByLabelText("Plan"), "platform:pro");
    await user.click(screen.getByRole("button", { name: "Subscribe" }));

    await waitFor(() =>
      expect(createSubscriptionMock).toHaveBeenCalledWith("t1", { platformPlanKey: "pro" }),
    );
    await waitFor(() => expect(listSubscriptionsMock).toHaveBeenCalledTimes(2));
  });

  it("calls the change-plan endpoint with the chosen plan", async () => {
    setDefaultPlanMocks();
    listSubscriptionsMock.mockResolvedValue([SUBSCRIPTION]);
    changeSubscriptionPlanMock.mockResolvedValue({ ...SUBSCRIPTION, plan_key: "pro" });
    const user = userEvent.setup();
    render(<SubscriptionsPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("starter")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Change plan" }));

    const dialog = await screen.findByRole("dialog", { name: "Change plan" });
    await user.selectOptions(within(dialog).getByLabelText("Plan"), "platform:pro");
    await user.click(within(dialog).getByRole("button", { name: "Change plan" }));

    await waitFor(() =>
      expect(changeSubscriptionPlanMock).toHaveBeenCalledWith("t1", "sub-1", { platformPlanKey: "pro" }),
    );
  });

  it("requires confirmation before cancelling, and only calls cancel after confirming", async () => {
    setDefaultPlanMocks();
    listSubscriptionsMock.mockResolvedValue([SUBSCRIPTION]);
    cancelSubscriptionMock.mockResolvedValue({ ...SUBSCRIPTION, status: "canceled" });
    const user = userEvent.setup();
    render(<SubscriptionsPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("starter")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(cancelSubscriptionMock).not.toHaveBeenCalled();
    expect(screen.getByText("Cancel this subscription?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel subscription" }));

    await waitFor(() => expect(cancelSubscriptionMock).toHaveBeenCalledWith("t1", "sub-1"));
  });

  it("does not offer change-plan/cancel on a subscription that is not active", async () => {
    setDefaultPlanMocks();
    listSubscriptionsMock.mockResolvedValue([{ ...SUBSCRIPTION, status: "canceled" }]);
    render(<SubscriptionsPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("starter")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Change plan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("shows a permission-denied state on a 403 from the subscriptions list", async () => {
    setDefaultPlanMocks();
    listSubscriptionsMock.mockRejectedValue(new ApiError("forbidden", "irrelevant"));
    render(<SubscriptionsPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Not found, or you don't have access")).toBeInTheDocument());
  });
});
