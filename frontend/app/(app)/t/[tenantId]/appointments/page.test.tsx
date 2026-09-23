import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AppointmentsWeekPage from "./page";

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

const { listAppointmentsMock, listCalendarsMock, cancelAppointmentMock } = vi.hoisted(() => ({
  listAppointmentsMock: vi.fn(),
  listCalendarsMock: vi.fn(),
  cancelAppointmentMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    listAppointments: listAppointmentsMock,
    listCalendars: listCalendarsMock,
    cancelAppointment: cancelAppointmentMock,
  };
});

const { getContactMock } = vi.hoisted(() => ({ getContactMock: vi.fn() }));
vi.mock("@/lib/api/crm", () => ({ getContact: getContactMock }));

function setDefaultMocks() {
  listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
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
    listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
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

  it("'+ Nieuw evenement' opens an honest not-yet-available notice, not a fake create flow", async () => {
    setDefaultMocks();
    const user = userEvent.setup();
    render(<AppointmentsWeekPage />);
    await waitFor(() => expect(listAppointmentsMock).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "+ Nieuw evenement" }));

    const dialog = await screen.findByRole("dialog", { name: "Nieuw evenement" });
    expect(dialog).toHaveTextContent(/volgende fase/i);
    // No form fields are offered -- nothing here can actually be submitted.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sluiten" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Nieuw evenement" })).not.toBeInTheDocument());
  });

  it("opens the real AppointmentCard in a manage dialog when a real event is clicked", async () => {
    listCalendarsMock.mockResolvedValue({
      results: [{ id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "Europe/Amsterdam", created_at: "", updated_at: "" }],
      hasMore: false,
    });
    listAppointmentsMock.mockResolvedValue({
      results: [
        {
          id: "a1",
          tenant_id: "t1",
          calendar_id: "cal1",
          contact_id: "c1",
          starts_at: new Date().toISOString(),
          ends_at: new Date(Date.now() + 30 * 60_000).toISOString(),
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

    const dialog = await screen.findByRole("dialog", { name: "Afspraak beheren" });
    // AppointmentCard's own real content -- the appointment id, proof
    // the already-fetched object was handed straight through, no
    // fabricated re-lookup.
    expect(screen.getByText("a1")).toBeInTheDocument();
    expect(dialog).toBeInTheDocument();
  });

  it("offers a real calendar selector once more than one calendar exists", async () => {
    listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
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
