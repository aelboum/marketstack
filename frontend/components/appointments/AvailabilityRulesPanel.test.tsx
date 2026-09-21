import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AvailabilityRulesPanel } from "./AvailabilityRulesPanel";
import { ApiError } from "@/lib/api/errors";

const { listAvailabilityRulesMock, createAvailabilityRuleMock, deleteAvailabilityRuleMock } =
  vi.hoisted(() => ({
    listAvailabilityRulesMock: vi.fn(),
    createAvailabilityRuleMock: vi.fn(),
    deleteAvailabilityRuleMock: vi.fn(),
  }));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    listAvailabilityRules: listAvailabilityRulesMock,
    createAvailabilityRule: createAvailabilityRuleMock,
    deleteAvailabilityRule: deleteAvailabilityRuleMock,
  };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function rule(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    tenant_id: "t1",
    calendar_id: "cal1",
    day_of_week: 0,
    start_time: 540,
    end_time: 1020,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("AvailabilityRulesPanel", () => {
  it("renders day_of_week 0 as Monday (Python weekday semantics) with HH:MM times", async () => {
    listAvailabilityRulesMock.mockResolvedValue([rule()]);
    render(<AvailabilityRulesPanel tenantId="t1" calendarId="cal1" />);

    await waitFor(() => expect(screen.getByText("Monday")).toBeInTheDocument());
    expect(screen.getByText("09:00 – 17:00")).toBeInTheDocument();
  });

  it("shows an empty state with no rules", async () => {
    listAvailabilityRulesMock.mockResolvedValue([]);
    render(<AvailabilityRulesPanel tenantId="t1" calendarId="cal1" />);
    await waitFor(() => expect(screen.getByText("No availability yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listAvailabilityRulesMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<AvailabilityRulesPanel tenantId="t1" calendarId="cal1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("creates a rule with minutes-since-midnight values", async () => {
    listAvailabilityRulesMock.mockResolvedValue([]);
    createAvailabilityRuleMock.mockResolvedValue(rule());
    const user = userEvent.setup();

    render(<AvailabilityRulesPanel tenantId="t1" calendarId="cal1" />);
    await waitFor(() => expect(screen.getByLabelText("Day")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Day"), "2");
    await user.click(screen.getByRole("button", { name: "Add rule" }));

    await waitFor(() =>
      expect(createAvailabilityRuleMock).toHaveBeenCalledWith("t1", "cal1", {
        day_of_week: 2,
        start_time: 540,
        end_time: 1020,
      }),
    );
  });

  it("warns about an overlap the backend would silently accept, without blocking it", async () => {
    listAvailabilityRulesMock.mockResolvedValue([rule()]);
    const user = userEvent.setup();

    render(<AvailabilityRulesPanel tenantId="t1" calendarId="cal1" />);
    await waitFor(() => expect(screen.getByText("Monday")).toBeInTheDocument());

    // Default form values (Monday 09:00-17:00) collide with the existing rule.
    expect(screen.getByText(/overlaps a rule that already exists for Monday/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add rule" })).toBeEnabled();

    // Moving to a free day clears the warning.
    await user.selectOptions(screen.getByLabelText("Day"), "3");
    expect(screen.queryByText(/overlaps a rule that already exists/)).not.toBeInTheDocument();
  });

  it("disables submit when the end time is not after the start time", async () => {
    listAvailabilityRulesMock.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<AvailabilityRulesPanel tenantId="t1" calendarId="cal1" />);
    await waitFor(() => expect(screen.getByLabelText("End time")).toBeInTheDocument());

    await user.clear(screen.getByLabelText("End time"));
    await user.type(screen.getByLabelText("End time"), "08:00");

    expect(screen.getByRole("button", { name: "Add rule" })).toBeDisabled();
    expect(screen.getByText("End time must be after start time.")).toBeInTheDocument();
  });

  it("removing a rule requires confirmation", async () => {
    listAvailabilityRulesMock.mockResolvedValue([rule()]);
    deleteAvailabilityRuleMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<AvailabilityRulesPanel tenantId="t1" calendarId="cal1" />);
    await waitFor(() => expect(screen.getByText("Monday")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(deleteAvailabilityRuleMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(deleteAvailabilityRuleMock).toHaveBeenCalledWith("t1", "cal1", "r1"),
    );
  });
});
