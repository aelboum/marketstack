import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CalendarForm } from "./CalendarForm";
import { ApiError } from "@/lib/api/errors";

const { createCalendarMock, updateCalendarMock } = vi.hoisted(() => ({
  createCalendarMock: vi.fn(),
  updateCalendarMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return { ...actual, createCalendar: createCalendarMock, updateCalendar: updateCalendarMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ user: { user_id: "me-123" }, markSessionExpired: vi.fn() }),
}));

const CALENDAR = {
  id: "cal1",
  tenant_id: "t1",
  name: "Sales calls",
  owner_user_id: "u1",
  timezone: "Europe/Amsterdam",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("CalendarForm", () => {
  it("create mode: pre-fills the signed-in user's id and submits all three fields", async () => {
    createCalendarMock.mockResolvedValue({ ...CALENDAR, id: "new1" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<CalendarForm tenantId="t1" onSaved={onSaved} />);

    expect(screen.getByLabelText("Owner user ID")).toHaveValue("me-123");
    expect(screen.getByRole("button", { name: "Create calendar" })).toBeDisabled();

    await user.type(screen.getByLabelText("Name"), "Sales calls");
    await user.click(screen.getByRole("button", { name: "Create calendar" }));

    await waitFor(() => expect(createCalendarMock).toHaveBeenCalled());
    const [, body] = createCalendarMock.mock.calls[0];
    expect(body.name).toBe("Sales calls");
    expect(body.owner_user_id).toBe("me-123");
    expect(typeof body.timezone).toBe("string");
    expect(onSaved).toHaveBeenCalled();
  });

  it("edit mode: sends null for fields that did not change (PATCH semantics)", async () => {
    updateCalendarMock.mockResolvedValue(CALENDAR);
    const user = userEvent.setup();

    render(<CalendarForm tenantId="t1" calendar={CALENDAR} onSaved={vi.fn()} />);

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Renamed");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateCalendarMock).toHaveBeenCalledWith("t1", "cal1", {
        name: "Renamed",
        owner_user_id: null,
        timezone: null,
      }),
    );
  });

  it("blocks a name longer than the real 255-character backend limit", async () => {
    const user = userEvent.setup();
    render(<CalendarForm tenantId="t1" onSaved={vi.fn()} />);

    await user.click(screen.getByLabelText("Name"));
    await user.paste("x".repeat(256));

    expect(screen.getByText(/255 characters or fewer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create calendar" })).toBeDisabled();
    expect(createCalendarMock).not.toHaveBeenCalled();
  });

  it("surfaces the backend's own validation error verbatim", async () => {
    createCalendarMock.mockRejectedValue(
      new ApiError("validation", "unknown timezone identifier: 'Mars/Phobos'", { status: 400 }),
    );
    const user = userEvent.setup();

    render(<CalendarForm tenantId="t1" onSaved={vi.fn()} />);
    await user.type(screen.getByLabelText("Name"), "Bad zone");
    await user.click(screen.getByRole("button", { name: "Create calendar" }));

    await waitFor(() =>
      expect(screen.getByText("unknown timezone identifier: 'Mars/Phobos'")).toBeInTheDocument(),
    );
  });
});
