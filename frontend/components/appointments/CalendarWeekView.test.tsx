import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CalendarWeekView } from "./CalendarWeekView";
import { getWeekStart } from "@/lib/appointments/calendarWeek";
import { ApiError } from "@/lib/api/errors";

const { listAppointmentsMock, listCalendarEventsMock, listCalendarsMock, getContactMock } = vi.hoisted(
  () => ({
    listAppointmentsMock: vi.fn(),
    listCalendarEventsMock: vi.fn(),
    listCalendarsMock: vi.fn(),
    getContactMock: vi.fn(),
  }),
);
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    listAppointments: listAppointmentsMock,
    listCalendarEvents: listCalendarEventsMock,
    listCalendars: listCalendarsMock,
  };
});
vi.mock("@/lib/api/crm", () => ({ getContact: getContactMock }));
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const WEEK_START = getWeekStart(new Date(2026, 8, 22)); // 2026-09-21 (Monday)

function appointment(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "a1",
    tenant_id: "t1",
    calendar_id: "cal1",
    contact_id: "c1",
    starts_at: new Date(2026, 8, 22, 9, 0).toISOString(),
    ends_at: new Date(2026, 8, 22, 9, 30).toISOString(),
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
    starts_at: new Date(2026, 8, 22, 11, 0).toISOString(),
    ends_at: new Date(2026, 8, 22, 11, 30).toISOString(),
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function setDefaultMocks() {
  listCalendarsMock.mockResolvedValue({
    results: [
      { id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "Europe/Amsterdam", created_at: "", updated_at: "" },
      { id: "cal2", tenant_id: "t1", name: "Verkoop", owner_user_id: "u1", timezone: "Europe/Amsterdam", created_at: "", updated_at: "" },
    ],
    hasMore: false,
  });
  getContactMock.mockResolvedValue({ id: "c1", first_name: "Jane", last_name: "Doe" });
  listCalendarEventsMock.mockResolvedValue({ results: [], hasMore: false });
  listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
}

describe("CalendarWeekView", () => {
  // --- Existing appointment behaviour, preserved -----------------------------

  it("shows loading, then a real appointment as an event with the resolved contact name and calendar name", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getAllByText("Jane Doe").length).toBeGreaterThan(0));
    expect(screen.getAllByText(/Hoofdagenda/).length).toBeGreaterThan(0);
    expect(listAppointmentsMock).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({ starts_after: WEEK_START.toISOString() }),
    );
  });

  it("calls onItemClick with an appointment-kind item when an appointment is clicked", async () => {
    setDefaultMocks();
    const theAppointment = appointment();
    listAppointmentsMock.mockResolvedValue({ results: [theAppointment], hasMore: false });
    const onItemClick = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarWeekView
        tenantId="t1"
        weekStart={WEEK_START}
        isToday={() => false}
        onItemClick={onItemClick}
      />,
    );

    await waitFor(() => expect(screen.getAllByText("Jane Doe").length).toBeGreaterThan(0));
    const [firstEvent] = screen.getAllByText("Jane Doe");
    await user.click(firstEvent);

    expect(onItemClick).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "appointment", appointment: theAppointment }),
    );
  });

  it("shows an honest 'no appointments' state per day when the week is genuinely empty", async () => {
    setDefaultMocks();

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getAllByText("Geen afspraken").length).toBe(5));
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("queries the visible Monday-Friday window (existing week boundaries unchanged)", async () => {
    setDefaultMocks();
    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalled());
    const [, args] = listAppointmentsMock.mock.calls[0];
    const expectedEnd = new Date(WEEK_START);
    expectedEnd.setDate(expectedEnd.getDate() + 5);
    expect(args.starts_after).toBe(WEEK_START.toISOString());
    expect(args.starts_before).toBe(expectedEnd.toISOString());
  });

  // --- Generic CalendarEvents -------------------------------------------------

  it("shows a real CalendarEvent at the correct day/time with the generic-event treatment", async () => {
    setDefaultMocks();
    listCalendarEventsMock.mockResolvedValue({ results: [calendarEvent()], hasMore: false });

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getAllByText("Team meeting").length).toBeGreaterThan(0));
    expect(screen.getAllByText(/Agendapunt/).length).toBeGreaterThan(0);
    expect(listCalendarEventsMock).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({
        starts_after: WEEK_START.toISOString(),
        calendar_id: undefined,
      }),
    );
  });

  it("calls onItemClick with an event-kind item (never appointment management) when a generic event is clicked", async () => {
    setDefaultMocks();
    const theEvent = calendarEvent();
    listCalendarEventsMock.mockResolvedValue({ results: [theEvent], hasMore: false });
    const onItemClick = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={onItemClick} />,
    );

    await waitFor(() => expect(screen.getAllByText("Team meeting").length).toBeGreaterThan(0));
    const [firstEvent] = screen.getAllByText("Team meeting");
    await user.click(firstEvent);

    expect(onItemClick).toHaveBeenCalledWith(expect.objectContaining({ kind: "event", event: theEvent }));
    expect(onItemClick).not.toHaveBeenCalledWith(expect.objectContaining({ kind: "appointment" }));
  });

  it("supports multiple generic events in the same week", async () => {
    setDefaultMocks();
    listCalendarEventsMock.mockResolvedValue({
      results: [
        calendarEvent({ id: "e1", title: "Team meeting" }),
        calendarEvent({ id: "e2", title: "Planning", starts_at: new Date(2026, 8, 23, 14, 0).toISOString(), ends_at: new Date(2026, 8, 23, 15, 0).toISOString() }),
      ],
      hasMore: false,
    });

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getAllByText("Team meeting").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Planning").length).toBeGreaterThan(0);
  });

  // --- Mixed data --------------------------------------------------------------

  it("renders an appointment and a generic event together in the same day, each with its own treatment", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });
    listCalendarEventsMock.mockResolvedValue({ results: [calendarEvent()], hasMore: false });

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getAllByText("Jane Doe").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Team meeting").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Bevestigd/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Agendapunt/).length).toBeGreaterThan(0);
  });

  it("does not render an appointment-backed CalendarEvent as a second item", async () => {
    setDefaultMocks();
    const theAppointment = appointment({ id: "a1" });
    listAppointmentsMock.mockResolvedValue({ results: [theAppointment], hasMore: false });
    listCalendarEventsMock.mockResolvedValue({
      results: [calendarEvent({ id: "e1", appointment_id: "a1", title: "Should not render" })],
      hasMore: false,
    });

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getAllByText("Jane Doe").length).toBeGreaterThan(0));
    expect(screen.queryByText("Should not render")).not.toBeInTheDocument();
  });

  // --- Calendar filtering -------------------------------------------------------

  it("filters both appointments and generic events to the selected calendar", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({
      results: [appointment({ id: "a1", calendar_id: "cal1" }), appointment({ id: "a2", calendar_id: "cal2", contact_id: null })],
      hasMore: false,
    });
    listCalendarEventsMock.mockResolvedValue({ results: [calendarEvent({ id: "e1", calendar_id: "cal2" })], hasMore: false });

    render(
      <CalendarWeekView
        tenantId="t1"
        weekStart={WEEK_START}
        calendarId="cal2"
        isToday={() => false}
        onItemClick={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getAllByText("Team meeting").length).toBeGreaterThan(0));
    expect(screen.queryByText("Jane Doe")).not.toBeInTheDocument();
    expect(listCalendarEventsMock).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({ calendar_id: "cal2" }),
    );
  });

  // --- Date boundaries -----------------------------------------------------------

  it("renders an event at the very start of the visible week (Monday)", async () => {
    setDefaultMocks();
    listCalendarEventsMock.mockResolvedValue({
      results: [calendarEvent({ id: "mon", title: "Monday item", starts_at: new Date(2026, 8, 21, 9, 0).toISOString(), ends_at: new Date(2026, 8, 21, 9, 30).toISOString() })],
      hasMore: false,
    });

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getAllByText("Monday item").length).toBeGreaterThan(0));
  });

  it("renders an event at the very end of the visible week (Friday)", async () => {
    setDefaultMocks();
    listCalendarEventsMock.mockResolvedValue({
      results: [calendarEvent({ id: "fri", title: "Friday item", starts_at: new Date(2026, 8, 25, 16, 0).toISOString(), ends_at: new Date(2026, 8, 25, 16, 30).toISOString() })],
      hasMore: false,
    });

    render(
      <CalendarWeekView tenantId="t1" weekStart={WEEK_START} isToday={() => false} onItemClick={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getAllByText("Friday item").length).toBeGreaterThan(0));
  });
});
