// Pure month-grid date math for the Agenda month/list views -- mirrors
// lib/appointments/calendarWeek.ts's own "pure, unit-testable date
// arithmetic, kept out of the component" split. NL week starts Monday,
// the same convention calendarWeek.ts already uses.
import type { AgendaItem } from "./agendaItems";

/** Local midnight on the 1st of `date`'s month. */
export function getMonthStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

/** The Monday on or before the 1st of `date`'s month -- the first cell
 * of a 6-row Monday-start month grid. */
export function getMonthGridStart(date: Date): Date {
  const monthStart = getMonthStart(date);
  const day = monthStart.getDay(); // 0=Sun..6=Sat
  const diff = day === 0 ? -6 : 1 - day;
  const start = new Date(monthStart);
  start.setDate(start.getDate() + diff);
  return start;
}

export type MonthGridDay = { date: Date; inMonth: boolean };

/** 42 days (6 full Monday-start weeks) covering `date`'s month, padded
 * with the trailing days of the previous/next month so every row is a
 * complete week -- the standard month-grid shape. */
export function monthGridDays(date: Date): MonthGridDay[] {
  const start = getMonthGridStart(date);
  const month = date.getMonth();
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return { date: d, inMonth: d.getMonth() === month };
  });
}

export function addMonths(date: Date, delta: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + delta, 1);
}

export function addDays(date: Date, delta: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + delta);
  return next;
}

/** `YYYY-MM-DD` in the viewer's own local calendar day -- a stable
 * grouping key, never shown to the user. */
export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** Groups agenda items by the local calendar day their `startsAt` falls
 * on, each day's items sorted ascending by start time. */
export function groupItemsByDay(items: AgendaItem[]): Record<string, AgendaItem[]> {
  const groups: Record<string, AgendaItem[]> = {};
  for (const item of items) {
    const key = dayKey(new Date(item.startsAt));
    (groups[key] ??= []).push(item);
  }
  for (const key of Object.keys(groups)) {
    groups[key].sort((a, b) => a.startsAt.localeCompare(b.startsAt));
  }
  return groups;
}
