import { describe, expect, it } from "vitest";
import { combineAgendaItems } from "./agendaItems";
import type { Appointment, CalendarEvent } from "@/lib/api/appointments";

function appointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: "a1",
    tenant_id: "t1",
    calendar_id: "cal1",
    contact_id: null,
    starts_at: "2026-10-05T09:00:00.000Z",
    ends_at: "2026-10-05T09:30:00.000Z",
    status: "confirmed",
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

function calendarEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "e1",
    tenant_id: "t1",
    calendar_id: "cal1",
    appointment_id: null,
    title: "Team meeting",
    description: null,
    starts_at: "2026-10-05T08:00:00.000Z",
    ends_at: "2026-10-05T08:30:00.000Z",
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

describe("combineAgendaItems", () => {
  it("merges appointments and generic events, sorted chronologically", () => {
    const items = combineAgendaItems(
      [appointment({ id: "a1", starts_at: "2026-10-05T10:00:00.000Z" })],
      [calendarEvent({ id: "e1", starts_at: "2026-10-05T09:00:00.000Z" })],
    );
    expect(items.map((i) => i.id)).toEqual(["e1", "a1"]);
    expect(items[0].kind).toBe("event");
    expect(items[1].kind).toBe("appointment");
  });

  it("excludes an appointment-backed CalendarEvent to avoid rendering the same booking twice", () => {
    const items = combineAgendaItems(
      [appointment({ id: "a1" })],
      [calendarEvent({ id: "e1", appointment_id: "a1" })],
    );
    expect(items.map((i) => i.id)).toEqual(["a1"]);
    expect(items[0].kind).toBe("appointment");
  });

  it("returns an empty list when there is nothing scheduled", () => {
    expect(combineAgendaItems([], [])).toEqual([]);
  });
});
