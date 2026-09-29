import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AppointmentsWeekPage from "./page";
import { getWeekStart } from "@/lib/appointments/calendarWeek";

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/tenant-1/appointments",
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("@/lib/tenant/tenant-context", () => ({
  useTenant: () => ({ tenantId: "tenant-1" }),
}));

const {
  listAppointmentsMock,
  listCalendarEventsMock,
  listCalendarsMock,
  cancelAppointmentMock,
  createCalendarEventMock,
} = vi.hoisted(() => ({
  listAppointmentsMock: vi.fn(),
  listCalendarEventsMock: vi.fn(),
  listCalendarsMock: vi.fn(),
  cancelAppointmentMock: vi.fn(),
  createCalendarEventMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    listAppointments: listAppointmentsMock,
    listCalendarEvents: listCalendarEventsMock,
    listCalendars: listCalendarsMock,
    cancelAppointment: cancelAppointmentMock,
    createCalendarEvent: createCalendarEventMock,
  };
});

const { getContactMock } = vi.hoisted(() => ({ getContactMock: vi.fn() }));
vi.mock("@/lib/api/crm", () => ({ getContact: getContactMock }));

function setDefaultMocks() {
  listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
  listCalendarEventsMock.mockResolvedValue({ results: [], hasMore: false });
  listCalendarsMock.mockResolvedValue({ results: [], hasMore: false });
}

describe("AppointmentsWeekPage", () => {
  it("renders the Agenda heading and defaults to the Week view", async () => {
    setDefaultMocks();
    render(<AppointmentsWeekPage />);

    expect(screen.getByRole("heading", { name: "Agenda" })).toBeInTheDocument();
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalled());
    // A week label like "21–25 september 2026" -- an en dash between a
    // bare day number and the full end date.
    expect(screen.getByText(/–/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Week" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switching to the Month view re-queries a different, wider date range", async () => {
    setDefaultMocks();
    const user = userEvent.setup();
    render(<AppointmentsWeekPage />);
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: "Maand" }));
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalledTimes(2));

    const [, weekCallArgs] = listAppointmentsMock.mock.calls[0];
    const [, monthCallArgs] = listAppointmentsMock.mock.calls[1];
    expect(monthCallArgs.starts_after).not.toBe(weekCallArgs.starts_after);
    expect(screen.getByRole("button", { name: "Maand" })).toHaveAttribute("aria-pressed", "true");
  });

  it("moving to the next week and back to today re-queries a different date range", async () => {
    setDefaultMocks();
    const user = userEvent.setup();
    render(<AppointmentsWeekPage />);
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: "Volgende week" }));
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalledTimes(2));

    const [, secondCallArgs] = listAppointmentsMock.mock.calls[1];
    const [, firstCallArgs] = listAppointmentsMock.mock.calls[0];
    expect(secondCallArgs.starts_after).not.toBe(firstCallArgs.starts_after);

    await user.click(screen.getByRole("button", { name: "Vandaag" }));
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalledTimes(3));
    const [, thirdCallArgs] = listAppointmentsMock.mock.calls[2];
    expect(thirdCallArgs.starts_after).toBe(firstCallArgs.starts_after);
  });

  it("opens the real booking form in a dialog titled 'Afspraak inplannen' from the header action", async () => {
    setDefaultMocks();
    listCalendarsMock.mockResolvedValue({
      results: [{ id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "Europe/Amsterdam", created_at: "", updated_at: "" }],
      hasMore: false,
    });
    const user = userEvent.setup();
    render(<AppointmentsWeekPage />);
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "+ Nieuwe afspraak" }));

    const dialog = await screen.findByRole("dialog", { name: "Afspraak inplannen" });
    // The real BookAppointmentForm's own first step -- proof this is the
    // actual reused component, not a fabricated mockup-shaped form.
    expect(screen.getByText("1. Choose a calendar")).toBeInTheDocument();
    expect(dialog).toBeInTheDocument();
  });

  it("'+ Nieuw evenement' opens a real create dialog wired to the CalendarEvent API", async () => {
    setDefaultMocks();
    listCalendarsMock.mockResolvedValue({
      results: [{ id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "UTC", created_at: "", updated_at: "" }],
      hasMore: false,
    });
    createCalendarEventMock.mockResolvedValue({
      id: "e1",
      tenant_id: "tenant-1",
      calendar_id: "cal1",
      appointment_id: null,
      title: "Team meeting",
      description: null,
      starts_at: "2026-10-07T09:00:00.000Z",
      ends_at: "2026-10-07T10:00:00.000Z",
      created_at: "",
      updated_at: "",
    });
    const user = userEvent.setup();
    render(<AppointmentsWeekPage />);
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "+ Nieuw evenement" }));
    const dialog = await screen.findByRole("dialog", { name: "Nieuw evenement" });
    expect(dialog).toBeInTheDocument();

    await user.type(screen.getByLabelText("Titel"), "Team meeting");
    await user.click(screen.getByRole("button", { name: "Aanmaken" }));

    await waitFor(() => expect(createCalendarEventMock).toHaveBeenCalled());
    const [calledTenantId, input] = createCalendarEventMock.mock.calls[0];
    expect(calledTenantId).toBe("tenant-1");
    expect(input.title).toBe("Team meeting");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Nieuw evenement" })).not.toBeInTheDocument());
    // Reloads the active view's data after a successful create.
    expect(listAppointmentsMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("clicking a real calendar event in the Agenda/List view opens it for editing in a side panel", async () => {
    setDefaultMocks();
    listCalendarEventsMock.mockResolvedValue({
      results: [
        {
          id: "e1",
          tenant_id: "tenant-1",
          calendar_id: "cal1",
          appointment_id: null,
          title: "Team meeting",
          description: null,
          starts_at: new Date().toISOString(),
          ends_at: new Date(Date.now() + 30 * 60_000).toISOString(),
          created_at: "",
          updated_at: "",
        },
      ],
      hasMore: false,
    });
    const user = userEvent.setup();
    render(<AppointmentsWeekPage />);

    await user.click(screen.getByRole("button", { name: "Agenda" }));
    await waitFor(() => expect(screen.getByText("Team meeting")).toBeInTheDocument());
    await user.click(screen.getByText("Team meeting"));

    // An existing event opens the side panel (its title is the event's
    // own title), not the centered "Nieuw evenement" create dialog.
    const panel = await screen.findByRole("dialog", { name: "Team meeting" });
    expect(panel).toBeInTheDocument();
    expect(screen.getByLabelText("Titel")).toHaveValue("Team meeting");
  });

  it("opens the real appointment detail side panel when a real event is clicked", async () => {
    setDefaultMocks();
    listCalendarsMock.mockResolvedValue({
      results: [{ id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "Europe/Amsterdam", created_at: "", updated_at: "" }],
      hasMore: false,
    });
    // Monday of "today"'s week, not a raw `new Date()` -- CalendarWeekView
    // only ever renders Monday-Friday (lib/appointments/calendarWeek.ts's
    // own module docstring: a weekend timestamp is deliberately outside
    // its query window), so a real `new Date()` here is flaky depending on
    // which real-world weekday the suite happens to run on.
    const monday = getWeekStart(new Date());
    monday.setHours(10, 0, 0, 0);
    const startsAt = monday;
    const endsAt = new Date(startsAt.getTime() + 30 * 60_000);
    listAppointmentsMock.mockResolvedValue({
      results: [
        {
          id: "a1",
          tenant_id: "t1",
          calendar_id: "cal1",
          contact_id: "c1",
          starts_at: startsAt.toISOString(),
          ends_at: endsAt.toISOString(),
          status: "confirmed",
          created_at: "",
          updated_at: "",
        },
      ],
      hasMore: false,
    });
    getContactMock.mockResolvedValue({ id: "c1", first_name: "Jane", last_name: "Doe" });
    const user = userEvent.setup();

    render(<AppointmentsWeekPage />);
    await waitFor(() => expect(screen.getAllByText("Jane Doe").length).toBeGreaterThan(0));

    const [firstEvent] = screen.getAllByText("Jane Doe");
    await user.click(firstEvent);

    // AppointmentDetailPanel's own real content, proof the already-
    // fetched appointment (and its resolved contact/calendar) was handed
    // straight through, no fabricated re-lookup: the panel's title is the
    // contact's real name, and its body shows the real calendar name and
    // status -- never the raw appointment/calendar/contact id.
    const panel = await screen.findByRole("dialog", { name: "Jane Doe" });
    expect(within(panel).getByText("Hoofdagenda")).toBeInTheDocument();
    expect(within(panel).getByText("Bevestigd")).toBeInTheDocument();
    expect(within(panel).queryByText("a1")).not.toBeInTheDocument();
  });

  it("offers a real calendar selector once more than one calendar exists", async () => {
    setDefaultMocks();
    listCalendarsMock.mockResolvedValue({
      results: [
        { id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "UTC", created_at: "", updated_at: "" },
        { id: "cal2", tenant_id: "t1", name: "Verkoop", owner_user_id: "u1", timezone: "UTC", created_at: "", updated_at: "" },
      ],
      hasMore: false,
    });
    render(<AppointmentsWeekPage />);

    const select = await screen.findByRole("combobox");
    expect(select).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Alle agenda's" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Hoofdagenda" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Verkoop" })).toBeInTheDocument();
  });
});
