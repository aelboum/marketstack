import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppointmentCard } from "./AppointmentCard";
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

describe("AppointmentCard", () => {
  it("cancelling requires confirmation, then reports the cancelled row", async () => {
    cancelAppointmentMock.mockResolvedValue(appointment({ status: "cancelled" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<AppointmentCard tenantId="t1" appointment={appointment()} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Cancel appointment" }));
    expect(cancelAppointmentMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));

    await waitFor(() => expect(cancelAppointmentMock).toHaveBeenCalledWith("t1", "a1"));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "cancelled" }));
  });

  it("an already-cancelled appointment offers no cancel or reschedule action", () => {
    render(<AppointmentCard tenantId="t1" appointment={appointment({ status: "cancelled" })} />);

    expect(screen.queryByRole("button", { name: "Cancel appointment" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reschedule" })).not.toBeInTheDocument();
    expect(screen.getByText(/cancelled appointments cannot be rescheduled/i)).toBeInTheDocument();
  });

  it("surfaces the backend's own 'already cancelled' validation message verbatim", async () => {
    cancelAppointmentMock.mockRejectedValue(
      new ApiError("validation", "appointment a1 is already cancelled.", { status: 400 }),
    );
    const user = userEvent.setup();

    render(<AppointmentCard tenantId="t1" appointment={appointment()} />);
    await user.click(screen.getByRole("button", { name: "Cancel appointment" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));

    await waitFor(() =>
      expect(screen.getByText("appointment a1 is already cancelled.")).toBeInTheDocument(),
    );
  });

  it("does not hide a non-enumerating 404 behind a generic message", async () => {
    cancelAppointmentMock.mockRejectedValue(
      new ApiError("forbidden", "Not found, or you don't have access to it.", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<AppointmentCard tenantId="t1" appointment={appointment()} />);
    await user.click(screen.getByRole("button", { name: "Cancel appointment" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));

    await waitFor(() =>
      expect(screen.getByText("Not found, or you don't have access to it.")).toBeInTheDocument(),
    );
  });

  it("rescheduling sends timezone-aware instants, never the naive input value", async () => {
    rescheduleAppointmentMock.mockResolvedValue(appointment({ starts_at: "2026-03-03T09:00:00Z" }));
    const user = userEvent.setup();

    render(<AppointmentCard tenantId="t1" appointment={appointment()} />);
    await user.click(screen.getByRole("button", { name: "Reschedule" }));

    await user.clear(screen.getByLabelText("New start"));
    await user.type(screen.getByLabelText("New start"), "2026-03-03T10:00");
    await user.clear(screen.getByLabelText("New end"));
    await user.type(screen.getByLabelText("New end"), "2026-03-03T10:30");
    await user.click(screen.getByRole("button", { name: "Confirm new time" }));

    await waitFor(() => expect(rescheduleAppointmentMock).toHaveBeenCalled());
    const [, , body] = rescheduleAppointmentMock.mock.calls[0];
    expect(body.new_starts_at).toMatch(/Z$/);
    expect(body.new_ends_at).toMatch(/Z$/);
    expect(new Date(body.new_starts_at).getTime()).toBe(new Date("2026-03-03T10:00").getTime());
  });

  it("explains a 409 slot conflict as 'pick another time', not as a generic failure", async () => {
    rescheduleAppointmentMock.mockRejectedValue(
      new ApiError("server", "The requested slot is no longer available.", { status: 409 }),
    );
    const user = userEvent.setup();

    render(<AppointmentCard tenantId="t1" appointment={appointment()} />);
    await user.click(screen.getByRole("button", { name: "Reschedule" }));
    await user.click(screen.getByRole("button", { name: "Confirm new time" }));

    await waitFor(() =>
      expect(screen.getByText(/That time is no longer available/)).toBeInTheDocument(),
    );
  });

  it("marks a confirmed appointment as completed and reports the updated row", async () => {
    completeAppointmentMock.mockResolvedValue(appointment({ status: "completed" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<AppointmentCard tenantId="t1" appointment={appointment()} onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Afgerond" }));

    await waitFor(() => expect(completeAppointmentMock).toHaveBeenCalledWith("t1", "a1"));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }));
  });

  it("marks a confirmed appointment as no-show and reports the updated row", async () => {
    markAppointmentNoShowMock.mockResolvedValue(appointment({ status: "no_show" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<AppointmentCard tenantId="t1" appointment={appointment()} onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Niet verschenen" }));

    await waitFor(() => expect(markAppointmentNoShowMock).toHaveBeenCalledWith("t1", "a1"));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "no_show" }));
  });

  it("a completed appointment shows the Dutch terminal-state label and no actions", () => {
    render(<AppointmentCard tenantId="t1" appointment={appointment({ status: "completed" })} />);

    expect(screen.getByText("Afgerond")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel appointment" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reschedule" })).not.toBeInTheDocument();
    expect(
      screen.getByText(/definitieve status van deze afspraak/i),
    ).toBeInTheDocument();
  });

  it("a no-show appointment shows the Dutch terminal-state label and no actions", () => {
    render(<AppointmentCard tenantId="t1" appointment={appointment({ status: "no_show" })} />);

    expect(screen.getByText("Niet verschenen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel appointment" })).not.toBeInTheDocument();
  });

  it("surfaces a failed complete/no-show attempt without hiding the backend message", async () => {
    completeAppointmentMock.mockRejectedValue(
      new ApiError(
        "validation",
        "appointment a1 cannot be completed while status='cancelled' (only 'confirmed' appointments can be).",
        { status: 400 },
      ),
    );
    const user = userEvent.setup();

    render(<AppointmentCard tenantId="t1" appointment={appointment()} />);
    await user.click(screen.getByRole("button", { name: "Afgerond" }));

    await waitFor(() =>
      expect(screen.getByText(/cannot be completed while status=/)).toBeInTheDocument(),
    );
  });
});
