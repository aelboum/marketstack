// Isolates the "a scheduled thing is always an Appointment" assumption
// so the Month/Agenda-list views can grow a second kind (a generic
// calendar event) later without restructuring how they render. Only the
// `"appointment"` variant exists today: there is no frontend read path
// for a generic calendar event yet -- `product/appointments
// /calendar_events.py` (Calendar Foundation, docs/ROADMAP.md Phase 7.5)
// is service-layer only, no HTTP route. Adding that route/read-path is a
// separate, later change; this module is what lets a `"event"` variant
// slot in later without touching every view that lists scheduled items.
import type { Appointment } from "@/lib/api/appointments";

/** One scheduled thing shown on the calendar. Only the `"appointment"`
 * variant exists today -- see module comment. */
export type AgendaItem = {
  kind: "appointment";
  id: string;
  startsAt: string;
  endsAt: string;
  appointment: Appointment;
};

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
