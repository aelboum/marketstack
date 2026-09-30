import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResalePlansPanel } from "./ResalePlansPanel";
import { ApiError } from "@/lib/api/errors";

const {
  listResalePlansMock,
  createResalePlanMock,
  updateResalePlanMock,
  deactivateResalePlanMock,
} = vi.hoisted(() => ({
  listResalePlansMock: vi.fn(),
  createResalePlanMock: vi.fn(),
  updateResalePlanMock: vi.fn(),
  deactivateResalePlanMock: vi.fn(),
}));
vi.mock("@/lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/billing")>();
  return {
    ...actual,
    listResalePlans: listResalePlansMock,
    createResalePlan: createResalePlanMock,
    updateResalePlan: updateResalePlanMock,
    deactivateResalePlan: deactivateResalePlanMock,
  };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const PLAN = {
  id: "plan-1",
  tenant_id: "t1",
  key: "starter",
  name: "Starter",
  description: "The basic tier",
  price_amount: 1000,
  price_currency: "USD",
  billing_interval: "month",
  entitlements: {},
  status: "enabled",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("ResalePlansPanel", () => {
  it("renders resale plans scoped to the given tenant", async () => {
    listResalePlansMock.mockResolvedValue([PLAN]);
    render(<ResalePlansPanel tenantId="t1" />);

    await waitFor(() => expect(listResalePlansMock).toHaveBeenCalledWith("t1"));
    await waitFor(() => expect(screen.getByText("Starter")).toBeInTheDocument());
    expect(screen.getByText("1000 USD / month")).toBeInTheDocument();
    expect(screen.getByText("enabled")).toBeInTheDocument();
  });

  it("shows an empty state when there are no resale plans yet", async () => {
    listResalePlansMock.mockResolvedValue([]);
    render(<ResalePlansPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No resale plans yet")).toBeInTheDocument());
  });

  it("creates a resale plan and refreshes the list", async () => {
    listResalePlansMock.mockResolvedValueOnce([]).mockResolvedValueOnce([PLAN]);
    createResalePlanMock.mockResolvedValue(PLAN);
    const user = userEvent.setup();
    render(<ResalePlansPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("No resale plans yet")).toBeInTheDocument());
    await user.type(screen.getByLabelText("Key"), "starter");
    await user.type(screen.getByLabelText("Name"), "Starter");
    await user.type(screen.getByLabelText("Price"), "1000");
    await user.clear(screen.getByLabelText("Currency"));
    await user.type(screen.getByLabelText("Currency"), "USD");
    await user.click(screen.getByRole("button", { name: "Create resale plan" }));

    await waitFor(() =>
      expect(createResalePlanMock).toHaveBeenCalledWith("t1", {
        key: "starter",
        name: "Starter",
        description: null,
        price_amount: 1000,
        price_currency: "USD",
        billing_interval: "month",
      }),
    );
    await waitFor(() => expect(listResalePlansMock).toHaveBeenCalledTimes(2));
  });

  it("edits a resale plan's name via the inline edit form", async () => {
    listResalePlansMock.mockResolvedValue([PLAN]);
    updateResalePlanMock.mockResolvedValue({ ...PLAN, name: "Starter Plus" });
    const user = userEvent.setup();
    render(<ResalePlansPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("Starter")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Edit" }));
    // The bottom "Create a resale plan" form also has its own "Name"
    // field -- the row's own edit form renders first in DOM order.
    const nameInput = screen.getAllByLabelText("Name")[0];
    await user.clear(nameInput);
    await user.type(nameInput, "Starter Plus");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateResalePlanMock).toHaveBeenCalledWith("t1", "plan-1", {
        name: "Starter Plus",
        description: "The basic tier",
      }),
    );
  });

  it("requires confirmation before deactivating a resale plan, and calls the deactivate endpoint only after confirming", async () => {
    listResalePlansMock.mockResolvedValue([PLAN]);
    deactivateResalePlanMock.mockResolvedValue({ ...PLAN, status: "disabled" });
    const user = userEvent.setup();
    render(<ResalePlansPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("Starter")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Deactivate" }));

    // The mutation must not fire merely from clicking the row action --
    // only the dialog's own confirm button may trigger it.
    expect(deactivateResalePlanMock).not.toHaveBeenCalled();
    expect(screen.getByText("Deactivate this resale plan?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(deactivateResalePlanMock).not.toHaveBeenCalled();
  });

  it("calls deactivate only once the confirmation dialog is confirmed", async () => {
    listResalePlansMock.mockResolvedValue([PLAN]);
    deactivateResalePlanMock.mockResolvedValue({ ...PLAN, status: "disabled" });
    const user = userEvent.setup();
    render(<ResalePlansPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("Starter")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialogButtons = screen.getAllByRole("button", { name: "Deactivate" });
    // Two "Deactivate" buttons now exist: the row action and the
    // dialog's own confirm button -- the confirm one is the last.
    await user.click(dialogButtons[dialogButtons.length - 1]);

    await waitFor(() => expect(deactivateResalePlanMock).toHaveBeenCalledWith("t1", "plan-1"));
  });

  it("shows a permission-denied state on a 403 from the list endpoint", async () => {
    listResalePlansMock.mockRejectedValue(new ApiError("forbidden", "irrelevant"));
    render(<ResalePlansPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Not found, or you don't have access")).toBeInTheDocument());
  });
});
