import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
    listCalendarEventsMock.mockResolvedValue({ results: [calendarEvent()], hasMore: false });

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
