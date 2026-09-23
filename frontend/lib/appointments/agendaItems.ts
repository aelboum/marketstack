// Isolates the "a scheduled thing is always an Appointment" assumption
// so the Day/Month/Agenda-list views can render a second kind (a generic
// calendar event) without restructuring how they render. Both variants
// exist now that the Calendar Event API (docs/ROADMAP.md Phase 7.5) has
// a real HTTP read path -- `CalendarEvent` (`lib/api/appointments.ts`).
import type { Appointment, CalendarEvent } from "@/lib/api/appointments";

/** One scheduled thing shown on the calendar: a business `Appointment`
 * or a generic `CalendarEvent`. */
export type AgendaItem =
  | { kind: "appointment"; id: string; startsAt: string; endsAt: string; appointment: Appointment }
  | { kind: "event"; id: string; startsAt: string; endsAt: string; event: CalendarEvent };

export function appointmentToAgendaItem(appointment: Appointment): AgendaItem {
  return {
    kind: "appointment",
    id: appointment.id,
    startsAt: appointment.starts_at,
    endsAt: appointment.ends_at,
    appointment,
  };
}

export function appointmentsToAgendaItems(appointments: Appointment[]): AgendaItem[] {
  return appointments.map(appointmentToAgendaItem);
}

export function calendarEventToAgendaItem(event: CalendarEvent): AgendaItem {
  return {
    kind: "event",
    id: event.id,
    startsAt: event.starts_at,
    endsAt: event.ends_at,
    event,
  };
}

export function calendarEventsToAgendaItems(events: CalendarEvent[]): AgendaItem[] {
  return events.map(calendarEventToAgendaItem);
}

/** Merges appointments and generic calendar events into one
 * chronologically-sorted list. An appointment-backed `CalendarEvent`
 * (`event.appointment_id` set) is deliberately excluded here -- that
 * booking is already represented by its own `Appointment` row in
 * `appointments`, and this API never lets the frontend create one (see
 * `lib/api/appointments.ts::CalendarEvent`'s own comment), so including
 * it too would render the same booking twice. */
export function combineAgendaItems(
  appointments: Appointment[],
  events: CalendarEvent[],
): AgendaItem[] {
  const generic = events.filter((event) => event.appointment_id === null);
  return [...appointmentsToAgendaItems(appointments), ...calendarEventsToAgendaItems(generic)].sort(
    (a, b) => a.startsAt.localeCompare(b.startsAt),
  );
}
