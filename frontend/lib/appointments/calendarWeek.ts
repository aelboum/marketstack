// Pure week/day-grid math for the Appointments week view (mockup layout
// parity: design/Calendar.dc.html). Kept separate from the page
// component so the date arithmetic and event-layout math are unit-
// testable without rendering anything.
//
// Business week is Monday-Friday, matching the mockup's own 5-column
// grid -- a real, deliberate scope choice, not an oversight: this
// product has no concept of "business days" on a calendar (no such
// field exists on `Calendar`/`Appointment`), so "Monday-Friday" is a
// fixed display convention here, the same way the mockup itself hard-
// codes it. A confirmed appointment that happens to fall on a Saturday
// or Sunday still exists and is not cancelled by this -- it is simply
// outside the query window this view asks for, exactly like the
// mockup's own fixed 5-day grid would not show one either.
import type { Appointment, AppointmentStatus } from "@/lib/api/appointments";

export const GRID_START_HOUR = 8;
export const GRID_END_HOUR = 18;
export const GRID_HOURS = Array.from(
  { length: GRID_END_HOUR - GRID_START_HOUR },
  (_, i) => GRID_START_HOUR + i,
);
export const ROW_HEIGHT_PX = 56;

/** The Monday of the week containing `date`, at local midnight. */
export function getWeekStart(date: Date): Date {
  const day = date.getDay(); // 0=Sun..6=Sat
  const diff = day === 0 ? -6 : 1 - day;
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate() + diff);
  monday.setHours(0, 0, 0, 0);
  return monday;
}

/** Monday-Friday dates for the week starting at `weekStart`. */
export function weekDays(weekStart: Date): Date[] {
  return Array.from({ length: 5 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + i);
    return d;
  });
}

export function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Buckets appointments by which of the 5 weekday columns (0=Monday)
 * their `starts_at` falls on, in the *viewer's own local* calendar day
 * -- omitting anything outside Monday-Friday (see module docstring).
 * Sorted ascending by start time within each day. */
export function bucketByWeekday(appointments: Appointment[], weekStart: Date): Appointment[][] {
  const buckets: Appointment[][] = [[], [], [], [], []];
  const days = weekDays(weekStart);
  for (const appointment of appointments) {
    const start = new Date(appointment.starts_at);
    const dayIndex = days.findIndex((d) => isSameDay(d, start));
    if (dayIndex === -1) continue;
    buckets[dayIndex].push(appointment);
  }
  for (const bucket of buckets) {
    bucket.sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  }
  return buckets;
}

export type EventLayout = {
  topPx: number;
  heightPx: number;
  /** Whole hours + fractional minutes since local midnight, for the
   * start time -- used only to decide whether an event actually falls
   * inside the rendered 08:00-18:00 grid window. */
  startHour: number;
  /** Mirrors the mockup's own `dir`/`pad` (`design/Calendar.dc.html`):
   * an event under an hour is too short to stack a title line above a
   * details line without either clipping (a 24px-tall 30-minute slot
   * cannot fit two 16px-line-height lines plus padding) or, worse,
   * `overflow: hidden` silently hiding the second line entirely -- so
   * short events lay their title and time side by side instead of
   * stacked, with tighter padding to match. */
  direction: "row" | "column";
  paddingPx: [vertical: number, horizontal: number];
  /** An event under an hour shows only its start time (mockup: `dur < 1
   * ? fmt(h) : fmt(h)+'–'+fmt(h+dur)`) -- the row layout has no room for
   * a full time range next to the title. */
  compactTime: boolean;
};

/** Pixel position/height for one event block within the day column,
 * clamped to the rendered grid window -- mirrors the mockup's own
 * `top`/`h` math (`(hour - start) * 56`), in real local time, not the
 * mockup's fixed sample hours. */
export function eventLayout(appointment: Appointment): EventLayout {
  const start = new Date(appointment.starts_at);
  const end = new Date(appointment.ends_at);
  const startHour = start.getHours() + start.getMinutes() / 60;
  const durationHours = Math.max((end.getTime() - start.getTime()) / 3_600_000, 0);
  const topPx = (startHour - GRID_START_HOUR) * ROW_HEIGHT_PX;
  const heightPx = Math.max(durationHours * ROW_HEIGHT_PX - 4, 20);
  const paddingPx: [number, number] =
    durationHours < 0.5 ? [2, 8] : durationHours < 1 ? [3, 8] : [6, 8];
  return {
    topPx,
    heightPx,
    startHour,
    direction: durationHours < 1 ? "row" : "column",
    paddingPx,
    compactTime: durationHours < 1,
  };
}

export function isWithinGridWindow(appointment: Appointment): boolean {
  const start = new Date(appointment.starts_at);
  const startHour = start.getHours() + start.getMinutes() / 60;
  return startHour >= GRID_START_HOUR && startHour < GRID_END_HOUR;
}

export const STATUS_LABEL_NL: Record<AppointmentStatus, string> = {
  confirmed: "Bevestigd",
  completed: "Afgerond",
  cancelled: "Geannuleerd",
  no_show: "Niet verschenen",
};

/** Existing semantic tokens only -- status is the one real, always-
 * present field this product's `Appointment` has that the mockup's own
 * (unmodeled) "appointment type" does not map onto; colouring by real
 * status is the honest substitute. */
export const STATUS_TONE: Record<AppointmentStatus, "info" | "success" | "neutral" | "warning"> = {
  confirmed: "info",
  completed: "success",
  cancelled: "neutral",
  no_show: "warning",
};
