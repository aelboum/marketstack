import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppointmentDetailPanel } from "./AppointmentDetailPanel";
import { ApiError } from "@/lib/api/errors";

const {
  cancelAppointmentMock,
  rescheduleAppointmentMock,
  completeAppointmentMock,
  markAppointmentNoShowMock,
} = vi.hoisted(() => ({
  cancelAppointmentMock: vi.fn(),
  rescheduleAppointmentMock: vi.fn(),
  completeAppointmentMock: vi.fn(),
  markAppointmentNoShowMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    cancelAppointment: cancelAppointmentMock,
    rescheduleAppointment: rescheduleAppointmentMock,
    completeAppointment: completeAppointmentMock,
    markAppointmentNoShow: markAppointmentNoShowMock,
  };
});

const { getContactMock } = vi.hoisted(() => ({ getContactMock: vi.fn() }));
vi.mock("@/lib/api/crm", () => ({ getContact: getContactMock }));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const CALENDARS = [
  { id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "UTC", created_at: "", updated_at: "" },
];

function appointment(overrides: Record<string, unknown> = {}) {
  return {
    id: "a1",
    tenant_id: "t1",
    calendar_id: "cal1",
    contact_id: "ct1",
    starts_at: "2026-03-02T09:00:00Z",
    ends_at: "2026-03-02T09:30:00Z",
    status: "confirmed" as const,
    created_at: "2026-03-01T00:00:00Z",
    updated_at: "2026-03-01T00:00:00Z",
    ...overrides,
  };
}

describe("AppointmentDetailPanel", () => {
  beforeEach(() => {
    getContactMock.mockClear();
    getContactMock.mockResolvedValue({ id: "ct1", first_name: "Jane", last_name: "Doe" });
  });

  it("shows the contact's real name as the title, the status tag, and the real calendar name", async () => {
    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole("heading", { name: "Jane Doe" })).toBeInTheDocument());
    expect(screen.getByText("Bevestigd")).toBeInTheDocument();
    expect(screen.getByText("Hoofdagenda")).toBeInTheDocument();
    expect(screen.queryByText("a1")).not.toBeInTheDocument();
    expect(screen.queryByText("cal1")).not.toBeInTheDocument();
  });

  it("links to the real CRM contact profile", async () => {
    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const link = await screen.findByRole("link", { name: "Klantprofiel" });
    expect(link).toHaveAttribute("href", "/t/t1/crm/contacts/ct1");
  });

  it("cancelling asks in the footer itself, in place, before calling the API", async () => {
    cancelAppointmentMock.mockResolvedValue(appointment({ status: "cancelled" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={onChanged}
        onClose={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Afspraak annuleren" }));
    expect(cancelAppointmentMock).not.toHaveBeenCalled();
    expect(screen.getByText("Deze afspraak annuleren?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Ja, annuleren" }));

    await waitFor(() => expect(cancelAppointmentMock).toHaveBeenCalledWith("t1", "a1"));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "cancelled" }));
  });

  it("keeping the appointment dismisses the inline confirmation without calling the API", async () => {
    const user = userEvent.setup();

    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Afspraak annuleren" }));
    await user.click(screen.getByRole("button", { name: "Behouden" }));

    expect(cancelAppointmentMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Afspraak annuleren" })).toBeInTheDocument();
  });

  it("surfaces the backend's own cancellation error message verbatim", async () => {
    cancelAppointmentMock.mockRejectedValue(
      new ApiError("validation", "appointment a1 is already cancelled.", { status: 400 }),
    );
    const user = userEvent.setup();

    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Afspraak annuleren" }));
    await user.click(screen.getByRole("button", { name: "Ja, annuleren" }));

    await waitFor(() =>
      expect(screen.getByText("appointment a1 is already cancelled.")).toBeInTheDocument(),
    );
  });

  it("rescheduling sends timezone-aware instants, never the naive input value", async () => {
    rescheduleAppointmentMock.mockResolvedValue(appointment({ starts_at: "2026-03-03T09:00:00Z" }));
    const user = userEvent.setup();

    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Verzetten" }));
    await user.clear(screen.getByLabelText("Nieuw begin"));
    await user.type(screen.getByLabelText("Nieuw begin"), "2026-03-03T10:00");
    await user.clear(screen.getByLabelText("Nieuw einde"));
    await user.type(screen.getByLabelText("Nieuw einde"), "2026-03-03T10:30");
    await user.click(screen.getByRole("button", { name: "Bevestig nieuwe tijd" }));

    await waitFor(() => expect(rescheduleAppointmentMock).toHaveBeenCalled());
    const [, , body] = rescheduleAppointmentMock.mock.calls[0];
    expect(body.new_starts_at).toMatch(/Z$/);
    expect(new Date(body.new_starts_at).getTime()).toBe(new Date("2026-03-03T10:00").getTime());
  });

  it("marks a confirmed appointment as completed and reports the updated row", async () => {
    completeAppointmentMock.mockResolvedValue(appointment({ status: "completed" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={onChanged}
        onClose={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Markeer als afgerond" }));

    await waitFor(() => expect(completeAppointmentMock).toHaveBeenCalledWith("t1", "a1"));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }));
  });

  it("marks a confirmed appointment as no-show and reports the updated row", async () => {
    markAppointmentNoShowMock.mockResolvedValue(appointment({ status: "no_show" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={onChanged}
        onClose={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Niet verschenen" }));

    await waitFor(() => expect(markAppointmentNoShowMock).toHaveBeenCalledWith("t1", "a1"));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "no_show" }));
  });

  it("a cancelled appointment offers no actions and shows the terminal-state notice", async () => {
    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment({ status: "cancelled" })}
        calendars={CALENDARS}
        onChanged={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("Geannuleerd")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Afspraak annuleren" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verzetten" })).not.toBeInTheDocument();
    expect(
      screen.getByText(/definitieve status van deze afspraak/i),
    ).toBeInTheDocument();
  });

  it("an appointment with no linked contact shows the fallback title and no customer section", async () => {
    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment({ contact_id: null })}
        calendars={CALENDARS}
        onChanged={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Onbekende klant" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Klantprofiel" })).not.toBeInTheDocument();
    expect(getContactMock).not.toHaveBeenCalled();
  });

  it("closing calls onClose", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <AppointmentDetailPanel
        tenantId="t1"
        appointment={appointment()}
        calendars={CALENDARS}
        onChanged={vi.fn()}
        onClose={onClose}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Sluiten" }));
    expect(onClose).toHaveBeenCalled();
  });
});
