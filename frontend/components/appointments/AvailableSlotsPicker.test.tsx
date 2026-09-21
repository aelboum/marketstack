import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AvailableSlotsPicker } from "./AvailableSlotsPicker";
import { ApiError } from "@/lib/api/errors";

const { listAvailableSlotsMock } = vi.hoisted(() => ({ listAvailableSlotsMock: vi.fn() }));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return { ...actual, listAvailableSlots: listAvailableSlotsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("AvailableSlotsPicker", () => {
  it("fetches nothing until a search is submitted, then shows only backend-returned slots", async () => {
    listAvailableSlotsMock.mockResolvedValue([
      { starts_at: "2026-03-02T08:00:00Z", ends_at: "2026-03-02T08:30:00Z" },
      { starts_at: "2026-03-02T08:30:00Z", ends_at: "2026-03-02T09:00:00Z" },
    ]);
    const user = userEvent.setup();

    render(
      <AvailableSlotsPicker tenantId="t1" calendarId="cal1" timeZone="Europe/Amsterdam" />,
    );
    expect(listAvailableSlotsMock).not.toHaveBeenCalled();
    expect(screen.getByText(/Choose a date range and slot length/)).toBeInTheDocument();

    await user.clear(screen.getByLabelText("From date"));
    await user.type(screen.getByLabelText("From date"), "2026-03-02");
    await user.clear(screen.getByLabelText("To date"));
    await user.type(screen.getByLabelText("To date"), "2026-03-02");
    await user.click(screen.getByRole("button", { name: "Find slots" }));

    await waitFor(() =>
      expect(listAvailableSlotsMock).toHaveBeenCalledWith("t1", "cal1", {
        date_from: "2026-03-02",
        date_to: "2026-03-02",
        slot_duration_minutes: 30,
      }),
    );
    // 08:00 UTC is 09:00 in Amsterdam -- the calendar's zone, not the viewer's.
    await waitFor(() => expect(screen.getByText("09:00")).toBeInTheDocument());
    expect(screen.getByText("09:30")).toBeInTheDocument();
    expect(screen.getByText(/Times shown in Europe\/Amsterdam/)).toBeInTheDocument();
  });

  it("blocks a date range longer than the real backend limit of 90 days", async () => {
    const user = userEvent.setup();
    render(<AvailableSlotsPicker tenantId="t1" calendarId="cal1" timeZone="UTC" />);

    await user.clear(screen.getByLabelText("From date"));
    await user.type(screen.getByLabelText("From date"), "2026-01-01");
    await user.clear(screen.getByLabelText("To date"));
    await user.type(screen.getByLabelText("To date"), "2026-06-01");

    expect(screen.getByText(/must be 90 days or fewer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find slots" })).toBeDisabled();
    expect(listAvailableSlotsMock).not.toHaveBeenCalled();
  });

  it("blocks a slot length outside the real backend range of 5-1440 minutes", async () => {
    const user = userEvent.setup();
    render(<AvailableSlotsPicker tenantId="t1" calendarId="cal1" timeZone="UTC" />);

    await user.clear(screen.getByLabelText("Slot length in minutes"));
    await user.type(screen.getByLabelText("Slot length in minutes"), "2");

    expect(screen.getByText(/between 5 and 1440 minutes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find slots" })).toBeDisabled();
  });

  it("shows an empty state when the backend returns no slots -- never invents any", async () => {
    listAvailableSlotsMock.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<AvailableSlotsPicker tenantId="t1" calendarId="cal1" timeZone="UTC" />);
    await user.click(screen.getByRole("button", { name: "Find slots" }));

    await waitFor(() => expect(screen.getByText("No available slots")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listAvailableSlotsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<AvailableSlotsPicker tenantId="t1" calendarId="cal1" timeZone="UTC" />);
    await user.click(screen.getByRole("button", { name: "Find slots" }));

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("selecting a slot reports the backend's own slot object, unmodified", async () => {
    const slot = { starts_at: "2026-03-02T08:00:00Z", ends_at: "2026-03-02T08:30:00Z" };
    listAvailableSlotsMock.mockResolvedValue([slot]);
    const onSelect = vi.fn();
    const user = userEvent.setup();

    render(
      <AvailableSlotsPicker
        tenantId="t1"
        calendarId="cal1"
        timeZone="UTC"
        onSelect={onSelect}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Find slots" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "08:00" })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "08:00" }));
    expect(onSelect).toHaveBeenCalledWith(slot);
  });
});
