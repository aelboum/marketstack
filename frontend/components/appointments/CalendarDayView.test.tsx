import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CalendarDayView } from "./CalendarDayView";

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

const DAY = new Date(2026, 8, 22); // Tuesday

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
      { id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "UTC", created_at: "", updated_at: "" },
      { id: "cal2", tenant_id: "t1", name: "Verkoop", owner_user_id: "u1", timezone: "UTC", created_at: "", updated_at: "" },
    ],
    hasMore: false,
  });
  getContactMock.mockResolvedValue({ id: "c1", first_name: "Jane", last_name: "Doe" });
  listCalendarEventsMock.mockResolvedValue({ results: [], hasMore: false });
  listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
}

describe("CalendarDayView", () => {
  it("shows a real appointment as an event with the resolved contact name", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });

    render(
      <CalendarDayView tenantId="t1" day={DAY} onItemClick={vi.fn()} onNewAppointment={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    expect(listAppointmentsMock).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({ starts_after: new Date(2026, 8, 22).toISOString() }),
    );
  });

  it("shows a real CalendarEvent alongside an appointment, visually distinguished", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });
    // An hour long specifically: a sub-hour event's own row layout has no
    // room for the "· where · Agendapunt" suffix this test asserts on
    // (see CalendarDayView.tsx's own `layout.direction === "row"` case) --
    // this test is about the label/tone existing at all, not about the
    // sub-hour layout, which has its own coverage below.
    listCalendarEventsMock.mockResolvedValue({
      results: [calendarEvent({ ends_at: new Date(2026, 8, 22, 12, 0).toISOString() })],
      hasMore: false,
    });

    render(
      <CalendarDayView tenantId="t1" day={DAY} onItemClick={vi.fn()} onNewAppointment={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    expect(screen.getByText("Team meeting")).toBeInTheDocument();
    expect(screen.getByText(/Agendapunt/)).toBeInTheDocument();
    expect(listCalendarEventsMock).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({
        starts_after: new Date(2026, 8, 22).toISOString(),
        calendar_id: undefined,
      }),
    );
  });

  it("lays a sub-hour appointment's title and time side by side, dropping the status suffix", async () => {
    // The default `appointment()` fixture is 09:00-09:30 -- 30 minutes,
    // squarely inside the row layout's own sub-hour threshold.
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });
    listCalendarEventsMock.mockResolvedValue({ results: [], hasMore: false });

    render(
      <CalendarDayView tenantId="t1" day={DAY} onItemClick={vi.fn()} onNewAppointment={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    // Scoped to the event button itself -- "09:00" alone is ambiguous
    // against the hour-column's own "09:00" row label.
    const card = screen.getByText("Jane Doe").closest("button")!;
    expect(within(card).getByText("09:00")).toBeInTheDocument();
    expect(within(card).queryByText(/Bevestigd/)).not.toBeInTheDocument();
  });

  it("calls onItemClick with an appointment-kind item when an appointment is clicked", async () => {
    setDefaultMocks();
    const theAppointment = appointment();
    listAppointmentsMock.mockResolvedValue({ results: [theAppointment], hasMore: false });
    const onItemClick = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarDayView tenantId="t1" day={DAY} onItemClick={onItemClick} onNewAppointment={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    await user.click(screen.getByText("Jane Doe"));

    expect(onItemClick).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "appointment", appointment: theAppointment }),
    );
  });

  it("calls onItemClick with an event-kind item when a calendar event is clicked", async () => {
    setDefaultMocks();
    const theEvent = calendarEvent();
    listCalendarEventsMock.mockResolvedValue({ results: [theEvent], hasMore: false });
    const onItemClick = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarDayView tenantId="t1" day={DAY} onItemClick={onItemClick} onNewAppointment={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText("Team meeting")).toBeInTheDocument());
    await user.click(screen.getByText("Team meeting"));

    expect(onItemClick).toHaveBeenCalledWith(expect.objectContaining({ kind: "event", event: theEvent }));
  });

  it("filters out appointments from other calendars when calendarId is set", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({
      results: [appointment({ id: "a1", calendar_id: "cal1" }), appointment({ id: "a2", calendar_id: "cal2" })],
      hasMore: false,
    });

    render(
      <CalendarDayView
        tenantId="t1"
        day={DAY}
        calendarId="cal2"
        onItemClick={vi.fn()}
        onNewAppointment={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getAllByText("Jane Doe")).toHaveLength(1));
    expect(listCalendarEventsMock).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({ calendar_id: "cal2" }),
    );
  });

  it("shows an honest empty state with a real 'Nieuwe afspraak' action when the day has nothing", async () => {
    setDefaultMocks();
    const onNewAppointment = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarDayView tenantId="t1" day={DAY} onItemClick={vi.fn()} onNewAppointment={onNewAppointment} />,
    );

    await waitFor(() => expect(screen.getByText("Geen afspraken op deze dag")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Nieuwe afspraak" }));
    expect(onNewAppointment).toHaveBeenCalled();
  });
});
