import { describe, expect, it } from "vitest";
import {
  bucketByWeekday,
  eventLayout,
  getWeekStart,
  isWithinGridWindow,
  weekDays,
} from "./calendarWeek";
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

describe("getWeekStart", () => {
  it("returns the Monday of the week for a mid-week date", () => {
    // Tuesday 2026-09-22.
    const monday = getWeekStart(new Date(2026, 8, 22));
    expect(monday.getDay()).toBe(1);
    expect(monday.getDate()).toBe(21);
  });

  it("returns the same date when already a Monday", () => {
    const monday = getWeekStart(new Date(2026, 8, 21));
    expect(monday.getDate()).toBe(21);
  });

  it("rolls a Sunday back to the Monday that started its week, not forward", () => {
    const monday = getWeekStart(new Date(2026, 8, 27)); // Sunday
    expect(monday.getDay()).toBe(1);
    expect(monday.getDate()).toBe(21);
  });
});

describe("weekDays", () => {
  it("returns exactly Monday through Friday", () => {
    const days = weekDays(new Date(2026, 8, 21));
    expect(days).toHaveLength(5);
    expect(days.map((d) => d.getDay())).toEqual([1, 2, 3, 4, 5]);
  });
});

describe("bucketByWeekday", () => {
  it("groups appointments into their local weekday column, sorted by start time", () => {
    const weekStart = new Date(2026, 8, 21); // Monday
    const appointments = [
      appointment({ id: "late", starts_at: "2026-09-22T14:00:00.000Z" }), // Tuesday
      appointment({ id: "early", starts_at: "2026-09-22T09:00:00.000Z" }), // Tuesday
      appointment({ id: "monday", starts_at: "2026-09-21T10:00:00.000Z" }),
    ];

    const buckets = bucketByWeekday(appointments, weekStart);

    expect(buckets[0].map((a) => a.id)).toEqual(["monday"]);
    expect(buckets[1].map((a) => a.id)).toEqual(["early", "late"]);
    expect(buckets[2]).toEqual([]);
  });

  it("omits an appointment that falls on a Saturday or Sunday -- outside the 5-day grid", () => {
    const weekStart = new Date(2026, 8, 21);
    const saturday = appointment({ starts_at: "2026-09-26T10:00:00.000Z" });

    const buckets = bucketByWeekday([saturday], weekStart);

    expect(buckets.flat()).toEqual([]);
  });
});

describe("eventLayout", () => {
  it("positions a 30-minute event proportionally within the grid", () => {
    const nineAm = appointment({
      starts_at: new Date(2026, 8, 22, 9, 0).toISOString(),
      ends_at: new Date(2026, 8, 22, 9, 30).toISOString(),
    });

    const layout = eventLayout(nineAm);

    expect(layout.topPx).toBe(56); // (9 - 8) * 56
    expect(layout.heightPx).toBe(24); // 0.5 * 56 - 4
    expect(layout.startHour).toBe(9);
  });

  it("never collapses a very short event below the minimum visible height", () => {
    const fiveMin = appointment({
      starts_at: new Date(2026, 8, 22, 10, 0).toISOString(),
      ends_at: new Date(2026, 8, 22, 10, 5).toISOString(),
    });

    expect(eventLayout(fiveMin).heightPx).toBe(20);
  });
});

describe("isWithinGridWindow", () => {
  it("is true for an appointment inside 08:00-18:00", () => {
    const inWindow = appointment({ starts_at: new Date(2026, 8, 22, 12, 0).toISOString() });
    expect(isWithinGridWindow(inWindow)).toBe(true);
  });

  it("is false for an appointment starting before 08:00 or at/after 18:00", () => {
    const early = appointment({ starts_at: new Date(2026, 8, 22, 7, 0).toISOString() });
    const late = appointment({ starts_at: new Date(2026, 8, 22, 18, 0).toISOString() });
    expect(isWithinGridWindow(early)).toBe(false);
    expect(isWithinGridWindow(late)).toBe(false);
  });
});
