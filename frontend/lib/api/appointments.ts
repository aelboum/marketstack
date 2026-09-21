// Typed API functions for the Phase 7 Appointments backend
// (`product/appointments/routes.py`, mounted at `/v1/appointments`),
// built on the UI-1 `request()` foundation -- mirrors lib/api/{agency,
// crm,conversations,marketing}.ts; UI-6 adds no second HTTP client.
// Every shape below is read directly off that router's own
// `_calendar_dict()`/`_rule_dict()`/`_slot_dict()`/`_appointment_dict()`
// builders and request models.
//
// Deliberately absent, because the backend has none -- verified by
// grepping every `def` in `product/appointments/*.py`, not just the
// router:
//   - **no authenticated appointment list endpoint** (no
//     `GET /tenants/{t}/appointments`) and no `list_appointments()`
//     service function anywhere. An appointment can only be read back
//     by the *contact* who booked it, through the public
//     `GET /manage/{manage_token}` route; staff have no read path at
//     all;
//   - **no authenticated appointment detail endpoint** (no
//     `GET /tenants/{t}/appointments/{id}`) and no `get_appointment()`
//     service function. `POST .../appointments` returns the row it just
//     created, and cancel/reschedule return the row they just changed --
//     those three responses are the *only* way this app ever sees an
//     appointment;
//   - no calendar-sync/provider endpoint: `product/appointments/
//     calendar_sync.py` exists but is not imported by `routes.py` at
//     all, so no provider/credential state is API-readable;
//   - no readable reminder state: `POST .../reminders/sweep` *sends*
//     due reminders and returns only a count plus the ids it touched;
//     no per-appointment reminder history is exposed.
// See this phase's own report for the full gap list and the exact UI
// consequence of each.

import { request } from "@/lib/api/client";

/** The only two statuses `product/appointments/models.py` defines. */
export type AppointmentStatus = "confirmed" | "cancelled";

export type Calendar = {
  id: string;
  tenant_id: string;
  name: string;
  owner_user_id: string;
  timezone: string;
  created_at: string;
  updated_at: string;
};

export type AvailabilityRule = {
  id: string;
  tenant_id: string;
  calendar_id: string;
  /** 0-6, as validated by `CreateAvailabilityRuleRequest`. */
  day_of_week: number;
  /** Minutes since midnight (0 <= start_time < 1440). */
  start_time: number;
  /** Minutes since midnight (0 < end_time <= 1440). */
  end_time: number;
  created_at: string;
};

/** A slot the backend itself computed. Never constructed client-side --
 * `compute_available_slots()` is the only authority on what is bookable
 * (and even it is explicitly a courtesy answer, not the safety net: the
 * database `EXCLUDE` constraint is, per booking.py's own docstring). */
export type AvailableSlot = {
  starts_at: string;
  ends_at: string;
};

export type Appointment = {
  id: string;
  tenant_id: string;
  calendar_id: string;
  contact_id: string | null;
  starts_at: string;
  ends_at: string;
  status: AppointmentStatus;
  created_at: string;
  updated_at: string;
};

export type ReminderSweepResult = {
  reminded_count: number;
  appointment_ids: string[];
};

export type Page<T> = {
  results: T[];
  /** Heuristic only (`results.length === limit`) -- the calendars list
   * endpoint returns a plain array with no total count, same as every
   * other list endpoint in this product. */
  hasMore: boolean;
};

function toPage<T>(results: T[], limit: number): Page<T> {
  return { results, hasMore: results.length === limit };
}

/** Mirrors `product/appointments/pagination.py::DEFAULT_PAGE_SIZE`. */
const DEFAULT_LIMIT = 25;

// --- Calendars -------------------------------------------------------------

export function listCalendars(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Calendar>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<Calendar[]>(`/v1/appointments/tenants/${tenantId}/calendars`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getCalendar(tenantId: string, calendarId: string): Promise<Calendar> {
  return request<Calendar>(`/v1/appointments/tenants/${tenantId}/calendars/${calendarId}`);
}

export function createCalendar(
  tenantId: string,
  input: { name: string; owner_user_id: string; timezone: string },
): Promise<Calendar> {
  return request<Calendar>(`/v1/appointments/tenants/${tenantId}/calendars`, {
    method: "POST",
    body: input,
  });
}

export type UpdateCalendarInput = {
  name?: string | null;
  owner_user_id?: string | null;
  timezone?: string | null;
};

export function updateCalendar(
  tenantId: string,
  calendarId: string,
  input: UpdateCalendarInput,
): Promise<Calendar> {
  return request<Calendar>(`/v1/appointments/tenants/${tenantId}/calendars/${calendarId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteCalendar(tenantId: string, calendarId: string): Promise<void> {
  return request<void>(`/v1/appointments/tenants/${tenantId}/calendars/${calendarId}`, {
    method: "DELETE",
  });
}

/** `POST .../booking-link` -- get-or-create, so calling it twice returns
 * the same token (see `calendars.py::get_or_create_booking_link()`). */
export function getOrCreateBookingLink(
  tenantId: string,
  calendarId: string,
): Promise<{ link_token: string }> {
  return request<{ link_token: string }>(
    `/v1/appointments/tenants/${tenantId}/calendars/${calendarId}/booking-link`,
    { method: "POST" },
  );
}

// --- Availability rules ----------------------------------------------------

/** No `limit`/`offset` exist on this route -- it returns every rule for
 * the calendar, so there is nothing to paginate. */
export function listAvailabilityRules(
  tenantId: string,
  calendarId: string,
): Promise<AvailabilityRule[]> {
  return request<AvailabilityRule[]>(
    `/v1/appointments/tenants/${tenantId}/calendars/${calendarId}/availability-rules`,
  );
}

export function createAvailabilityRule(
  tenantId: string,
  calendarId: string,
  input: { day_of_week: number; start_time: number; end_time: number },
): Promise<AvailabilityRule> {
  return request<AvailabilityRule>(
    `/v1/appointments/tenants/${tenantId}/calendars/${calendarId}/availability-rules`,
    { method: "POST", body: input },
  );
}

export function deleteAvailabilityRule(
  tenantId: string,
  calendarId: string,
  ruleId: string,
): Promise<void> {
  return request<void>(
    `/v1/appointments/tenants/${tenantId}/calendars/${calendarId}/availability-rules/${ruleId}`,
    { method: "DELETE" },
  );
}

/** `date_from`/`date_to` are `datetime.date` on the backend, so they go
 * over the wire as plain `YYYY-MM-DD`; `slot_duration_minutes` has no
 * server-side default, so it is required here too. */
export function listAvailableSlots(
  tenantId: string,
  calendarId: string,
  params: { date_from: string; date_to: string; slot_duration_minutes: number },
): Promise<AvailableSlot[]> {
  return request<AvailableSlot[]>(
    `/v1/appointments/tenants/${tenantId}/calendars/${calendarId}/available-slots`,
    {
      query: {
        date_from: params.date_from,
        date_to: params.date_to,
        slot_duration_minutes: params.slot_duration_minutes,
      },
    },
  );
}

// --- Appointments (staff) ---------------------------------------------------

export type BookAppointmentInput = {
  calendar_id: string;
  contact_email: string;
  contact_first_name: string;
  contact_last_name: string;
  contact_phone?: string | null;
  /** Must be timezone-aware ISO-8601 -- `booking.py::_validate_time_range()`
   * rejects a naive datetime with a 400. Build these with
   * `lib/appointments/datetime.ts::localInputToIso()`, never by passing
   * an `<input type="datetime-local">` value straight through. */
  starts_at: string;
  ends_at: string;
};

export function bookAppointment(
  tenantId: string,
  input: BookAppointmentInput,
): Promise<Appointment> {
  return request<Appointment>(`/v1/appointments/tenants/${tenantId}/appointments`, {
    method: "POST",
    body: input,
  });
}

export function cancelAppointment(tenantId: string, appointmentId: string): Promise<Appointment> {
  return request<Appointment>(
    `/v1/appointments/tenants/${tenantId}/appointments/${appointmentId}/cancel`,
    { method: "POST" },
  );
}

export function rescheduleAppointment(
  tenantId: string,
  appointmentId: string,
  input: { new_starts_at: string; new_ends_at: string },
): Promise<Appointment> {
  return request<Appointment>(
    `/v1/appointments/tenants/${tenantId}/appointments/${appointmentId}/reschedule`,
    { method: "POST", body: input },
  );
}

// --- Reminders --------------------------------------------------------------

/** Sends every *due* reminder for the tenant and reports what it
 * touched. The backend's own route docstring is explicit that nothing in
 * this product calls this on a schedule -- so the UI presents it as a
 * manual action, never as evidence that reminders are running. */
export function sweepReminders(tenantId: string): Promise<ReminderSweepResult> {
  return request<ReminderSweepResult>(`/v1/appointments/tenants/${tenantId}/reminders/sweep`, {
    method: "POST",
  });
}
