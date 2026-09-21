import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RemindersPanel } from "./RemindersPanel";
import { ApiError } from "@/lib/api/errors";

const { sweepRemindersMock } = vi.hoisted(() => ({ sweepRemindersMock: vi.fn() }));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return { ...actual, sweepReminders: sweepRemindersMock };
});

describe("RemindersPanel", () => {
  it("presents the sweep as manual, and sends nothing until asked", () => {
    render(<RemindersPanel tenantId="t1" />);
    expect(sweepRemindersMock).not.toHaveBeenCalled();
    expect(screen.getByText(/Nothing runs this automatically/)).toBeInTheDocument();
  });

  it("reports only what the sweep returned", async () => {
    sweepRemindersMock.mockResolvedValue({ reminded_count: 2, appointment_ids: ["a1", "a2"] });
    const user = userEvent.setup();

    render(<RemindersPanel tenantId="t1" />);
    await user.click(screen.getByRole("button", { name: "Run reminder sweep" }));

    await waitFor(() => expect(sweepRemindersMock).toHaveBeenCalledWith("t1"));
    expect(screen.getByText("Sent 2 reminders.")).toBeInTheDocument();
    expect(screen.getByText("a1")).toBeInTheDocument();
    expect(screen.getByText("a2")).toBeInTheDocument();
  });

  it("shows the backend error on failure", async () => {
    sweepRemindersMock.mockRejectedValue(
      new ApiError("server", "EMAIL_DEFAULT_SENDER is not set.", { status: 400 }),
    );
    const user = userEvent.setup();

    render(<RemindersPanel tenantId="t1" />);
    await user.click(screen.getByRole("button", { name: "Run reminder sweep" }));

    await waitFor(() =>
      expect(screen.getByText("EMAIL_DEFAULT_SENDER is not set.")).toBeInTheDocument(),
    );
  });
});
