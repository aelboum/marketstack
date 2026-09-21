"use client";

// Staff booking on a contact's behalf -- `POST .../appointments`.
//
// The slot is always one the backend returned: the picker below is fed
// by `compute_available_slots()`, and the chosen slot's own
// `starts_at`/`ends_at` are what get submitted, unmodified. Availability
// is never inferred here, and a staff member cannot type an arbitrary
// time into this form -- if the backend does not offer a slot, this form
// cannot book it.
//
// The contact fields map onto `BookAppointmentRequest` exactly. The
// backend routes them into
// `crm.contacts.create_or_update_contact_from_trusted_source()`, so
// booking for an email that already exists updates that contact rather
// than creating a duplicate -- which is why this collects contact
// details directly instead of picking an existing CRM contact: the
// endpoint takes no `contact_id`.
import { useState } from "react";
import {
  bookAppointment,
  listCalendars,
  type Appointment,
  type AvailableSlot,
  type Calendar,
} from "@/lib/api/appointments";
import { formatInTimeZone } from "@/lib/appointments/datetime";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { AvailableSlotsPicker } from "./AvailableSlotsPicker";

export function BookAppointmentForm({
  tenantId,
  onBooked,
}: {
  tenantId: string;
  onBooked: (appointment: Appointment) => void;
}) {
  const calendarsQuery = useApiQuery(() => listCalendars(tenantId, { limit: 100 }), [tenantId]);
  const [calendarId, setCalendarId] = useState("");
  const [slot, setSlot] = useState<AvailableSlot | null>(null);
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");

  const { state, run } = useAsyncAction(() =>
    bookAppointment(tenantId, {
      calendar_id: calendarId,
      contact_email: email.trim(),
      contact_first_name: firstName.trim(),
      contact_last_name: lastName.trim(),
      contact_phone: phone.trim() || null,
      starts_at: (slot as AvailableSlot).starts_at,
      ends_at: (slot as AvailableSlot).ends_at,
    }),
  );

  if (calendarsQuery.status === "loading") return <LoadingState label="Loading calendars…" />;
  if (calendarsQuery.status === "error") {
    return <ApiErrorPanel error={calendarsQuery.error} onRetry={calendarsQuery.refetch} />;
  }

  const calendars: Calendar[] = calendarsQuery.data.results;
  if (calendars.length === 0) {
    return (
      <EmptyState
        title="No calendars yet"
        description="A booking needs a calendar with availability rules. Create one first."
      />
    );
  }

  const selectedCalendar = calendars.find((c) => c.id === calendarId) ?? null;
  const canSubmit =
    slot !== null &&
    selectedCalendar !== null &&
    email.trim().length > 0 &&
    firstName.trim().length > 0 &&
    lastName.trim().length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <section aria-labelledby="book-calendar-heading">
        <h2 id="book-calendar-heading" style={{ fontSize: "var(--font-size-md)" }}>
          1. Choose a calendar
        </h2>
        <Card>
          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              Calendar
            </span>
            <select
              aria-label="Calendar"
              value={calendarId}
              onChange={(event) => {
                setCalendarId(event.target.value);
                setSlot(null);
              }}
            >
              <option value="">Select a calendar…</option>
              {calendars.map((calendar) => (
                <option key={calendar.id} value={calendar.id}>
                  {calendar.name || "(unnamed)"} — {calendar.timezone}
                </option>
              ))}
            </select>
          </label>
        </Card>
      </section>

      {selectedCalendar ? (
        <section aria-labelledby="book-slot-heading">
          <h2 id="book-slot-heading" style={{ fontSize: "var(--font-size-md)" }}>
            2. Choose an available slot
          </h2>
          <Card>
            <AvailableSlotsPicker
              tenantId={tenantId}
              calendarId={selectedCalendar.id}
              timeZone={selectedCalendar.timezone}
              selectedSlotStart={slot?.starts_at ?? null}
              onSelect={setSlot}
            />
          </Card>
        </section>
      ) : null}

      {slot && selectedCalendar ? (
        <section aria-labelledby="book-contact-heading">
          <h2 id="book-contact-heading" style={{ fontSize: "var(--font-size-md)" }}>
            3. Contact details
          </h2>
          <Card>
            <p style={{ marginTop: 0, fontSize: "var(--font-size-sm)" }}>
              Booking <strong>{formatInTimeZone(slot.starts_at, selectedCalendar.timezone)}</strong>{" "}
              ({selectedCalendar.timezone})
            </p>
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                if (!canSubmit) return;
                const booked = await run();
                if (booked) {
                  setSlot(null);
                  setEmail("");
                  setFirstName("");
                  setLastName("");
                  setPhone("");
                  onBooked(booked);
                }
              }}
              style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
            >
              <Input
                label="Email"
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
              <Input
                label="First name"
                required
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
              />
              <Input
                label="Last name"
                required
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
              />
              <Input
                label="Phone (optional)"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
              />

              {state.status === "error" ? (
                <InlineNotice tone="danger">
                  {state.error.status === 409
                    ? "That slot was taken while you were filling this in. Pick another slot."
                    : state.error.message}
                </InlineNotice>
              ) : null}

              <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
                {state.status === "pending" ? "Booking…" : "Confirm booking"}
              </Button>
            </form>
          </Card>
        </section>
      ) : null}
    </div>
  );
}
