import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CalendarMonthView } from "./CalendarMonthView";

const { listAppointmentsMock, listCalendarEventsMock, listCalendarsMock } = vi.hoisted(() => ({
  listAppointmentsMock: vi.fn(),
  listCalendarEventsMock: vi.fn(),
  listCalendarsMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    listAppointments: listAppointmentsMock,
    listCalendarEvents: listCalendarEventsMock,
    listCalendars: listCalendarsMock,
  };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const MONTH_DATE = new Date(2026, 8, 22); // September 2026

function appointment(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "a1",
    tenant_id: "t1",
    calendar_id: "cal1",
    contact_id: "c1",
    starts_at: new Date(2026, 8, 10, 9, 0).toISOString(),
    ends_at: new Date(2026, 8, 10, 9, 30).toISOString(),
    status: "confirmed",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function calendarEvent(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "e1",
    tenant_id: "t1",
    calendar_id: "cal1",
    appointment_id: null,
    title: "Team meeting",
    description: null,
    starts_at: new Date(2026, 8, 12, 9, 0).toISOString(),
    ends_at: new Date(2026, 8, 12, 9, 30).toISOString(),
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function setDefaultMocks() {
  listCalendarsMock.mockResolvedValue({ results: [], hasMore: false });
  listCalendarEventsMock.mockResolvedValue({ results: [], hasMore: false });
  listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
}

describe("CalendarMonthView", () => {
  it("queries the full 6-week grid range, not just the calendar month", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });

    render(
      <CalendarMonthView
        tenantId="t1"
        monthDate={MONTH_DATE}
        onSelectDay={vi.fn()}
        onNewAppointment={vi.fn()}
      />,
    );

    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalled());
    const [, args] = listAppointmentsMock.mock.calls[0];
    // September 2026 starts on a Tuesday -- the grid must begin on the
    // Monday before it (31 August).
    expect(args.starts_after).toBe(new Date(2026, 7, 31).toISOString());
  });

  it("calls onSelectDay with the clicked date", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });
    const onSelectDay = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarMonthView
        tenantId="t1"
        monthDate={MONTH_DATE}
        onSelectDay={onSelectDay}
        onNewAppointment={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: /15 september/i })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /15 september/i }));

    expect(onSelectDay).toHaveBeenCalledTimes(1);
    const [selected] = onSelectDay.mock.calls[0];
    expect(selected.getDate()).toBe(15);
  });

  it("shows a real density dot for a day with an appointment", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });

    render(
      <CalendarMonthView
        tenantId="t1"
        monthDate={MONTH_DATE}
        onSelectDay={vi.fn()}
        onNewAppointment={vi.fn()}
      />,
    );

    const cell = await screen.findByRole("button", { name: /10 september/i });
    await waitFor(() => expect(cell.querySelector("span")).toBeTruthy());
  });

  it("shows a real density dot for a day with only a generic calendar event", async () => {
    setDefaultMocks();
    listCalendarEventsMock.mockResolvedValue({ results: [calendarEvent()], hasMore: false });

    render(
      <CalendarMonthView
        tenantId="t1"
        monthDate={MONTH_DATE}
        onSelectDay={vi.fn()}
        onNewAppointment={vi.fn()}
      />,
    );

    const cell = await screen.findByRole("button", { name: /12 september/i });
    await waitFor(() => expect(cell.querySelector("span")).toBeTruthy());
  });

  it("shows an honest empty state when the whole month is genuinely empty", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
    const onNewAppointment = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarMonthView
        tenantId="t1"
        monthDate={MONTH_DATE}
        onSelectDay={vi.fn()}
        onNewAppointment={onNewAppointment}
      />,
    );

    await waitFor(() => expect(screen.getByText("Geen activiteiten gepland")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Nieuwe afspraak" }));
    expect(onNewAppointment).toHaveBeenCalled();
  });
});
