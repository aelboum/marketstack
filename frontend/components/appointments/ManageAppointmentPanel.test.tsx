import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManageAppointmentPanel } from "./ManageAppointmentPanel";
import { ApiError } from "@/lib/api/errors";

const { cancelAppointmentMock } = vi.hoisted(() => ({ cancelAppointmentMock: vi.fn() }));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return { ...actual, cancelAppointment: cancelAppointmentMock };
});

describe("ManageAppointmentPanel", () => {
  it("explains why there is no appointment list to browse", () => {
    render(<ManageAppointmentPanel tenantId="t1" />);
    expect(
      screen.getByText(/no endpoint for listing or reading appointments/),
    ).toBeInTheDocument();
  });

  it("requires confirmation, then cancels by id and shows the returned row", async () => {
    cancelAppointmentMock.mockResolvedValue({
      id: "a1",
      tenant_id: "t1",
      calendar_id: "cal1",
      contact_id: "ct1",
      starts_at: "2026-03-02T09:00:00Z",
      ends_at: "2026-03-02T09:30:00Z",
      status: "cancelled",
      created_at: "2026-03-01T00:00:00Z",
      updated_at: "2026-03-01T00:00:00Z",
    });
    const user = userEvent.setup();

    render(<ManageAppointmentPanel tenantId="t1" />);
    await user.type(screen.getByLabelText("Appointment ID"), "a1");
    await user.click(screen.getByRole("button", { name: "Cancel appointment" }));
    expect(cancelAppointmentMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));

    await waitFor(() => expect(cancelAppointmentMock).toHaveBeenCalledWith("t1", "a1"));
    await waitFor(() => expect(screen.getByText("cancelled")).toBeInTheDocument());
  });

  it("shows the non-enumerating 404 as-is for an unknown or inaccessible id", async () => {
    cancelAppointmentMock.mockRejectedValue(
      new ApiError("forbidden", "Not found, or you don't have access to it.", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<ManageAppointmentPanel tenantId="t1" />);
    await user.type(screen.getByLabelText("Appointment ID"), "unknown");
    await user.click(screen.getByRole("button", { name: "Cancel appointment" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));

    await waitFor(() =>
      expect(screen.getByText("Not found, or you don't have access to it.")).toBeInTheDocument(),
    );
  });
});
