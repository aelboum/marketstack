import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BookAppointmentForm } from "./BookAppointmentForm";
import { ApiError } from "@/lib/api/errors";
import { formatTimeInTimeZone } from "@/lib/appointments/datetime";

const { listCalendarsMock, listAvailableSlotsMock, bookAppointmentMock } = vi.hoisted(() => ({
  listCalendarsMock: vi.fn(),
  listAvailableSlotsMock: vi.fn(),
  bookAppointmentMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    listCalendars: listCalendarsMock,
    listAvailableSlots: listAvailableSlotsMock,
    bookAppointment: bookAppointmentMock,
  };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const CALENDAR = {
  id: "cal1",
  tenant_id: "t1",
  name: "Sales calls",
  owner_user_id: "u1",
  timezone: "UTC",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
const SLOT = { starts_at: "2026-03-02T09:00:00Z", ends_at: "2026-03-02T09:30:00Z" };

// The slot button is labelled with `formatTimeInTimeZone()`, which formats in
// the *runtime's* default locale so each viewer sees their own convention.
// That default belongs to the machine, not the project (a workstation here
// resolves to 24-hour "09:00"; the CI runner resolves to 12-hour "9:00 AM"),
// so the expected label is derived through the same helper rather than
// hard-coded. CALENDAR's zone is UTC, so the slot's instant is also its
// wall-clock time.
const SLOT_LABEL = () => formatTimeInTimeZone(SLOT.starts_at, CALENDAR.timezone);

async function pickCalendarAndSlot(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getByLabelText("Calendar")).toBeInTheDocument());
  await user.selectOptions(screen.getByLabelText("Calendar"), "cal1");
  await user.click(screen.getByRole("button", { name: "Find slots" }));
  const slotLabel = SLOT_LABEL();
  await waitFor(() => expect(screen.getByRole("button", { name: slotLabel })).toBeInTheDocument());
  await user.click(screen.getByRole("button", { name: slotLabel }));
}

describe("BookAppointmentForm", () => {
  it("books using the backend's own slot object, never a client-composed time", async () => {
    listCalendarsMock.mockResolvedValue({ results: [CALENDAR], hasMore: false });
    listAvailableSlotsMock.mockResolvedValue([SLOT]);
    bookAppointmentMock.mockResolvedValue({ id: "a1", status: "confirmed" });
    const onBooked = vi.fn();
    const user = userEvent.setup();

    render(<BookAppointmentForm tenantId="t1" onBooked={onBooked} />);
    await pickCalendarAndSlot(user);

    await user.type(screen.getByLabelText("Email"), "jane@example.com");
    await user.type(screen.getByLabelText("First name"), "Jane");
    await user.type(screen.getByLabelText("Last name"), "Doe");
    await user.click(screen.getByRole("button", { name: "Confirm booking" }));

    await waitFor(() =>
      expect(bookAppointmentMock).toHaveBeenCalledWith("t1", {
        calendar_id: "cal1",
        contact_email: "jane@example.com",
        contact_first_name: "Jane",
        contact_last_name: "Doe",
        contact_phone: null,
        starts_at: SLOT.starts_at,
        ends_at: SLOT.ends_at,
      }),
    );
    expect(onBooked).toHaveBeenCalledWith({ id: "a1", status: "confirmed" });
  });

  it("offers no contact form until a real slot has been chosen", async () => {
    listCalendarsMock.mockResolvedValue({ results: [CALENDAR], hasMore: false });
    listAvailableSlotsMock.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<BookAppointmentForm tenantId="t1" onBooked={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText("Calendar")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Calendar"), "cal1");

    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm booking" })).not.toBeInTheDocument();
  });

  it("explains a 409 as 'the slot was taken', not as a generic failure", async () => {
    listCalendarsMock.mockResolvedValue({ results: [CALENDAR], hasMore: false });
    listAvailableSlotsMock.mockResolvedValue([SLOT]);
    bookAppointmentMock.mockRejectedValue(
      new ApiError("server", "The requested slot is no longer available.", { status: 409 }),
    );
    const user = userEvent.setup();

    render(<BookAppointmentForm tenantId="t1" onBooked={vi.fn()} />);
    await pickCalendarAndSlot(user);
    await user.type(screen.getByLabelText("Email"), "jane@example.com");
    await user.type(screen.getByLabelText("First name"), "Jane");
    await user.type(screen.getByLabelText("Last name"), "Doe");
    await user.click(screen.getByRole("button", { name: "Confirm booking" }));

    await waitFor(() =>
      expect(screen.getByText(/That slot was taken while you were filling this in/)).toBeInTheDocument(),
    );
  });

  it("shows an empty state, not a booking form, when the tenant has no calendars", async () => {
    listCalendarsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<BookAppointmentForm tenantId="t1" onBooked={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("No calendars yet")).toBeInTheDocument());
    expect(screen.queryByLabelText("Calendar")).not.toBeInTheDocument();
  });

  it("shows the non-enumerating permission-denied state when calendars are not readable", async () => {
    listCalendarsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<BookAppointmentForm tenantId="t1" onBooked={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
