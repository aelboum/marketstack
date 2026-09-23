import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CalendarAgendaListView } from "./CalendarAgendaListView";

const { listAppointmentsMock, listCalendarsMock, getContactMock } = vi.hoisted(() => ({
  listAppointmentsMock: vi.fn(),
  listCalendarsMock: vi.fn(),
  getContactMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return { ...actual, listAppointments: listAppointmentsMock, listCalendars: listCalendarsMock };
});
vi.mock("@/lib/api/crm", () => ({ getContact: getContactMock }));
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const TODAY = new Date();

function appointment(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "a1",
    tenant_id: "t1",
    calendar_id: "cal1",
    contact_id: "c1",
    starts_at: new Date(TODAY.getFullYear(), TODAY.getMonth(), TODAY.getDate(), 9, 0).toISOString(),
    ends_at: new Date(TODAY.getFullYear(), TODAY.getMonth(), TODAY.getDate(), 9, 30).toISOString(),
    status: "confirmed",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function setDefaultMocks() {
  listCalendarsMock.mockResolvedValue({
    results: [{ id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "UTC", created_at: "", updated_at: "" }],
    hasMore: false,
  });
  getContactMock.mockResolvedValue({ id: "c1", first_name: "Jane", last_name: "Doe" });
}

describe("CalendarAgendaListView", () => {
  it("groups a real appointment under 'Vandaag'", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [appointment()], hasMore: false });

    render(
      <CalendarAgendaListView
        tenantId="t1"
        anchorDate={TODAY}
        onEventClick={vi.fn()}
        onNewAppointment={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    expect(screen.getByText("Vandaag")).toBeInTheDocument();
  });

  it("calls onEventClick with the real appointment object when a row is clicked", async () => {
    setDefaultMocks();
    const theAppointment = appointment();
    listAppointmentsMock.mockResolvedValue({ results: [theAppointment], hasMore: false });
    const onEventClick = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarAgendaListView
        tenantId="t1"
        anchorDate={TODAY}
        onEventClick={onEventClick}
        onNewAppointment={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    await user.click(screen.getByText("Jane Doe"));

    expect(onEventClick).toHaveBeenCalledWith(theAppointment);
  });

  it("shows an honest empty state with a real 'Nieuwe afspraak' action when the window has nothing", async () => {
    setDefaultMocks();
    listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
    const onNewAppointment = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarAgendaListView
        tenantId="t1"
        anchorDate={TODAY}
        onEventClick={vi.fn()}
        onNewAppointment={onNewAppointment}
      />,
    );

    await waitFor(() => expect(screen.getByText("Geen afspraken gepland")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Nieuwe afspraak" }));
    expect(onNewAppointment).toHaveBeenCalled();
  });
});
