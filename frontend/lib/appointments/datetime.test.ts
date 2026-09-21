import { describe, expect, it } from "vitest";
import {
  DAY_NAMES,
  dateSpanDays,
  formatInTimeZone,
  formatTimeInTimeZone,
  isoToLocalInput,
  localInputToIso,
  minutesToTimeInput,
  timeInputToMinutes,
  toDateInput,
} from "./datetime";

describe("appointments datetime helpers", () => {
  it("DAY_NAMES is Monday-first, matching Python's date.weekday() (NOT Date.getDay())", () => {
    expect(DAY_NAMES[0]).toBe("Monday");
    expect(DAY_NAMES[6]).toBe("Sunday");
  });

  it("localInputToIso turns a naive datetime-local value into a timezone-aware instant", () => {
    const iso = localInputToIso("2026-03-01T09:30");
    expect(iso).not.toBeNull();
    // The backend rejects a naive datetime with a 400, so the result must
    // carry a real offset -- toISOString() always ends in Z.
    expect(iso).toMatch(/Z$/);
    expect(new Date(iso as string).getTime()).toBe(new Date("2026-03-01T09:30").getTime());
  });

  it("localInputToIso returns null for empty/unparseable input (submit stays disabled)", () => {
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("not-a-date")).toBeNull();
  });

  it("isoToLocalInput round-trips back through localInputToIso", () => {
    const original = "2026-07-04T14:15";
    const iso = localInputToIso(original) as string;
    expect(isoToLocalInput(iso)).toBe(original);
  });

  it("timeInputToMinutes converts HH:MM to minutes since midnight", () => {
    expect(timeInputToMinutes("00:00")).toBe(0);
    expect(timeInputToMinutes("09:30")).toBe(570);
    expect(timeInputToMinutes("23:59")).toBe(1439);
  });

  it("timeInputToMinutes rejects malformed or out-of-range values", () => {
    expect(timeInputToMinutes("")).toBeNull();
    expect(timeInputToMinutes("9:5")).toBeNull();
    expect(timeInputToMinutes("25:00")).toBeNull();
    expect(timeInputToMinutes("10:75")).toBeNull();
  });

  it("minutesToTimeInput renders 1440 as end-of-day, never wrapping to 00:00", () => {
    expect(minutesToTimeInput(0)).toBe("00:00");
    expect(minutesToTimeInput(570)).toBe("09:30");
    expect(minutesToTimeInput(1440)).toBe("24:00");
  });

  it("formatInTimeZone renders the calendar's zone, not the viewer's", () => {
    // 12:00 UTC is 13:00 in Amsterdam (CET, winter) and 07:00 in New York.
    const amsterdam = formatTimeInTimeZone("2026-01-15T12:00:00Z", "Europe/Amsterdam");
    const newYork = formatTimeInTimeZone("2026-01-15T12:00:00Z", "America/New_York");
    expect(amsterdam).not.toBe(newYork);
    expect(amsterdam).toContain("13");
    expect(newYork).toContain("7");
  });

  it("formatInTimeZone falls back to the viewer's locale for an unknown zone", () => {
    expect(formatInTimeZone("2026-01-15T12:00:00Z", "Mars/Phobos")).toBe(
      new Date("2026-01-15T12:00:00Z").toLocaleString(),
    );
  });

  it("dateSpanDays matches the backend's own (date_to - date_from).days", () => {
    expect(dateSpanDays("2026-01-01", "2026-01-01")).toBe(0);
    expect(dateSpanDays("2026-01-01", "2026-04-01")).toBe(90);
    expect(dateSpanDays("2026-01-01", "2026-04-02")).toBe(91);
    expect(dateSpanDays("2026-04-01", "2026-01-01")).toBe(-90);
    expect(dateSpanDays("nonsense", "2026-01-01")).toBeNull();
  });

  it("toDateInput renders the YYYY-MM-DD shape the date query params take", () => {
    expect(toDateInput(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});
