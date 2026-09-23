import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CalendarEventForm } from "./CalendarEventForm";
import type { Calendar, CalendarEvent } from "@/lib/api/appointments";
import { ApiError } from "@/lib/api/errors";

const { createCalendarEventMock, updateCalendarEventMock, deleteCalendarEventMock } = vi.hoisted(() => ({
  createCalendarEventMock: vi.fn(),
  updateCalendarEventMock: vi.fn(),
  deleteCalendarEventMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    createCalendarEvent: createCalendarEventMock,
    updateCalendarEvent: updateCalendarEventMock,
    deleteCalendarEvent: deleteCalendarEventMock,
  };
});

const CALENDARS: Calendar[] = [
  { id: "cal1", tenant_id: "t1", name: "Hoofdagenda", owner_user_id: "u1", timezone: "UTC", created_at: "", updated_at: "" },
];

function existingEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "e1",
    tenant_id: "t1",
    calendar_id: "cal1",
    appointment_id: null,
    title: "Old title",
    description: "Old description",
    starts_at: "2026-10-05T09:00:00.000Z",
    ends_at: "2026-10-05T10:00:00.000Z",
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

describe("CalendarEventForm", () => {
  it("creates a generic event with the fields the user filled in", async () => {
    createCalendarEventMock.mockResolvedValue({ id: "e1", title: "Team meeting" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarEventForm
        tenantId="t1"
        calendars={CALENDARS}
        defaultDate={new Date(2026, 9, 5)}
        onCancel={vi.fn()}
        onSaved={onSaved}
      />,
    );

    await user.type(screen.getByLabelText("Titel"), "Team meeting");
    await user.click(screen.getByRole("button", { name: "Aanmaken" }));

    await waitFor(() => expect(createCalendarEventMock).toHaveBeenCalled());
    const [tenantId, input] = createCalendarEventMock.mock.calls[0];
    expect(tenantId).toBe("t1");
    expect(input.calendar_id).toBe("cal1");
    expect(input.title).toBe("Team meeting");
    expect(input.starts_at < input.ends_at).toBe(true);
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ id: "e1", title: "Team meeting" }));
  });

  it("requires a title", async () => {
    const user = userEvent.setup();
    render(
      <CalendarEventForm tenantId="t1" calendars={CALENDARS} onCancel={vi.fn()} onSaved={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "Aanmaken" }));

    expect(screen.getByText("Titel is verplicht.")).toBeInTheDocument();
    expect(createCalendarEventMock).not.toHaveBeenCalled();
  });

  it("rejects an end time before the start time", async () => {
    const user = userEvent.setup();
    render(
      <CalendarEventForm
        tenantId="t1"
        calendars={CALENDARS}
        defaultDate={new Date(2026, 9, 5)}
        onCancel={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("Titel"), "Backwards");
    const startInput = screen.getByLabelText("Starttijd");
    const endInput = screen.getByLabelText("Eindtijd");
    await user.clear(startInput);
    await user.type(startInput, "14:00");
    await user.clear(endInput);
    await user.type(endInput, "09:00");
    await user.click(screen.getByRole("button", { name: "Aanmaken" }));

    expect(screen.getByText("Eindtijd moet na de starttijd liggen.")).toBeInTheDocument();
    expect(createCalendarEventMock).not.toHaveBeenCalled();
  });

  it("shows the real API error on a failed submit", async () => {
    createCalendarEventMock.mockRejectedValue(new ApiError("validation", "Something went wrong.", { status: 400 }));
    const user = userEvent.setup();
    render(
      <CalendarEventForm
        tenantId="t1"
        calendars={CALENDARS}
        defaultDate={new Date(2026, 9, 5)}
        onCancel={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("Titel"), "Will fail");
    await user.click(screen.getByRole("button", { name: "Aanmaken" }));

    await waitFor(() => expect(screen.getByText("Something went wrong.")).toBeInTheDocument());
  });

  it("edit mode pre-fills the existing event and hides the calendar picker", async () => {
    updateCalendarEventMock.mockResolvedValue({ id: "e1", title: "New title" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarEventForm
        tenantId="t1"
        calendars={CALENDARS}
        event={existingEvent()}
        onCancel={vi.fn()}
        onSaved={onSaved}
      />,
    );

    expect(screen.queryByText("Agenda")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Titel")).toHaveValue("Old title");

    await user.clear(screen.getByLabelText("Titel"));
    await user.type(screen.getByLabelText("Titel"), "New title");
    await user.click(screen.getByRole("button", { name: "Opslaan" }));

    await waitFor(() => expect(updateCalendarEventMock).toHaveBeenCalled());
    const [, eventId, input] = updateCalendarEventMock.mock.calls[0];
    expect(eventId).toBe("e1");
    expect(input.title).toBe("New title");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("deletes the event after confirmation, without touching any appointment", async () => {
    deleteCalendarEventMock.mockResolvedValue(undefined);
    const onDeleted = vi.fn();
    const user = userEvent.setup();

    render(
      <CalendarEventForm
        tenantId="t1"
        calendars={CALENDARS}
        event={existingEvent()}
        onCancel={vi.fn()}
        onSaved={vi.fn()}
        onDeleted={onDeleted}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Verwijderen" }));
    const dialog = await screen.findByRole("dialog", { name: "Evenement verwijderen?" });
    await user.click(within(dialog).getByRole("button", { name: "Verwijderen" }));

    await waitFor(() => expect(deleteCalendarEventMock).toHaveBeenCalledWith("t1", "e1"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("e1"));
  });

  it("does not offer deletion while creating a new event", () => {
    render(
      <CalendarEventForm tenantId="t1" calendars={CALENDARS} onCancel={vi.fn()} onSaved={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Verwijderen" })).not.toBeInTheDocument();
  });
});
