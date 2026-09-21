// Time helpers for UI-6. Appointments is the first module in this
// frontend where the backend's own time semantics are strict enough that
// inline `new Date(x).toLocaleString()` (what CRM/Conversations/Marketing
// each do) is not sufficient:
//
//   - `booking.py::_validate_time_range()` REJECTS a naive datetime with
//     a 400, so an `<input type="datetime-local">` value ("2026-03-01T09:00",
//     no offset) can never be sent as-is -- it must become a real
//     timezone-aware instant first (`localInputToIso`);
//   - availability rules store **minutes since local midnight**
//     (0..1440) interpreted in the owning calendar's own IANA timezone,
//     not the viewer's -- so a rule editor needs a real HH:MM <-> minutes
//     conversion (`timeInputToMinutes`/`minutesToTimeInput`);
//   - `compute_available_slots()` returns **UTC instants** for a calendar
//     that has its own timezone, so showing a slot in the viewer's local
//     zone would silently mislead whoever administers a calendar in
//     another zone (`formatInTimeZone`).
//
// Every constant below mirrors a real backend constant; none is invented
// here (the UI-3 lesson: validate against the backend's own limit, never
// a client-chosen one).

/** `product/appointments/models.py::MAX_CALENDAR_NAME_LENGTH`. */
export const MAX_CALENDAR_NAME_LENGTH = 255;

/** `product/appointments/availability.py::MIN_SLOT_DURATION_MINUTES`. */
export const MIN_SLOT_DURATION_MINUTES = 5;

/** `product/appointments/availability.py::MAX_SLOT_DURATION_MINUTES`
 * (== `MINUTES_PER_DAY`). */
export const MAX_SLOT_DURATION_MINUTES = 1440;

/** `product/appointments/availability.py::MAX_AVAILABILITY_QUERY_DAYS`.
 * The backend check is `(date_to - date_from).days > 90`, so a span of
 * exactly 90 days is allowed. */
export const MAX_AVAILABILITY_QUERY_DAYS = 90;

/** `product/appointments/models.py::MINUTES_PER_DAY`. */
export const MINUTES_PER_DAY = 1440;

/** Index 0-6 maps to `day_of_week` exactly as the backend defines it:
 * Python's `date.weekday()`, so 0 is Monday -- NOT JavaScript's
 * `Date.getDay()`, where 0 is Sunday. Getting this backwards would
 * silently publish availability on the wrong day. */
export const DAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

/**
 * Turns an `<input type="datetime-local">` value into the
 * timezone-aware ISO-8601 string the backend requires.
 *
 * The input value carries no offset; the browser interprets it in the
 * viewer's own zone, which is exactly what a staff member typing "9am"
 * means. `toISOString()` then pins it to a real UTC instant.
 *
 * Returns `null` for an empty or unparseable value, so callers can keep
 * the submit button disabled rather than sending something the backend
 * would 400 on.
 */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}

/** Inverse of `localInputToIso` -- renders an instant back into the
 * `datetime-local` shape ("YYYY-MM-DDTHH:mm") in the viewer's zone, for
 * pre-filling a reschedule form from an existing appointment. */
export function isoToLocalInput(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}` +
    `T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
  );
}

/** "09:30" -> 570. Returns `null` when the value isn't a valid HH:MM
 * inside [0, 1440). */
export function timeInputToMinutes(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

/** 570 -> "09:30". 1440 (the backend's inclusive end-of-day bound) is
 * rendered as "24:00" rather than wrapping to "00:00", because the
 * backend treats it as local end-of-day, not midnight of the next day. */
export function minutesToTimeInput(minutes: number): string {
  if (minutes === MINUTES_PER_DAY) return "24:00";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
}

/** Formats a UTC instant in a specific IANA timezone -- used for slots
 * and appointment times, which belong to the *calendar's* zone, not the
 * viewer's. Falls back to the viewer's zone if the stored identifier
 * isn't one this browser knows (the backend validated it at write time,
 * but an old browser may still not resolve it). */
export function formatInTimeZone(iso: string, timeZone: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone,
      dateStyle: "medium",
      timeStyle: "short",
    }).format(parsed);
  } catch {
    return parsed.toLocaleString();
  }
}

/** Time-only variant of `formatInTimeZone`, for a list of slots that
 * already shows its date as a group heading. */
export function formatTimeInTimeZone(iso: string, timeZone: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat(undefined, { timeZone, timeStyle: "short" }).format(parsed);
  } catch {
    return parsed.toLocaleTimeString();
  }
}

/** Groups slots under a per-day heading rendered in the calendar's own
 * timezone, so a slot near midnight is filed under the day the calendar
 * considers it to be on. */
export function dayKeyInTimeZone(iso: string, timeZone: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone,
      dateStyle: "full",
    }).format(parsed);
  } catch {
    return parsed.toLocaleDateString();
  }
}

/** `YYYY-MM-DD` in the viewer's zone -- the shape the `date_from`/
 * `date_to` query params take (they are `datetime.date` server-side). */
export function toDateInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Whole days between two `YYYY-MM-DD` strings, matching the backend's
 * own `(date_to - date_from).days`. Returns `null` if either is
 * unparseable. */
export function dateSpanDays(dateFrom: string, dateTo: string): number | null {
  const from = new Date(`${dateFrom}T00:00:00Z`);
  const to = new Date(`${dateTo}T00:00:00Z`);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return null;
  return Math.round((to.getTime() - from.getTime()) / 86_400_000);
}

/** The viewer's own IANA zone, used only as the default pre-fill for a
 * new calendar -- the backend still validates whatever is submitted. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** Every IANA zone this browser knows, for the calendar timezone picker.
 * `Intl.supportedValuesOf` is not in every runtime (and not in jsdom),
 * so callers fall back to a free-text field when this returns null. */
export function supportedTimeZones(): string[] | null {
  const intl = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] };
  if (typeof intl.supportedValuesOf !== "function") return null;
  try {
    return intl.supportedValuesOf("timeZone");
  } catch {
    return null;
  }
}
