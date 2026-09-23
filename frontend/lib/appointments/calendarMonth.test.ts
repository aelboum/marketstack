import { describe, expect, it } from "vitest";
import {
  addDays,
  addMonths,
  dayKey,
  getMonthGridStart,
  getMonthStart,
  groupItemsByDay,
  monthGridDays,
} from "./calendarMonth";
import { appointmentToAgendaItem } from "./agendaItems";
import type { Appointment } from "@/lib/api/appointments";

function appointment(overrides: Partial<Appointment>): Appointment {
  return {
    id: "a1",
    tenant_id: "t1",
    calendar_id: "c1",
    contact_id: null,
    starts_at: "2026-09-22T09:00:00.000Z",
    ends_at: "2026-09-22T09:30:00.000Z",
    status: "confirmed",
    created_at: "2026-09-01T00:00:00.000Z",
    updated_at: "2026-09-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("getMonthStart", () => {
  it("returns the 1st of the month at local midnight", () => {
    const start = getMonthStart(new Date(2026, 8, 22));
    expect(start.getDate()).toBe(1);
    expect(start.getMonth()).toBe(8);
    expect(start.getHours()).toBe(0);
  });
});

describe("getMonthGridStart", () => {
  it("rolls back to the Monday on/before the 1st (September 2026 starts on a Tuesday)", () => {
    const start = getMonthGridStart(new Date(2026, 8, 22));
    expect(start.getDay()).toBe(1);
    expect(start.getMonth()).toBe(7); // August
    expect(start.getDate()).toBe(31);
  });

  it("returns the 1st itself when the month already starts on a Monday", () => {
    // 2026-06-01 is a Monday.
    const start = getMonthGridStart(new Date(2026, 5, 15));
    expect(start.getDay()).toBe(1);
    expect(start.getDate()).toBe(1);
    expect(start.getMonth()).toBe(5);
  });
});

describe("monthGridDays", () => {
  it("returns 42 days covering the full month plus lead/trail padding", () => {
    const days = monthGridDays(new Date(2026, 8, 22));
    expect(days).toHaveLength(42);
    expect(days[0].inMonth).toBe(false);
    const first = days.find((d) => d.inMonth);
    expect(first?.date.getDate()).toBe(1);
    expect(first?.date.getMonth()).toBe(8);
  });
});

describe("addMonths/addDays", () => {
  it("addMonths steps by whole months, clamped to the 1st", () => {
    const next = addMonths(new Date(2026, 8, 22), 1);
    expect(next.getMonth()).toBe(9);
    expect(next.getDate()).toBe(1);
  });

  it("addDays steps by whole days", () => {
    const next = addDays(new Date(2026, 8, 22), 3);
    expect(next.getDate()).toBe(25);
  });
});

describe("dayKey/groupItemsByDay", () => {
  it("groups items by local calendar day and sorts ascending within a day", () => {
    const items = [
      appointmentToAgendaItem(appointment({ id: "a", starts_at: "2026-09-22T10:00:00.000Z" })),
      appointmentToAgendaItem(appointment({ id: "b", starts_at: "2026-09-22T08:00:00.000Z" })),
      appointmentToAgendaItem(appointment({ id: "c", starts_at: "2026-09-23T08:00:00.000Z" })),
    ];
    const groups = groupItemsByDay(items);
    const key22 = dayKey(new Date("2026-09-22T10:00:00.000Z"));
    const key23 = dayKey(new Date("2026-09-23T08:00:00.000Z"));
    expect(groups[key22].map((i) => i.id)).toEqual(["b", "a"]);
    expect(groups[key23].map((i) => i.id)).toEqual(["c"]);
  });
});
